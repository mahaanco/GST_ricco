"""
core/reconciler.py
------------------
Main orchestrator for the GST reconciliation pipeline.
Coordinates cleaning, validation, matching, fuzzy matching, and reporting.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, Optional

import pandas as pd

from core.cleaner import clean_dataframe
from core.duplicate_detector import detect_duplicates, remove_duplicates_keep_first
from core.fuzzy_matcher import (
    build_fuzzy_match_report,
    fuzzy_match_unmatched,
)
from core.matcher import check_amount_mismatch, check_date_mismatch, exact_match
from core.validator import get_invalid_gstin_report, validate_gstin_column

logger = logging.getLogger(__name__)


@dataclass
class ReconciliationConfig:
    """Configuration parameters for a reconciliation run."""

    reconciliation_type: str = "purchase"  # "purchase" or "sales"
    source_label: str = "Purchase Register"
    target_label: str = "GSTR-2B"
    amount_tolerance: float = 1.0
    date_tolerance_days: int = 3
    fuzzy_threshold: int = 95
    run_fuzzy: bool = True
    remove_duplicates: bool = False


@dataclass
class ReconciliationResult:
    """Complete result of a reconciliation run."""

    # Core match results
    matched: pd.DataFrame = field(default_factory=pd.DataFrame)
    missing_in_target: pd.DataFrame = field(default_factory=pd.DataFrame)
    missing_in_source: pd.DataFrame = field(default_factory=pd.DataFrame)
    amount_mismatch: pd.DataFrame = field(default_factory=pd.DataFrame)
    date_mismatch: pd.DataFrame = field(default_factory=pd.DataFrame)
    fuzzy_matches: pd.DataFrame = field(default_factory=pd.DataFrame)
    source_duplicates: pd.DataFrame = field(default_factory=pd.DataFrame)
    target_duplicates: pd.DataFrame = field(default_factory=pd.DataFrame)
    invalid_gstin_source: pd.DataFrame = field(default_factory=pd.DataFrame)
    invalid_gstin_target: pd.DataFrame = field(default_factory=pd.DataFrame)
    vendor_summary: pd.DataFrame = field(default_factory=pd.DataFrame)

    # Statistics
    total_source: int = 0
    total_target: int = 0
    matched_count: int = 0
    missing_in_target_count: int = 0
    missing_in_source_count: int = 0
    amount_mismatch_count: int = 0
    date_mismatch_count: int = 0
    fuzzy_match_count: int = 0
    source_duplicate_count: int = 0
    target_duplicate_count: int = 0
    invalid_gstin_source_count: int = 0
    invalid_gstin_target_count: int = 0
    match_percentage: float = 0.0

    # Config
    config: Optional[ReconciliationConfig] = None


def build_vendor_summary(
    missing_in_target: pd.DataFrame,
    amount_mismatch: pd.DataFrame,
    source_label: str = "Purchase Register",
) -> pd.DataFrame:
    """
    Build a vendor-level summary of mismatches.

    Groups by GSTIN and aggregates invoice count and GST amounts.

    Args:
        missing_in_target: Missing invoices DataFrame.
        amount_mismatch: Amount mismatch DataFrame.
        source_label: Label for the report.

    Returns:
        Summary DataFrame.
    """
    frames = []

    if not missing_in_target.empty and "_clean_gstin" in missing_in_target.columns:
        df = missing_in_target[["_clean_gstin", "_clean_total_gst"]].copy()
        df["issue_type"] = "Missing in Target"
        frames.append(df)

    if not amount_mismatch.empty and "_clean_gstin" in amount_mismatch.columns:
        df = amount_mismatch[["_clean_gstin", "_clean_total_gst_source"]].copy()
        df = df.rename(columns={"_clean_total_gst_source": "_clean_total_gst"})
        df["issue_type"] = "Amount Mismatch"
        frames.append(df)

    if not frames:
        return pd.DataFrame(
            columns=["GSTIN", "Issue Type", "Invoice Count", "Total GST Amount"]
        )

    combined = pd.concat(frames, ignore_index=True)
    summary = (
        combined.groupby(["_clean_gstin", "issue_type"])
        .agg(
            Invoice_Count=("_clean_gstin", "count"),
            Total_GST_Amount=("_clean_total_gst", "sum"),
        )
        .reset_index()
        .rename(columns={
            "_clean_gstin": "GSTIN",
            "issue_type": "Issue Type",
            "Invoice_Count": "Invoice Count",
            "Total_GST_Amount": "Total GST Amount",
        })
        .sort_values("Total GST Amount", ascending=False)
    )
    return summary


def run_reconciliation(
    source_df: pd.DataFrame,
    target_df: pd.DataFrame,
    source_col_map: Dict[str, str],
    target_col_map: Dict[str, str],
    config: ReconciliationConfig,
) -> ReconciliationResult:
    """
    Execute the full GST reconciliation pipeline.

    Steps:
    1. Clean both dataframes
    2. Validate GSTINs
    3. Detect duplicates
    4. Exact match
    5. Amount mismatch check
    6. Date mismatch check
    7. Fuzzy matching on unmatched
    8. Build vendor summary

    Args:
        source_df: Raw source DataFrame.
        target_df: Raw target DataFrame.
        source_col_map: Column mapping for source.
        target_col_map: Column mapping for target.
        config: Reconciliation configuration.

    Returns:
        ReconciliationResult with all outputs populated.
    """
    result = ReconciliationResult(config=config)

    logger.info("Starting reconciliation: %s vs %s", config.source_label, config.target_label)

    # Step 1: Clean
    logger.info("Step 1: Cleaning data...")
    source_clean = clean_dataframe(source_df, source_col_map)
    target_clean = clean_dataframe(target_df, target_col_map)

    # Step 2: GSTIN Validation
    logger.info("Step 2: Validating GSTINs...")
    source_clean = validate_gstin_column(source_clean)
    target_clean = validate_gstin_column(target_clean)

    result.invalid_gstin_source = get_invalid_gstin_report(source_clean, config.source_label)
    result.invalid_gstin_target = get_invalid_gstin_report(target_clean, config.target_label)
    result.invalid_gstin_source_count = len(result.invalid_gstin_source)
    result.invalid_gstin_target_count = len(result.invalid_gstin_target)

    # Step 3: Duplicate Detection
    logger.info("Step 3: Detecting duplicates...")
    result.source_duplicates = detect_duplicates(source_clean, config.source_label)
    result.target_duplicates = detect_duplicates(target_clean, config.target_label)
    result.source_duplicate_count = len(
        result.source_duplicates.drop_duplicates("_match_key") if not result.source_duplicates.empty else result.source_duplicates
    )
    result.target_duplicate_count = len(
        result.target_duplicates.drop_duplicates("_match_key") if not result.target_duplicates.empty else result.target_duplicates
    )

    # Optionally remove duplicates before matching
    if config.remove_duplicates:
        source_clean = remove_duplicates_keep_first(source_clean)
        target_clean = remove_duplicates_keep_first(target_clean)

    result.total_source = len(source_clean)
    result.total_target = len(target_clean)

    # Step 4: Exact Match
    logger.info("Step 4: Exact matching...")
    matched_source, unmatched_source, unmatched_target = exact_match(source_clean, target_clean)

    result.matched = matched_source
    result.missing_in_target = unmatched_source
    result.missing_in_source = unmatched_target
    result.matched_count = len(matched_source)
    result.missing_in_target_count = len(unmatched_source)
    result.missing_in_source_count = len(unmatched_target)

    matched_keys = matched_source["_match_key"]

    # Step 5: Amount Mismatch
    logger.info("Step 5: Checking amount mismatches...")
    result.amount_mismatch = check_amount_mismatch(
        source_clean, target_clean, matched_keys, config.amount_tolerance
    )
    result.amount_mismatch_count = len(result.amount_mismatch)

    # Step 6: Date Mismatch
    logger.info("Step 6: Checking date mismatches...")
    result.date_mismatch = check_date_mismatch(
        source_clean, target_clean, matched_keys, config.date_tolerance_days
    )
    result.date_mismatch_count = len(result.date_mismatch)

    # Step 7: Fuzzy Matching
    if config.run_fuzzy and not unmatched_source.empty and not unmatched_target.empty:
        logger.info("Step 7: Running fuzzy matching (threshold=%d)...", config.fuzzy_threshold)
        fuzzy_matches = fuzzy_match_unmatched(
            unmatched_source, unmatched_target, config.fuzzy_threshold
        )
        result.fuzzy_matches = build_fuzzy_match_report(
            fuzzy_matches, source_clean, target_clean
        )
        result.fuzzy_match_count = len(result.fuzzy_matches)
    else:
        result.fuzzy_match_count = 0

    # Step 8: Vendor Summary
    logger.info("Step 8: Building vendor summary...")
    result.vendor_summary = build_vendor_summary(
        result.missing_in_target,
        result.amount_mismatch,
        config.source_label,
    )

    # Compute match percentage
    if result.total_source > 0:
        result.match_percentage = round(
            (result.matched_count / result.total_source) * 100, 2
        )

    logger.info(
        "Reconciliation complete. Matched: %d/%.2f%%, Missing: %d, "
        "Amount Mismatches: %d, Fuzzy: %d",
        result.matched_count,
        result.match_percentage,
        result.missing_in_target_count,
        result.amount_mismatch_count,
        result.fuzzy_match_count,
    )

    return result
