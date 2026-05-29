"""
reports/summary.py
------------------
Builds the summary sheet for the Excel report.
"""

import pandas as pd
from datetime import datetime

from core.reconciler import ReconciliationResult


def build_summary_df(result: ReconciliationResult) -> pd.DataFrame:
    """
    Build a summary DataFrame for inclusion in the Excel report.

    Args:
        result: Completed ReconciliationResult.

    Returns:
        DataFrame with two columns: Metric, Value.
    """
    config = result.config
    source_label = config.source_label if config else "Source"
    target_label = config.target_label if config else "Target"

    rows = [
        ("Reconciliation Type", f"{source_label} vs {target_label}"),
        ("Generated On", datetime.now().strftime("%d-%b-%Y %H:%M:%S")),
        ("", ""),
        ("=== FILE STATISTICS ===", ""),
        (f"Total Records in {source_label}", result.total_source),
        (f"Total Records in {target_label}", result.total_target),
        ("", ""),
        ("=== MATCH RESULTS ===", ""),
        ("Matched Records", result.matched_count),
        ("Match Percentage", f"{result.match_percentage:.2f}%"),
        (f"Missing in {target_label} (in source but not target)", result.missing_in_target_count),
        (f"Missing in {source_label} (in target but not source)", result.missing_in_source_count),
        ("", ""),
        ("=== DISCREPANCIES ===", ""),
        ("Amount Mismatches", result.amount_mismatch_count),
        ("Date Mismatches", result.date_mismatch_count),
        ("Fuzzy Matches (possible)", result.fuzzy_match_count),
        ("", ""),
        ("=== DATA QUALITY ===", ""),
        (f"Duplicate Records in {source_label}", result.source_duplicate_count),
        (f"Duplicate Records in {target_label}", result.target_duplicate_count),
        (f"Invalid GSTINs in {source_label}", result.invalid_gstin_source_count),
        (f"Invalid GSTINs in {target_label}", result.invalid_gstin_target_count),
        ("", ""),
        ("=== CONFIGURATION ===", ""),
        ("Amount Tolerance (₹)", config.amount_tolerance if config else "-"),
        ("Date Tolerance (days)", config.date_tolerance_days if config else "-"),
        ("Fuzzy Match Threshold (%)", config.fuzzy_threshold if config else "-"),
    ]

    return pd.DataFrame(rows, columns=["Metric", "Value"])
