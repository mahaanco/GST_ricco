"""
services/upload_service.py
---------------------------
Service layer for handling file uploads.
Validates files, reads them, and prepares them for reconciliation.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import pandas as pd

from core.mapper import (
    auto_detect_columns,
    get_field_display_names,
    get_optional_fields,
    get_required_fields,
    validate_mapping,
)
from parsers.file_reader import get_sheet_names, read_uploaded_file

logger = logging.getLogger(__name__)

MAX_FILE_SIZE_MB = 50
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024


@dataclass
class UploadResult:
    """Result of processing an uploaded file."""

    success: bool = False
    df: Optional[pd.DataFrame] = None
    filename: str = ""
    file_type: str = ""
    header_row: int = 0
    sheet_names: List[str] = field(default_factory=list)
    selected_sheet: str = ""
    col_map: Dict[str, str] = field(default_factory=dict)
    unmapped_fields: List[str] = field(default_factory=list)
    needs_manual_mapping: bool = False
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    row_count: int = 0
    col_count: int = 0


def process_uploaded_file(
    file_buffer,
    filename: str,
    sheet_name: Optional[str] = None,
) -> UploadResult:
    """
    Process an uploaded file: read, detect columns, validate.

    Args:
        file_buffer: Streamlit UploadedFile or file-like object.
        filename: Original filename.
        sheet_name: Sheet to read (Excel only).

    Returns:
        UploadResult with all details populated.
    """
    result = UploadResult(filename=filename)

    # Validate file size
    if hasattr(file_buffer, "size") and file_buffer.size > MAX_FILE_SIZE_BYTES:
        result.errors.append(
            f"File too large: {file_buffer.size / 1024 / 1024:.1f} MB "
            f"(max {MAX_FILE_SIZE_MB} MB)."
        )
        return result

    # Get sheet names if Excel
    try:
        if hasattr(file_buffer, "seek"):
            file_buffer.seek(0)
        sheets = get_sheet_names(file_buffer, filename)
        result.sheet_names = sheets
        if hasattr(file_buffer, "seek"):
            file_buffer.seek(0)
    except Exception:
        result.sheet_names = []

    # Read the file
    try:
        df, header_row, file_type = read_uploaded_file(
            file_buffer, filename, sheet_name=sheet_name
        )
    except ValueError as e:
        result.errors.append(str(e))
        return result

    result.df = df
    result.file_type = file_type
    result.header_row = header_row
    result.row_count = len(df)
    result.col_count = len(df.columns)

    if df.empty:
        result.errors.append("File contains no data rows.")
        return result

    if len(df.columns) < 2:
        result.errors.append("File has too few columns to process.")
        return result

    # Auto-detect column mapping
    col_map, unmapped = auto_detect_columns(df)
    result.col_map = col_map
    result.unmapped_fields = unmapped

    # Check if required fields are mapped
    required = get_required_fields()
    missing_required = [f for f in required if f not in col_map]

    if missing_required:
        result.needs_manual_mapping = True
        result.warnings.append(
            f"Could not auto-detect required columns: "
            f"{', '.join(get_field_display_names().get(f, f) for f in missing_required)}. "
            "Please map them manually."
        )
    else:
        # Validate that mapped columns exist
        errors = validate_mapping(col_map, df)
        if errors:
            result.errors.extend(errors)
            return result

    result.success = True

    logger.info(
        "File '%s' processed: %d rows, %d columns, %d fields auto-mapped, %d unmapped.",
        filename, result.row_count, result.col_count,
        len(col_map), len(unmapped)
    )
    return result


def get_column_options(df: pd.DataFrame) -> List[str]:
    """
    Return column names from a DataFrame for use in manual mapping dropdowns.

    Args:
        df: DataFrame with columns to list.

    Returns:
        List of column names with a skip option prepended.
    """
    return ["-- Skip --"] + list(df.columns)
