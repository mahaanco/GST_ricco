"""
core/fuzzy_matcher.py
---------------------
Fuzzy matching for invoice numbers using RapidFuzz.
Handles cases like INV001 vs INV-001, A100 vs A/100.
"""

import logging
from typing import List, Optional, Tuple

import pandas as pd
from rapidfuzz import fuzz, process

logger = logging.getLogger(__name__)


def build_fuzzy_index(df: pd.DataFrame) -> dict:
    """
    Build a lookup dictionary of match_key -> row index for fuzzy search.

    Args:
        df: DataFrame with `_match_key` column.

    Returns:
        Dict mapping match_key string to row index list.
    """
    index = {}
    for idx, key in df["_match_key"].items():
        if key not in index:
            index[key] = []
        index[key].append(idx)
    return index


def fuzzy_match_unmatched(
    unmatched_source: pd.DataFrame,
    unmatched_target: pd.DataFrame,
    threshold: int = 95,
) -> List[dict]:
    """
    Perform fuzzy matching on invoice numbers for records not exact-matched.

    Strategy:
    - Groups unmatched records by GSTIN
    - For each GSTIN group, runs fuzzy matching on invoice numbers
    - Only considers matches above the threshold

    Args:
        unmatched_source: Source rows not exact-matched, with `_clean_gstin`
                          and `_clean_invoice_number`.
        unmatched_target: Target rows not exact-matched.
        threshold: Minimum fuzzy score (0-100). Default 95.

    Returns:
        List of dicts describing fuzzy matches:
            {
                'source_idx': int,
                'target_idx': int,
                'source_invoice': str,
                'target_invoice': str,
                'fuzzy_score': float,
                'gstin': str,
            }
    """
    if unmatched_source.empty or unmatched_target.empty:
        return []

    fuzzy_matches = []

    # Group target by GSTIN for efficient lookup
    target_by_gstin = {}
    for idx, row in unmatched_target.iterrows():
        gstin = row["_clean_gstin"]
        if gstin not in target_by_gstin:
            target_by_gstin[gstin] = []
        target_by_gstin[gstin].append((idx, row["_clean_invoice_number"]))

    for src_idx, src_row in unmatched_source.iterrows():
        gstin = src_row["_clean_gstin"]
        src_inv = src_row["_clean_invoice_number"]

        if not gstin or not src_inv:
            continue

        candidates = target_by_gstin.get(gstin, [])
        if not candidates:
            continue

        candidate_invoices = [c[1] for c in candidates]
        candidate_indices = [c[0] for c in candidates]

        # Find best match using token_sort_ratio for robustness
        results = process.extract(
            src_inv,
            candidate_invoices,
            scorer=fuzz.token_sort_ratio,
            limit=1,
            score_cutoff=threshold,
        )

        if results:
            best_match_inv, score, best_pos = results[0]
            tgt_idx = candidate_indices[best_pos]

            fuzzy_matches.append({
                "source_idx": src_idx,
                "target_idx": tgt_idx,
                "source_invoice": src_inv,
                "target_invoice": best_match_inv,
                "fuzzy_score": round(score, 2),
                "gstin": gstin,
            })
            logger.debug(
                "Fuzzy match: GSTIN=%s, '%s' ~ '%s' (score=%.1f)",
                gstin, src_inv, best_match_inv, score,
            )

    logger.info(
        "Fuzzy matching: %d matches found from %d unmatched source records.",
        len(fuzzy_matches),
        len(unmatched_source),
    )
    return fuzzy_matches


def build_fuzzy_match_report(
    fuzzy_matches: List[dict],
    source_df: pd.DataFrame,
    target_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Convert fuzzy match results into a readable report DataFrame.

    Args:
        fuzzy_matches: Output of fuzzy_match_unmatched.
        source_df: Original source DataFrame.
        target_df: Original target DataFrame.

    Returns:
        DataFrame with columns for source and target invoice details.
    """
    if not fuzzy_matches:
        return pd.DataFrame()

    rows = []
    for match in fuzzy_matches:
        src_row = source_df.loc[match["source_idx"]]
        tgt_row = target_df.loc[match["target_idx"]]

        rows.append({
            "GSTIN": match["gstin"],
            "Source Invoice": match["source_invoice"],
            "Target Invoice": match["target_invoice"],
            "Fuzzy Score": match["fuzzy_score"],
            "Source Taxable Value": src_row.get("_clean_taxable_value", ""),
            "Target Taxable Value": tgt_row.get("_clean_taxable_value", ""),
            "Source GST Amount": src_row.get("_clean_total_gst", ""),
            "Target GST Amount": tgt_row.get("_clean_total_gst", ""),
            "Source Date": src_row.get("_clean_invoice_date", ""),
            "Target Date": tgt_row.get("_clean_invoice_date", ""),
            "Remark": "Possible match (invoice format difference)",
        })

    return pd.DataFrame(rows)
