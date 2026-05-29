"""
parsers/csv_parser.py
---------------------
CSV file parser with dynamic header row detection.
Handles CSV files where header may not be on the first row.
"""

import io
import logging
from typing import Tuple

import pandas as pd

logger = logging.getLogger(__name__)

MAX_HEADER_SCAN_ROWS = 15


def detect_csv_header_row(file_buffer, encoding: str = "utf-8") -> int:
    """
    Detect the header row in a CSV file.

    Strategy: read first N rows and find the row with the most comma-separated
    string tokens (likely the header).

    Args:
        file_buffer: File-like object.
        encoding: File encoding.

    Returns:
        Zero-based row index of the detected header.
    """
    try:
        # Read raw lines
        if hasattr(file_buffer, "seek"):
            file_buffer.seek(0)

        content = file_buffer.read()
        if isinstance(content, bytes):
            content = content.decode(encoding, errors="replace")

        lines = content.splitlines()
        scan_limit = min(MAX_HEADER_SCAN_ROWS, len(lines))

        best_row = 0
        best_score = 0

        for i in range(scan_limit):
            parts = lines[i].split(",")
            string_parts = [
                p.strip().strip('"')
                for p in parts
                if p.strip().strip('"') and not p.strip().strip('"').replace(".", "").isdigit()
            ]
            score = len(string_parts)
            if score > best_score:
                best_score = score
                best_row = i

        logger.debug("CSV header row detected at index: %d", best_row)
        return best_row

    except Exception as e:
        logger.warning("Could not detect CSV header row: %s. Defaulting to 0.", e)
        return 0


def read_csv_file(
    file_path_or_buffer,
    auto_detect_header: bool = True,
    encoding: str = "utf-8",
) -> Tuple[pd.DataFrame, int]:
    """
    Read a CSV file with optional automatic header detection.

    Args:
        file_path_or_buffer: File path or file-like object.
        auto_detect_header: If True, scans for the header row.
        encoding: File encoding (default utf-8).

    Returns:
        Tuple of (DataFrame, header_row_index).
    """
    if hasattr(file_path_or_buffer, "seek"):
        file_path_or_buffer.seek(0)

    if auto_detect_header:
        header_row = detect_csv_header_row(file_path_or_buffer, encoding)

        if hasattr(file_path_or_buffer, "seek"):
            file_path_or_buffer.seek(0)

        try:
            df = pd.read_csv(
                file_path_or_buffer,
                skiprows=header_row,
                dtype=str,
                encoding=encoding,
                on_bad_lines="skip",
            )
        except UnicodeDecodeError:
            if hasattr(file_path_or_buffer, "seek"):
                file_path_or_buffer.seek(0)
            df = pd.read_csv(
                file_path_or_buffer,
                skiprows=header_row,
                dtype=str,
                encoding="latin-1",
                on_bad_lines="skip",
            )
    else:
        try:
            df = pd.read_csv(file_path_or_buffer, dtype=str, encoding=encoding)
        except UnicodeDecodeError:
            if hasattr(file_path_or_buffer, "seek"):
                file_path_or_buffer.seek(0)
            df = pd.read_csv(file_path_or_buffer, dtype=str, encoding="latin-1")
        header_row = 0

    # Clean up
    df = df.dropna(how="all").reset_index(drop=True)
    df.columns = [str(c).strip() for c in df.columns]

    logger.info(
        "CSV read: %d rows, %d columns (header at row %d).",
        len(df), len(df.columns), header_row
    )
    return df, header_row
