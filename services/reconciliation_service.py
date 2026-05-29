"""
services/reconciliation_service.py
------------------------------------
Service layer for running reconciliation and managing results.
Acts as the bridge between Streamlit UI and core reconciliation logic.
"""

import logging
from typing import Dict, Optional

import pandas as pd

from core.mapper import apply_manual_mapping
from core.reconciler import ReconciliationConfig, ReconciliationResult, run_reconciliation

logger = logging.getLogger(__name__)


def build_config(
    reconciliation_type: str,
    amount_tolerance: float,
    date_tolerance_days: int,
    fuzzy_threshold: int,
    run_fuzzy: bool,
    remove_duplicates: bool,
) -> ReconciliationConfig:
    """
    Build a ReconciliationConfig from UI parameters.

    Args:
        reconciliation_type: "purchase" or "sales"
        amount_tolerance: GST amount tolerance in rupees.
        date_tolerance_days: Date tolerance in days.
        fuzzy_threshold: Fuzzy match score threshold (0-100).
        run_fuzzy: Whether to run fuzzy matching.
        remove_duplicates: Whether to deduplicate before matching.

    Returns:
        ReconciliationConfig instance.
    """
    type_labels = {
        "purchase": ("Purchase Register", "GSTR-2B"),
        "sales": ("Sales Register", "GSTR-1"),
    }
    source_label, target_label = type_labels.get(
        reconciliation_type, ("Source File", "Target File")
    )

    return ReconciliationConfig(
        reconciliation_type=reconciliation_type,
        source_label=source_label,
        target_label=target_label,
        amount_tolerance=amount_tolerance,
        date_tolerance_days=date_tolerance_days,
        fuzzy_threshold=fuzzy_threshold,
        run_fuzzy=run_fuzzy,
        remove_duplicates=remove_duplicates,
    )


def execute_reconciliation(
    source_df: pd.DataFrame,
    target_df: pd.DataFrame,
    source_col_map: Dict[str, str],
    target_col_map: Dict[str, str],
    source_manual_overrides: Optional[Dict[str, str]],
    target_manual_overrides: Optional[Dict[str, str]],
    config: ReconciliationConfig,
) -> ReconciliationResult:
    """
    Apply manual overrides to column maps and run reconciliation.

    Args:
        source_df: Source DataFrame.
        target_df: Target DataFrame.
        source_col_map: Auto-detected source column map.
        target_col_map: Auto-detected target column map.
        source_manual_overrides: User-provided overrides for source.
        target_manual_overrides: User-provided overrides for target.
        config: Reconciliation configuration.

    Returns:
        ReconciliationResult.
    """
    # Apply manual overrides if provided
    final_source_map = apply_manual_mapping(
        source_col_map, source_manual_overrides or {}
    )
    final_target_map = apply_manual_mapping(
        target_col_map, target_manual_overrides or {}
    )

    logger.info(
        "Starting reconciliation. Source map: %d fields, Target map: %d fields.",
        len(final_source_map),
        len(final_target_map),
    )

    return run_reconciliation(
        source_df=source_df,
        target_df=target_df,
        source_col_map=final_source_map,
        target_col_map=final_target_map,
        config=config,
    )


def get_summary_stats(result: ReconciliationResult) -> Dict:
    """
    Extract key statistics from a ReconciliationResult for display.

    Args:
        result: Completed ReconciliationResult.

    Returns:
        Dict with display-ready statistics.
    """
    return {
        "total_source": result.total_source,
        "total_target": result.total_target,
        "matched": result.matched_count,
        "match_pct": result.match_percentage,
        "missing_in_target": result.missing_in_target_count,
        "missing_in_source": result.missing_in_source_count,
        "amount_mismatch": result.amount_mismatch_count,
        "date_mismatch": result.date_mismatch_count,
        "fuzzy_matches": result.fuzzy_match_count,
        "source_duplicates": result.source_duplicate_count,
        "target_duplicates": result.target_duplicate_count,
        "invalid_gstin_source": result.invalid_gstin_source_count,
        "invalid_gstin_target": result.invalid_gstin_target_count,
    }
