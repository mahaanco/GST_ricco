"""
parsers/file_reader.py
----------------------
Unified file reader that dispatches to the appropriate parser
based on the file extension (XLSX, XLS, CSV).
"""

import logging
from typing import Tuple

import pandas as pd

from parsers.csv_parser import read_csv_file
from parsers.excel_parser import read_excel_file, list_sheets

logger = logging.getLogger(__name__)


def read_uploaded_file(
    file_buffer,
    filename: str,
    sheet_name: str = None,
) -> Tuple[pd.DataFrame, int, str]:
    """
    Read an uploaded file into a DataFrame.

    Supported formats: .xlsx, .xls, .csv

    Args:
        file_buffer: File-like object (from Streamlit st.file_uploader).
        filename: Original filename (used for extension detection).
        sheet_name: Optional sheet name for Excel files.

    Returns:
        Tuple of:
          - df: Loaded DataFrame
          - header_row: Detected header row index
          - file_type: "excel" or "csv"

    Raises:
        ValueError: If file format is not supported or file is empty.
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext in ("xlsx", "xls"):
        try:
            df, header_row = read_excel_file(
                file_buffer,
                sheet_name=sheet_name,
                auto_detect_header=True,
            )
            if df.empty:
                raise ValueError("The uploaded Excel file is empty or has no data.")
            return df, header_row, "excel"
        except Exception as e:
            logger.error("Failed to read Excel file '%s': %s", filename, e)
            raise ValueError(f"Could not read Excel file: {e}") from e

    elif ext == "csv":
        try:
            df, header_row = read_csv_file(file_buffer, auto_detect_header=True)
            if df.empty:
                raise ValueError("The uploaded CSV file is empty or has no data.")
            return df, header_row, "csv"
        except Exception as e:
            logger.error("Failed to read CSV file '%s': %s", filename, e)
            raise ValueError(f"Could not read CSV file: {e}") from e

    else:
        raise ValueError(
            f"Unsupported file format: '{ext}'. Please upload XLSX, XLS, or CSV files."
        )


def get_sheet_names(file_buffer, filename: str) -> list:
    """
    Get sheet names from an Excel file, or empty list for CSV.

    Args:
        file_buffer: File-like object.
        filename: Original filename.

    Returns:
        List of sheet name strings.
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in ("xlsx", "xls"):
        return list_sheets(file_buffer)
    return []
