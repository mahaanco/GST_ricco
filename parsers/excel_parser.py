"""
parsers/excel_parser.py
-----------------------
Excel file parser with dynamic header row detection.
Handles XLSX and XLS files that may have title rows before actual headers.
"""

import logging
from typing import Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

MAX_HEADER_SCAN_ROWS = 15


def detect_header_row(df_raw: pd.DataFrame, min_cols: int = 3) -> int:
    """
    Scan raw dataframe (read without header) to find the actual header row.

    Strategy:
    - A valid header row has at least `min_cols` non-null string cells
    - Among the candidate rows, prefer the one with the most string-type cells
    - Skip rows that appear to be title/description rows

    Args:
        df_raw: DataFrame read with header=None.
        min_cols: Minimum non-null columns required to be a valid header.

    Returns:
        Zero-based row index of the detected header.
    """
    scan_limit = min(MAX_HEADER_SCAN_ROWS, len(df_raw))
    best_row = 0
    best_score = 0

    for i in range(scan_limit):
        row = df_raw.iloc[i]
        non_null = row.dropna()
        string_cells = [c for c in non_null if isinstance(c, str) and len(str(c).strip()) > 0]
        score = len(string_cells)

        if score >= min_cols and score > best_score:
            best_score = score
            best_row = i

    logger.debug("Detected header row at index: %d (score=%d)", best_row, best_score)
    return best_row


def read_excel_file(
    file_path_or_buffer,
    sheet_name: Optional[str] = None,
    auto_detect_header: bool = True,
) -> Tuple[pd.DataFrame, int]:
    """
    Read an Excel file (XLSX or XLS) with optional automatic header detection.

    Args:
        file_path_or_buffer: File path or file-like object.
        sheet_name: Sheet name or index. None uses first sheet.
        auto_detect_header: If True, scans for the header row.

    Returns:
        Tuple of (DataFrame, detected_header_row_index).
    """
    sheet = sheet_name if sheet_name is not None else 0

    if auto_detect_header:
        # Read raw (no header) to scan for header row
        try:
            df_raw = pd.read_excel(
                file_path_or_buffer,
                sheet_name=sheet,
                header=None,
                dtype=str,
                nrows=MAX_HEADER_SCAN_ROWS + 5,
            )
        except Exception as e:
            logger.error("Failed to read raw Excel for header detection: %s", e)
            raise

        header_row = detect_header_row(df_raw)

        # Re-read with detected header row
        try:
            # Seek back if it's a buffer
            if hasattr(file_path_or_buffer, "seek"):
                file_path_or_buffer.seek(0)

            df = pd.read_excel(
                file_path_or_buffer,
                sheet_name=sheet,
                header=header_row,
                dtype=str,
            )
        except Exception as e:
            logger.error("Failed to read Excel with detected header row %d: %s", header_row, e)
            raise

        # Drop completely empty rows
        df = df.dropna(how="all").reset_index(drop=True)

        # Clean column names
        df.columns = [str(c).strip() for c in df.columns]

        logger.info(
            "Excel read: %d rows, %d columns (header at row %d).",
            len(df), len(df.columns), header_row
        )
        return df, header_row

    else:
        df = pd.read_excel(file_path_or_buffer, sheet_name=sheet, dtype=str)
        df = df.dropna(how="all").reset_index(drop=True)
        df.columns = [str(c).strip() for c in df.columns]
        return df, 0


def list_sheets(file_path_or_buffer) -> list:
    """
    Return the list of sheet names in an Excel workbook.

    Args:
        file_path_or_buffer: File path or buffer.

    Returns:
        List of sheet name strings.
    """
    try:
        xl = pd.ExcelFile(file_path_or_buffer)
        return xl.sheet_names
    except Exception as e:
        logger.error("Could not list sheets: %s", e)
        return []
