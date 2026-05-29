"""
reports/excel_report.py
-----------------------
Generates a multi-sheet Excel workbook from reconciliation results.
Uses xlsxwriter for formatting.
"""

import io
import logging
from typing import Optional

import pandas as pd
import xlsxwriter

from core.reconciler import ReconciliationResult
from reports.summary import build_summary_df

logger = logging.getLogger(__name__)

# Color palette
COLORS = {
    "header_bg": "#1A3C5E",
    "header_font": "#FFFFFF",
    "matched_bg": "#E8F5E9",
    "missing_bg": "#FFF3E0",
    "mismatch_bg": "#FFEBEE",
    "fuzzy_bg": "#E3F2FD",
    "duplicate_bg": "#F3E5F5",
    "invalid_bg": "#FCE4EC",
    "summary_label": "#1A3C5E",
    "summary_value": "#212121",
    "alt_row": "#F5F5F5",
    "white": "#FFFFFF",
}


def _col_letters(n: int) -> str:
    """Convert a zero-based column index to Excel column letter(s)."""
    result = ""
    while n >= 0:
        result = chr(n % 26 + 65) + result
        n = n // 26 - 1
    return result


def _write_sheet(
    workbook: xlsxwriter.Workbook,
    sheet_name: str,
    df: pd.DataFrame,
    header_color: str = COLORS["header_bg"],
    row_color: str = COLORS["white"],
    alt_color: str = COLORS["alt_row"],
    freeze_header: bool = True,
) -> None:
    """
    Write a DataFrame to an Excel worksheet with formatting.

    Args:
        workbook: xlsxwriter Workbook object.
        sheet_name: Name of the worksheet.
        df: DataFrame to write.
        header_color: Background color for header row.
        row_color: Background color for data rows.
        alt_color: Alternating row background color.
        freeze_header: If True, freeze the header row.
    """
    if df is None or df.empty:
        ws = workbook.add_worksheet(sheet_name[:31])
        ws.write(0, 0, "No data for this category.")
        return

    ws = workbook.add_worksheet(sheet_name[:31])

    # Formats
    header_fmt = workbook.add_format({
        "bold": True,
        "bg_color": header_color,
        "font_color": COLORS["header_font"],
        "border": 1,
        "border_color": "#CCCCCC",
        "text_wrap": True,
        "valign": "vcenter",
    })
    data_fmt = workbook.add_format({
        "border": 1,
        "border_color": "#E0E0E0",
        "valign": "vcenter",
    })
    alt_fmt = workbook.add_format({
        "bg_color": alt_color,
        "border": 1,
        "border_color": "#E0E0E0",
        "valign": "vcenter",
    })
    date_fmt = workbook.add_format({
        "num_format": "dd-mmm-yyyy",
        "border": 1,
        "border_color": "#E0E0E0",
    })
    num_fmt = workbook.add_format({
        "num_format": "#,##0.00",
        "border": 1,
        "border_color": "#E0E0E0",
    })

    # Clean columns for display (remove internal `_clean_` prefix columns from display)
    display_df = df.copy()
    # Keep only non-internal columns OR selected internal ones
    internal_prefixes = ("_clean_", "_match_key", "_gstin_", "_duplicate_", "_source_label", "_tolerance")
    visible_cols = [
        c for c in display_df.columns
        if not any(c.startswith(p) for p in internal_prefixes)
    ]
    # Add cleaned columns with readable names if original missing
    rename_map = {
        "_clean_gstin": "GSTIN (Cleaned)",
        "_clean_invoice_number": "Invoice No (Cleaned)",
        "_clean_invoice_date": "Invoice Date",
        "_clean_total_gst": "Total GST Amount",
        "_clean_taxable_value": "Taxable Value",
        "_clean_total_gst_source": "Source GST Amount",
        "_clean_total_gst_target": "Target GST Amount",
        "_amount_diff": "Amount Difference (₹)",
        "_clean_invoice_date_source": "Source Invoice Date",
        "_clean_invoice_date_target": "Target Invoice Date",
        "_date_diff_days": "Date Difference (Days)",
    }
    # Add useful internal columns
    useful_internals = list(rename_map.keys())
    for col in useful_internals:
        if col in display_df.columns and col not in visible_cols:
            visible_cols.append(col)

    display_df = display_df[visible_cols].rename(columns=rename_map)

    # Write header
    ws.set_row(0, 20)
    for col_idx, col_name in enumerate(display_df.columns):
        ws.write(0, col_idx, str(col_name), header_fmt)

    # Write data
    for row_idx, (_, row) in enumerate(display_df.iterrows()):
        fmt = alt_fmt if row_idx % 2 == 1 else data_fmt
        for col_idx, value in enumerate(row):
            if isinstance(value, pd.Timestamp):
                ws.write_datetime(row_idx + 1, col_idx, value.to_pydatetime(), date_fmt)
            elif isinstance(value, float) and not pd.isna(value):
                col_name = display_df.columns[col_idx]
                if any(k in col_name.lower() for k in ("amount", "value", "gst", "diff")):
                    ws.write_number(row_idx + 1, col_idx, value, num_fmt)
                else:
                    ws.write(row_idx + 1, col_idx, value, fmt)
            elif pd.isna(value) if not isinstance(value, str) else False:
                ws.write(row_idx + 1, col_idx, "", fmt)
            else:
                ws.write(row_idx + 1, col_idx, str(value) if not isinstance(value, (int, float)) else value, fmt)

    # Auto-fit columns (approximate)
    for col_idx, col_name in enumerate(display_df.columns):
        max_len = max(
            len(str(col_name)),
            display_df.iloc[:, col_idx].astype(str).str.len().max() if len(display_df) > 0 else 0,
        )
        ws.set_column(col_idx, col_idx, min(max_len + 2, 40))

    if freeze_header:
        ws.freeze_panes(1, 0)


def _write_summary_sheet(workbook: xlsxwriter.Workbook, summary_df: pd.DataFrame) -> None:
    """Write the summary sheet with special formatting."""
    ws = workbook.add_worksheet("Summary")

    label_fmt = workbook.add_format({
        "bold": True,
        "font_color": COLORS["summary_label"],
        "font_size": 11,
    })
    value_fmt = workbook.add_format({
        "font_color": COLORS["summary_value"],
        "font_size": 11,
    })
    section_fmt = workbook.add_format({
        "bold": True,
        "font_color": COLORS["header_font"],
        "bg_color": COLORS["header_bg"],
        "font_size": 11,
    })
    title_fmt = workbook.add_format({
        "bold": True,
        "font_size": 16,
        "font_color": COLORS["header_bg"],
    })

    ws.write(0, 0, "GST Reconciliation Report", title_fmt)
    ws.set_row(0, 30)
    ws.set_column(0, 0, 45)
    ws.set_column(1, 1, 30)

    for row_idx, (_, row) in enumerate(summary_df.iterrows()):
        metric = str(row["Metric"])
        value = str(row["Value"])
        actual_row = row_idx + 2

        if metric.startswith("==="):
            ws.merge_range(actual_row, 0, actual_row, 1, metric.replace("=", "").strip(), section_fmt)
        elif metric == "":
            ws.write(actual_row, 0, "")
        else:
            ws.write(actual_row, 0, metric, label_fmt)
            ws.write(actual_row, 1, value, value_fmt)

    ws.freeze_panes(1, 0)


def generate_excel_report(result: ReconciliationResult) -> bytes:
    """
    Generate a complete Excel reconciliation report.

    Sheets:
    1. Summary
    2. Matched
    3. Missing In Target
    4. Missing In Source
    5. Amount Mismatch
    6. Date Mismatch
    7. Fuzzy Matches
    8. Source Duplicates
    9. Target Duplicates
    10. Invalid GSTIN
    11. Vendor Summary

    Args:
        result: Completed ReconciliationResult.

    Returns:
        Excel file as bytes (for Streamlit download button).
    """
    output = io.BytesIO()

    workbook = xlsxwriter.Workbook(output, {"in_memory": True, "remove_timezone": True})

    config = result.config
    source_label = config.source_label if config else "Source"
    target_label = config.target_label if config else "Target"

    # 1. Summary
    summary_df = build_summary_df(result)
    _write_summary_sheet(workbook, summary_df)

    # 2. Matched
    _write_sheet(workbook, "Matched", result.matched, row_color=COLORS["matched_bg"])

    # 3. Missing In Target
    _write_sheet(workbook, f"Missing In {target_label[:15]}", result.missing_in_target,
                 row_color=COLORS["missing_bg"])

    # 4. Missing In Source
    _write_sheet(workbook, f"Missing In {source_label[:15]}", result.missing_in_source,
                 row_color=COLORS["missing_bg"])

    # 5. Amount Mismatch
    _write_sheet(workbook, "Amount Mismatch", result.amount_mismatch,
                 row_color=COLORS["mismatch_bg"])

    # 6. Date Mismatch
    _write_sheet(workbook, "Date Mismatch", result.date_mismatch,
                 row_color=COLORS["mismatch_bg"])

    # 7. Fuzzy Matches
    _write_sheet(workbook, "Fuzzy Matches", result.fuzzy_matches,
                 row_color=COLORS["fuzzy_bg"])

    # 8. Source Duplicates
    _write_sheet(workbook, f"{source_label[:12]} Duplicates", result.source_duplicates,
                 row_color=COLORS["duplicate_bg"])

    # 9. Target Duplicates
    _write_sheet(workbook, f"{target_label[:12]} Duplicates", result.target_duplicates,
                 row_color=COLORS["duplicate_bg"])

    # 10. Invalid GSTIN
    invalid_combined = pd.concat(
        [result.invalid_gstin_source, result.invalid_gstin_target],
        ignore_index=True
    ) if not result.invalid_gstin_source.empty or not result.invalid_gstin_target.empty else pd.DataFrame()
    _write_sheet(workbook, "Invalid GSTIN", invalid_combined,
                 row_color=COLORS["invalid_bg"])

    # 11. Vendor Summary
    _write_sheet(workbook, "Vendor Summary", result.vendor_summary,
                 row_color=COLORS["alt_row"])

    workbook.close()
    output.seek(0)

    logger.info("Excel report generated successfully.")
    return output.getvalue()
