"""
core/matcher.py
---------------
Core matching engine for GST reconciliation.
Implements exact matching, amount tolerance checks, and date tolerance checks.
Uses vectorized pandas operations for performance on 10,000+ row datasets.
"""

import logging
from typing import Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def exact_match(
    source_df: pd.DataFrame,
    target_df: pd.DataFrame,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Match records using the composite key: GSTIN + Invoice Number.

    Args:
        source_df: Cleaned source DataFrame with `_match_key`.
        target_df: Cleaned target DataFrame with `_match_key`.

    Returns:
        Tuple of:
          - matched_source: Source rows that have a match in target
          - unmatched_source: Source rows with no match in target
          - unmatched_target: Target rows with no match in source
    """
    source_keys = set(source_df["_match_key"].values)
    target_keys = set(target_df["_match_key"].values)

    common_keys = source_keys & target_keys
    only_in_source = source_keys - target_keys
    only_in_target = target_keys - source_keys

    matched_source = source_df[source_df["_match_key"].isin(common_keys)].copy()
    unmatched_source = source_df[source_df["_match_key"].isin(only_in_source)].copy()
    unmatched_target = target_df[target_df["_match_key"].isin(only_in_target)].copy()

    logger.info(
        "Exact match: %d matched, %d missing in target, %d missing in source.",
        len(matched_source),
        len(unmatched_source),
        len(unmatched_target),
    )

    return matched_source, unmatched_source, unmatched_target


def check_amount_mismatch(
    source_df: pd.DataFrame,
    target_df: pd.DataFrame,
    matched_keys: pd.Index,
    tolerance: float = 1.0,
) -> pd.DataFrame:
    """
    Among exact-matched records, find those where GST amounts differ beyond tolerance.

    Uses vectorized merge for performance.

    Args:
        source_df: Source DataFrame (cleaned).
        target_df: Target DataFrame (cleaned).
        matched_keys: Index of `_match_key` values that are exact matches.
        tolerance: Maximum acceptable GST amount difference (default ±1 rupee).

    Returns:
        DataFrame of mismatched records with source/target amounts.
    """
    src_matched = source_df[source_df["_match_key"].isin(matched_keys)].copy()
    tgt_matched = target_df[target_df["_match_key"].isin(matched_keys)].copy()

    # Deduplicate on key before merge to avoid cartesian explosion
    src_matched = src_matched.drop_duplicates(subset=["_match_key"])
    tgt_matched = tgt_matched.drop_duplicates(subset=["_match_key"])

    merged = src_matched[["_match_key", "_clean_total_gst"]].merge(
        tgt_matched[["_match_key", "_clean_total_gst"]],
        on="_match_key",
        suffixes=("_src", "_tgt"),
    )

    # Fill NaN with 0 for comparison
    merged["_clean_total_gst_src"] = merged["_clean_total_gst_src"].fillna(0)
    merged["_clean_total_gst_tgt"] = merged["_clean_total_gst_tgt"].fillna(0)

    merged["_amount_diff"] = (
        merged["_clean_total_gst_src"] - merged["_clean_total_gst_tgt"]
    ).abs()

    mismatch_keys = merged[merged["_amount_diff"] > tolerance]["_match_key"]

    if mismatch_keys.empty:
        return pd.DataFrame()

    src_mismatch = src_matched[src_matched["_match_key"].isin(mismatch_keys)].copy()
    tgt_mismatch = tgt_matched[tgt_matched["_match_key"].isin(mismatch_keys)].copy()

    result = src_mismatch[["_match_key", "_clean_gstin", "_clean_invoice_number", "_clean_total_gst"]].merge(
        tgt_mismatch[["_match_key", "_clean_total_gst"]],
        on="_match_key",
        suffixes=("_source", "_target"),
    )
    result["_amount_diff"] = (
        result["_clean_total_gst_source"] - result["_clean_total_gst_target"]
    ).abs()
    result["_tolerance"] = tolerance

    logger.info(
        "Amount mismatch (tolerance=%.2f): %d records.", tolerance, len(result)
    )
    return result


def check_date_mismatch(
    source_df: pd.DataFrame,
    target_df: pd.DataFrame,
    matched_keys: pd.Index,
    tolerance_days: int = 3,
) -> pd.DataFrame:
    """
    Among exact-matched records, find those where invoice dates differ beyond tolerance.

    Args:
        source_df: Source DataFrame (cleaned).
        target_df: Target DataFrame (cleaned).
        matched_keys: Set of `_match_key` values that are exact matches.
        tolerance_days: Maximum acceptable date difference in days (default 3).

    Returns:
        DataFrame of date-mismatched records.
    """
    src_matched = source_df[source_df["_match_key"].isin(matched_keys)].copy()
    tgt_matched = target_df[target_df["_match_key"].isin(matched_keys)].copy()

    # Skip if date column is missing
    if "_clean_invoice_date" not in src_matched.columns or "_clean_invoice_date" not in tgt_matched.columns:
        return pd.DataFrame()

    src_has_dates = src_matched["_clean_invoice_date"].notna().any()
    tgt_has_dates = tgt_matched["_clean_invoice_date"].notna().any()
    if not src_has_dates or not tgt_has_dates:
        return pd.DataFrame()

    src_matched = src_matched.drop_duplicates(subset=["_match_key"])
    tgt_matched = tgt_matched.drop_duplicates(subset=["_match_key"])

    merged = src_matched[["_match_key", "_clean_invoice_date"]].merge(
        tgt_matched[["_match_key", "_clean_invoice_date"]],
        on="_match_key",
        suffixes=("_src", "_tgt"),
    )

    # Convert to datetime and compute diff in days
    merged["_date_diff_days"] = (
        pd.to_datetime(merged["_clean_invoice_date_src"], errors="coerce")
        - pd.to_datetime(merged["_clean_invoice_date_tgt"], errors="coerce")
    ).abs().dt.days

    mismatch_keys = merged[merged["_date_diff_days"] > tolerance_days]["_match_key"]

    if mismatch_keys.empty:
        return pd.DataFrame()

    src_mismatch = src_matched[src_matched["_match_key"].isin(mismatch_keys)].copy()
    tgt_mismatch = tgt_matched[tgt_matched["_match_key"].isin(mismatch_keys)].copy()

    result = src_mismatch[["_match_key", "_clean_gstin", "_clean_invoice_number", "_clean_invoice_date"]].merge(
        tgt_mismatch[["_match_key", "_clean_invoice_date"]],
        on="_match_key",
        suffixes=("_source", "_target"),
    )
    result["_date_diff_days"] = (
        pd.to_datetime(result["_clean_invoice_date_source"], errors="coerce")
        - pd.to_datetime(result["_clean_invoice_date_target"], errors="coerce")
    ).abs().dt.days
    result["_tolerance_days"] = tolerance_days

    logger.info(
        "Date mismatch (tolerance=%d days): %d records.", tolerance_days, len(result)
    )
    return result
