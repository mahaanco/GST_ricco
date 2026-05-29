"""
core/cleaner.py
---------------
Data cleaning utilities for GST reconciliation.
Handles invoice numbers, GSTINs, dates, and monetary amounts.
"""

import re
import logging
from typing import Optional

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


def clean_invoice_number(value) -> str:
    """
    Normalize invoice number by removing spaces, special characters,
    and converting to uppercase.

    Examples:
        INV-001  -> INV001
        A/100    -> A100
        inv 001  -> INV001
        INV_001  -> INV001

    Args:
        value: Raw invoice number (str, int, float, or NaN)

    Returns:
        Cleaned invoice number string. Empty string if null/invalid.
    """
    if pd.isna(value) or value is None:
        return ""
    raw = str(value).strip()
    # Remove common separators and special characters
    cleaned = re.sub(r"[\s\-/\\_.,()\[\]{}#@!*&^%$~`'\"]", "", raw)
    return cleaned.upper()


def clean_gstin(value) -> str:
    """
    Normalize GSTIN by trimming whitespace and converting to uppercase.

    Args:
        value: Raw GSTIN value.

    Returns:
        Cleaned GSTIN string. Empty string if null.
    """
    if pd.isna(value) or value is None:
        return ""
    return str(value).strip().upper()


def clean_amount(value) -> Optional[float]:
    """
    Convert amount fields to float.
    Handles values with commas, currency symbols, and parentheses (negatives).

    Args:
        value: Raw amount value.

    Returns:
        Float amount, or NaN if conversion fails.
    """
    if pd.isna(value) or value is None:
        return np.nan
    raw = str(value).strip()
    # Remove currency symbols and whitespace
    raw = re.sub(r"[₹$£€,\s]", "", raw)
    # Handle parentheses as negative numbers: (1000) -> -1000
    if raw.startswith("(") and raw.endswith(")"):
        raw = "-" + raw[1:-1]
    try:
        return float(raw)
    except ValueError:
        logger.debug("Could not convert amount value: %s", value)
        return np.nan


def clean_date(value) -> Optional[pd.Timestamp]:
    """
    Parse date strings into pandas Timestamp objects.
    Tries multiple common Indian date formats.

    Args:
        value: Raw date value.

    Returns:
        pandas Timestamp or NaT if parsing fails.
    """
    if pd.isna(value) or value is None:
        return pd.NaT

    # Already a datetime
    if isinstance(value, (pd.Timestamp,)):
        return value

    raw = str(value).strip()
    formats = [
        "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y",
        "%d/%m/%y", "%d-%m-%y",
        "%Y-%m-%d", "%Y/%m/%d",
        "%d %b %Y", "%d %B %Y",
        "%b %d, %Y", "%B %d, %Y",
        "%d-%b-%Y", "%d-%b-%y",
    ]
    for fmt in formats:
        try:
            return pd.to_datetime(raw, format=fmt)
        except (ValueError, TypeError):
            continue

    # Fallback: let pandas infer
    try:
        return pd.to_datetime(raw, infer_datetime_format=True, dayfirst=True)
    except Exception:
        logger.debug("Could not parse date: %s", value)
        return pd.NaT


def clean_dataframe(
    df: pd.DataFrame,
    col_map: dict,
) -> pd.DataFrame:
    """
    Apply all cleaning operations to a dataframe based on the detected column mapping.

    Args:
        df: Raw dataframe.
        col_map: Dictionary mapping logical names to actual column names.
                 e.g. {"gstin": "Supplier GSTIN", "invoice_number": "Bill No", ...}

    Returns:
        Cleaned dataframe with standardized columns added (prefixed with `_clean_`).
    """
    df = df.copy()

    # GSTIN
    if "gstin" in col_map and col_map["gstin"] in df.columns:
        df["_clean_gstin"] = df[col_map["gstin"]].apply(clean_gstin)
    else:
        df["_clean_gstin"] = ""

    # Invoice Number
    if "invoice_number" in col_map and col_map["invoice_number"] in df.columns:
        df["_clean_invoice_number"] = df[col_map["invoice_number"]].apply(clean_invoice_number)
    else:
        df["_clean_invoice_number"] = ""

    # Invoice Date
    if "invoice_date" in col_map and col_map["invoice_date"] in df.columns:
        df["_clean_invoice_date"] = df[col_map["invoice_date"]].apply(clean_date)
    else:
        df["_clean_invoice_date"] = pd.NaT

    # Amount fields
    amount_fields = [
        "taxable_value", "igst_amount", "cgst_amount",
        "sgst_amount", "total_gst", "invoice_value"
    ]
    for field in amount_fields:
        if field in col_map and col_map[field] in df.columns:
            df[f"_clean_{field}"] = df[col_map[field]].apply(clean_amount)
        else:
            df[f"_clean_{field}"] = np.nan

    # Compute total GST if not present but components exist
    if df["_clean_total_gst"].isna().all():
        components = ["_clean_igst_amount", "_clean_cgst_amount", "_clean_sgst_amount"]
        available = [c for c in components if not df[c].isna().all()]
        if available:
            df["_clean_total_gst"] = df[available].fillna(0).sum(axis=1)

    # Composite match key
    df["_match_key"] = df["_clean_gstin"] + "||" + df["_clean_invoice_number"]

    logger.info("DataFrame cleaned: %d rows, match keys generated.", len(df))
    return df
