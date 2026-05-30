"""
core/mapper.py
--------------
Automatic and manual column mapping for GST reconciliation files.
Maps logical field names to actual dataframe column names using configurable aliases.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent.parent / "config" / "mapping.json"


def load_aliases():
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"mapping.json not found at {CONFIG_PATH}"
        )

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)

    return config["column_aliases"]


def normalize_col_name(name: str) -> str:
    """Normalize a column name for comparison (lowercase, strip whitespace)."""
    return str(name).strip().lower()


def auto_detect_columns(
    df: pd.DataFrame,
    aliases: Optional[Dict[str, List[str]]] = None,
) -> Tuple[Dict[str, str], List[str]]:
    """
    Automatically map logical field names to dataframe column names.

    Args:
        df: DataFrame with raw column names.
        aliases: Optional override for aliases dict.

    Returns:
        Tuple of:
          - col_map: Dict mapping logical_name -> actual_column_name
          - unmapped: List of logical fields that could not be auto-detected
    """
    if aliases is None:
        aliases = load_aliases()

    normalized_cols = {normalize_col_name(c): c for c in df.columns}
    col_map: Dict[str, str] = {}
    unmapped: List[str] = []

    for logical_name, alias_list in aliases.items():
        found = False
        for alias in alias_list:
            normalized_alias = normalize_col_name(alias)
            if normalized_alias in normalized_cols:
                col_map[logical_name] = normalized_cols[normalized_alias]
                logger.debug("Mapped '%s' -> '%s'", logical_name, col_map[logical_name])
                found = True
                break
        if not found:
            unmapped.append(logical_name)
            logger.debug("Could not auto-map field: '%s'", logical_name)

    required_fields = {"gstin", "invoice_number"}
    missing_required = required_fields - set(col_map.keys())
    if missing_required:
        logger.warning("Required fields not auto-mapped: %s", missing_required)

    return col_map, unmapped


def apply_manual_mapping(
    col_map: Dict[str, str],
    manual_overrides: Dict[str, str],
) -> Dict[str, str]:
    """
    Merge auto-detected mapping with user-provided manual overrides.

    Args:
        col_map: Auto-detected column map.
        manual_overrides: Dict of logical_name -> column_name from UI.

    Returns:
        Merged column map.
    """
    merged = {**col_map}
    for logical, actual in manual_overrides.items():
        if actual and actual != "-- Skip --":
            merged[logical] = actual
            logger.debug("Manual override: '%s' -> '%s'", logical, actual)
    return merged


def get_required_fields() -> List[str]:
    """Return the list of required logical field names for reconciliation."""
    return ["gstin", "invoice_number"]


def get_optional_fields() -> List[str]:
    """Return the list of optional logical field names."""
    return [
        "invoice_date", "taxable_value", "igst_amount",
        "cgst_amount", "sgst_amount", "total_gst",
        "invoice_value", "supplier_name", "place_of_supply", "gst_rate"
    ]


def get_field_display_names() -> Dict[str, str]:
    """Return human-readable display names for each logical field."""
    return {
        "gstin": "GSTIN / UIN",
        "invoice_number": "Invoice Number",
        "invoice_date": "Invoice Date",
        "taxable_value": "Taxable Value",
        "igst_amount": "IGST Amount",
        "cgst_amount": "CGST Amount",
        "sgst_amount": "SGST Amount",
        "total_gst": "Total GST Amount",
        "invoice_value": "Total Invoice Value",
        "supplier_name": "Supplier / Party Name",
        "place_of_supply": "Place of Supply",
        "gst_rate": "GST Rate (%)",
    }


def validate_mapping(col_map: Dict[str, str], df: pd.DataFrame) -> List[str]:
    """
    Validate that all mapped columns actually exist in the dataframe.

    Args:
        col_map: Column mapping dict.
        df: DataFrame to validate against.

    Returns:
        List of error messages. Empty if valid.
    """
    errors = []
    for logical, actual in col_map.items():
        if actual not in df.columns:
            errors.append(f"Mapped column '{actual}' for '{logical}' not found in file.")
    return errors
