"""
core/duplicate_detector.py
--------------------------
Detects duplicate invoice records within a single file.
Uses the composite key of GSTIN + Invoice Number.
"""

import logging

import pandas as pd

logger = logging.getLogger(__name__)


def detect_duplicates(df: pd.DataFrame, source_label: str = "File") -> pd.DataFrame:
    """
    Identify rows where the GSTIN + Invoice Number combination appears more than once.

    Args:
        df: Cleaned DataFrame with `_match_key` column.
        source_label: Label to annotate the source in the output.

    Returns:
        DataFrame of duplicate rows, with a `_duplicate_count` column showing
        how many times each key appears.
    """
    if "_match_key" not in df.columns:
        logger.warning("'_match_key' column not found. Skipping duplicate detection.")
        return pd.DataFrame()

    # Count occurrences of each match key
    key_counts = df["_match_key"].value_counts()
    duplicate_keys = key_counts[key_counts > 1].index

    if len(duplicate_keys) == 0:
        logger.info("No duplicates found in %s.", source_label)
        return pd.DataFrame()

    dup_df = df[df["_match_key"].isin(duplicate_keys)].copy()
    dup_df["_duplicate_count"] = dup_df["_match_key"].map(key_counts)
    dup_df["_source_label"] = source_label

    # Sort so duplicates are grouped together
    dup_df = dup_df.sort_values("_match_key").reset_index(drop=True)

    logger.info(
        "Duplicates in %s: %d unique keys, %d total rows.",
        source_label,
        len(duplicate_keys),
        len(dup_df),
    )
    return dup_df


def remove_duplicates_keep_first(df: pd.DataFrame) -> pd.DataFrame:
    """
    Remove duplicates from a DataFrame, keeping the first occurrence of each
    GSTIN + Invoice Number combination.

    Args:
        df: Cleaned DataFrame with `_match_key` column.

    Returns:
        DataFrame with duplicates removed (first occurrence retained).
    """
    if "_match_key" not in df.columns:
        return df

    before = len(df)
    df_deduped = df.drop_duplicates(subset=["_match_key"], keep="first").copy()
    removed = before - len(df_deduped)

    if removed > 0:
        logger.info("Removed %d duplicate rows (kept first occurrence).", removed)

    return df_deduped
