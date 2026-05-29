"""
core/validator.py
-----------------
GSTIN validation utilities.
Validates the 15-character GSTIN structure per Indian GST rules.
"""

import re
import logging
from typing import Tuple

import pandas as pd

logger = logging.getLogger(__name__)

# Official GSTIN regex pattern
GSTIN_PATTERN = re.compile(
    r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$"
)

# Valid state codes as per GST Act
VALID_STATE_CODES = {
    "01", "02", "03", "04", "05", "06", "07", "08", "09", "10",
    "11", "12", "13", "14", "15", "16", "17", "18", "19", "20",
    "21", "22", "23", "24", "25", "26", "27", "28", "29", "30",
    "31", "32", "33", "34", "35", "36", "37", "38", "97", "99",
}

STATE_CODE_MAP = {
    "01": "Jammu & Kashmir", "02": "Himachal Pradesh", "03": "Punjab",
    "04": "Chandigarh", "05": "Uttarakhand", "06": "Haryana",
    "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh",
    "10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh",
    "13": "Nagaland", "14": "Manipur", "15": "Mizoram",
    "16": "Tripura", "17": "Meghalaya", "18": "Assam",
    "19": "West Bengal", "20": "Jharkhand", "21": "Odisha",
    "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat",
    "25": "Daman & Diu", "26": "Dadra & Nagar Haveli", "27": "Maharashtra",
    "28": "Andhra Pradesh (Old)", "29": "Karnataka", "30": "Goa",
    "31": "Lakshadweep", "32": "Kerala", "33": "Tamil Nadu",
    "34": "Puducherry", "35": "Andaman & Nicobar Islands",
    "36": "Telangana", "37": "Andhra Pradesh", "38": "Ladakh",
    "97": "Other Territory", "99": "Centre Jurisdiction",
}


def validate_gstin(gstin: str) -> Tuple[bool, str]:
    """
    Validate a single GSTIN string.

    Args:
        gstin: Cleaned (uppercase, trimmed) GSTIN string.

    Returns:
        Tuple of (is_valid: bool, error_reason: str).
        error_reason is empty string if valid.
    """
    if not gstin:
        return False, "Empty GSTIN"

    if len(gstin) != 15:
        return False, f"Invalid length: {len(gstin)} (expected 15)"

    state_code = gstin[:2]
    if state_code not in VALID_STATE_CODES:
        return False, f"Invalid state code: {state_code}"

    if not GSTIN_PATTERN.match(gstin):
        return False, "Does not match GSTIN format"

    return True, ""


def validate_gstin_column(df: pd.DataFrame) -> pd.DataFrame:
    """
    Validate all GSTINs in a dataframe's `_clean_gstin` column.

    Adds two columns:
      - `_gstin_valid`: bool
      - `_gstin_error`: error reason string

    Args:
        df: DataFrame with `_clean_gstin` column.

    Returns:
        DataFrame with validation columns added.
    """
    df = df.copy()

    def _validate(gstin: str) -> Tuple[bool, str]:
        return validate_gstin(gstin)

    results = df["_clean_gstin"].apply(_validate)
    df["_gstin_valid"] = results.apply(lambda x: x[0])
    df["_gstin_error"] = results.apply(lambda x: x[1])

    invalid_count = (~df["_gstin_valid"]).sum()
    logger.info("GSTIN validation: %d invalid out of %d records.", invalid_count, len(df))

    return df


def get_invalid_gstin_report(df: pd.DataFrame, source_label: str) -> pd.DataFrame:
    """
    Extract rows with invalid GSTINs into a report DataFrame.

    Args:
        df: DataFrame after validate_gstin_column.
        source_label: Label for source column (e.g. "Purchase Register").

    Returns:
        DataFrame containing invalid GSTIN rows with reason.
    """
    invalid = df[~df["_gstin_valid"]].copy()
    if invalid.empty:
        return pd.DataFrame(columns=["Source", "Row Number", "GSTIN", "Error Reason"])

    report_rows = []
    for idx, row in invalid.iterrows():
        report_rows.append({
            "Source": source_label,
            "Row Number": idx + 1,
            "GSTIN": row.get("_clean_gstin", ""),
            "Error Reason": row.get("_gstin_error", ""),
        })

    return pd.DataFrame(report_rows)
