"""
app.py
------
GST Reconciliation System - Main Streamlit Application
Production-ready reconciliation for CA firms and finance teams.

Supports:
  - Purchase Register vs GSTR-2B
  - Sales Register vs GSTR-1
"""

import io
import logging
from datetime import datetime
from typing import Dict, Optional

import pandas as pd
import streamlit as st

from core.mapper import get_field_display_names, get_optional_fields, get_required_fields
from core.reconciler import ReconciliationResult
from reports.excel_report import generate_excel_report
from services.reconciliation_service import (
    build_config,
    execute_reconciliation,
    get_summary_stats,
)
from services.upload_service import UploadResult, get_column_options, process_uploaded_file

# ─────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Page Config
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="GST Reconciliation System",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────
# Custom CSS
# ─────────────────────────────────────────────
st.markdown("""
<style>
    /* Metric cards */
    div[data-testid="metric-container"] {
        background: white;
        border: 1px solid #E0E8F0;
        border-radius: 10px;
        padding: 16px;
        box-shadow: 0 2px 8px rgba(26,60,94,0.07);
    }
    div[data-testid="metric-container"] label {
        color: #5A7A9A;
        font-size: 0.82rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    div[data-testid="metric-container"] div[data-testid="stMetricValue"] {
        color: #1A3C5E;
        font-size: 1.8rem;
        font-weight: 700;
    }
    /* Header */
    .app-header {
        background: linear-gradient(135deg, #1A3C5E 0%, #2D6A9F 100%);
        padding: 28px 36px;
        border-radius: 12px;
        margin-bottom: 24px;
        color: white;
    }
    .app-header h1 { color: white; margin: 0; font-size: 2rem; }
    .app-header p { color: #BDD5EA; margin: 6px 0 0 0; font-size: 1rem; }
    /* Section cards */
    .section-card {
        background: white;
        border: 1px solid #E0E8F0;
        border-radius: 10px;
        padding: 20px;
        margin-bottom: 16px;
        box-shadow: 0 1px 4px rgba(26,60,94,0.06);
    }
    /* Status badges */
    .badge-success { background: #E8F5E9; color: #2E7D32; padding: 3px 10px; border-radius: 12px; font-size: 0.82rem; font-weight: 600; }
    .badge-warning { background: #FFF3E0; color: #E65100; padding: 3px 10px; border-radius: 12px; font-size: 0.82rem; font-weight: 600; }
    .badge-error   { background: #FFEBEE; color: #C62828; padding: 3px 10px; border-radius: 12px; font-size: 0.82rem; font-weight: 600; }
    .badge-info    { background: #E3F2FD; color: #1565C0; padding: 3px 10px; border-radius: 12px; font-size: 0.82rem; font-weight: 600; }
    /* Tabs styling */
    .stTabs [data-baseweb="tab-list"] { gap: 4px; }
    .stTabs [data-baseweb="tab"] { padding: 8px 16px; border-radius: 6px 6px 0 0; }
    /* Upload area */
    .upload-label { font-weight: 600; color: #1A3C5E; margin-bottom: 6px; font-size: 0.95rem; }
    /* Progress ring simulation */
    .match-pct-big {
        font-size: 3rem;
        font-weight: 800;
        color: #1A3C5E;
        text-align: center;
    }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# Session State Initialisation
# ─────────────────────────────────────────────
def init_session_state():
    defaults = {
        "source_upload": None,
        "target_upload": None,
        "source_result": None,
        "target_result": None,
        "source_manual_map": {},
        "target_manual_map": {},
        "reconciliation_result": None,
        "excel_report_bytes": None,
        "reconciliation_ran": False,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


# ─────────────────────────────────────────────
# Header
# ─────────────────────────────────────────────
def render_header():
    st.markdown("""
    <div class="app-header">
        <h1>📊 GST Reconciliation System</h1>
        <p>Automated reconciliation for Purchase Register vs GSTR-2B &amp; Sales Register vs GSTR-1</p>
    </div>
    """, unsafe_allow_html=True)


# ─────────────────────────────────────────────
# Sidebar
# ─────────────────────────────────────────────
def render_sidebar() -> dict:
    """Render sidebar controls and return configuration dict."""
    with st.sidebar:
        st.markdown("### ⚙️ Configuration")
        st.divider()

        recon_type = st.selectbox(
            "Reconciliation Type",
            options=["purchase", "sales"],
            format_func=lambda x: "Purchase Register vs GSTR-2B" if x == "purchase" else "Sales Register vs GSTR-1",
            help="Select the type of GST reconciliation to perform.",
        )

        st.divider()
        st.markdown("**Tolerance Settings**")

        amount_tolerance = st.number_input(
            "Amount Tolerance (₹)",
            min_value=0.0,
            max_value=1000.0,
            value=1.0,
            step=0.5,
            help="Maximum acceptable GST amount difference (default: ₹1).",
        )

        date_tolerance = st.number_input(
            "Date Tolerance (days)",
            min_value=0,
            max_value=30,
            value=3,
            help="Maximum acceptable invoice date difference in days (default: 3).",
        )

        st.divider()
        st.markdown("**Fuzzy Matching**")

        run_fuzzy = st.checkbox("Enable Fuzzy Matching", value=True,
                                help="Detect invoice numbers that differ in format (e.g. INV001 vs INV-001).")

        fuzzy_threshold = st.slider(
            "Fuzzy Score Threshold (%)",
            min_value=70,
            max_value=100,
            value=95,
            disabled=not run_fuzzy,
            help="Minimum similarity score for fuzzy matches.",
        )

        st.divider()
        st.markdown("**Data Options**")

        remove_duplicates = st.checkbox(
            "Remove duplicates before matching",
            value=False,
            help="If enabled, keeps only the first occurrence of duplicate invoices.",
        )

        st.divider()
        st.markdown("""
        <div style="font-size:0.8rem; color:#5A7A9A; line-height:1.6;">
        <b>Supported formats:</b> XLSX, XLS, CSV<br>
        <b>Max file size:</b> 50 MB<br>
        <b>Capacity:</b> 10,000+ invoices
        </div>
        """, unsafe_allow_html=True)

    return {
        "recon_type": recon_type,
        "amount_tolerance": amount_tolerance,
        "date_tolerance": date_tolerance,
        "run_fuzzy": run_fuzzy,
        "fuzzy_threshold": fuzzy_threshold,
        "remove_duplicates": remove_duplicates,
    }


# ─────────────────────────────────────────────
# Manual Mapping UI
# ─────────────────────────────────────────────
def render_manual_mapping(
    upload_result: UploadResult,
    label: str,
    key_prefix: str,
) -> Dict[str, str]:
    """
    Render manual column mapping dropdowns for a file.

    Args:
        upload_result: UploadResult with df and auto col_map.
        label: Display label (e.g. "Purchase Register").
        key_prefix: Unique prefix for Streamlit widget keys.

    Returns:
        Dict of manual overrides: logical_name -> actual_column.
    """
    field_display = get_field_display_names()
    required_fields = get_required_fields()
    optional_fields = get_optional_fields()
    col_options = get_column_options(upload_result.df)

    manual_map = {}

    st.markdown(f"#### 🗂️ Column Mapping — {label}")
    st.caption("Auto-detected where possible. Please verify and correct missing fields.")

    req_col, opt_col = st.columns(2)

    with req_col:
        st.markdown("**Required Fields** *(must be mapped)*")
        for field in required_fields:
            display_name = field_display.get(field, field)
            current = upload_result.col_map.get(field, "-- Skip --")
            default_idx = col_options.index(current) if current in col_options else 0
            selected = st.selectbox(
                display_name,
                options=col_options,
                index=default_idx,
                key=f"{key_prefix}_{field}",
            )
            manual_map[field] = selected

    with opt_col:
        st.markdown("**Optional Fields**")
        for field in optional_fields:
            display_name = field_display.get(field, field)
            current = upload_result.col_map.get(field, "-- Skip --")
            default_idx = col_options.index(current) if current in col_options else 0
            selected = st.selectbox(
                display_name,
                options=col_options,
                index=default_idx,
                key=f"{key_prefix}_{field}",
            )
            manual_map[field] = selected

    return manual_map


# ─────────────────────────────────────────────
# File Upload Section
# ─────────────────────────────────────────────
def render_file_upload(recon_type: str):
    """Render the file upload area for source and target files."""
    type_config = {
        "purchase": {
            "source_label": "Purchase Register",
            "target_label": "GSTR-2B",
            "source_icon": "📋",
            "target_icon": "🏛️",
        },
        "sales": {
            "source_label": "Sales Register",
            "target_label": "GSTR-1",
            "source_icon": "🧾",
            "target_icon": "🏛️",
        },
    }
    cfg = type_config[recon_type]

    col1, col2 = st.columns(2)

    with col1:
        st.markdown(
            f'<div class="upload-label">{cfg["source_icon"]} {cfg["source_label"]}</div>',
            unsafe_allow_html=True
        )
        source_file = st.file_uploader(
            f"Upload {cfg['source_label']}",
            type=["xlsx", "xls", "csv"],
            key="source_uploader",
            label_visibility="collapsed",
        )

        if source_file is not None:
            with st.spinner(f"Reading {cfg['source_label']}..."):
                result = process_uploaded_file(source_file, source_file.name)
                st.session_state["source_result"] = result
                st.session_state["source_upload"] = source_file

            if result.success:
                st.success(
                    f"✅ {result.row_count:,} rows · {result.col_count} columns · "
                    f"Header at row {result.header_row + 1}"
                )
                if result.warnings:
                    for w in result.warnings:
                        st.warning(w)
            else:
                for err in result.errors:
                    st.error(f"❌ {err}")

    with col2:
        st.markdown(
            f'<div class="upload-label">{cfg["target_icon"]} {cfg["target_label"]}</div>',
            unsafe_allow_html=True
        )
        target_file = st.file_uploader(
            f"Upload {cfg['target_label']}",
            type=["xlsx", "xls", "csv"],
            key="target_uploader",
            label_visibility="collapsed",
        )

        if target_file is not None:
            with st.spinner(f"Reading {cfg['target_label']}..."):
                result = process_uploaded_file(target_file, target_file.name)
                st.session_state["target_result"] = result
                st.session_state["target_upload"] = target_file

            if result.success:
                st.success(
                    f"✅ {result.row_count:,} rows · {result.col_count} columns · "
                    f"Header at row {result.header_row + 1}"
                )
                if result.warnings:
                    for w in result.warnings:
                        st.warning(w)
            else:
                for err in result.errors:
                    st.error(f"❌ {err}")


# ─────────────────────────────────────────────
# Column Mapping Section
# ─────────────────────────────────────────────
def render_column_mapping(recon_type: str):
    """Render column mapping UI for both files."""
    source_result: Optional[UploadResult] = st.session_state.get("source_result")
    target_result: Optional[UploadResult] = st.session_state.get("target_result")

    if source_result is None or target_result is None:
        return

    if not source_result.success or not target_result.success:
        return

    type_config = {
        "purchase": ("Purchase Register", "GSTR-2B"),
        "sales": ("Sales Register", "GSTR-1"),
    }
    source_label, target_label = type_config[recon_type]

    needs_mapping = (
        source_result.needs_manual_mapping
        or target_result.needs_manual_mapping
    )

    with st.expander(
        "🗂️ Column Mapping" + (" ⚠️ Manual mapping required" if needs_mapping else " ✅ Auto-detected"),
        expanded=needs_mapping,
    ):
        tab_src, tab_tgt = st.tabs([f"📋 {source_label}", f"🏛️ {target_label}"])

        with tab_src:
            src_map = render_manual_mapping(source_result, source_label, "src")
            st.session_state["source_manual_map"] = src_map

        with tab_tgt:
            tgt_map = render_manual_mapping(target_result, target_label, "tgt")
            st.session_state["target_manual_map"] = tgt_map


# ─────────────────────────────────────────────
# Dashboard Metrics
# ─────────────────────────────────────────────
def render_dashboard(stats: dict, recon_type: str):
    """Render the summary dashboard metrics."""
    source_label = "Purchase Register" if recon_type == "purchase" else "Sales Register"
    target_label = "GSTR-2B" if recon_type == "purchase" else "GSTR-1"

    st.markdown("### 📊 Reconciliation Dashboard")

    # Top row
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric(f"📋 {source_label}", f"{stats['total_source']:,}")
    c2.metric(f"🏛️ {target_label}", f"{stats['total_target']:,}")
    c3.metric("✅ Matched", f"{stats['matched']:,}")
    c4.metric("🎯 Match %", f"{stats['match_pct']:.1f}%")
    c5.metric("🔍 Fuzzy Matches", f"{stats['fuzzy_matches']:,}")

    st.markdown("")

    # Bottom row
    c6, c7, c8, c9, c10 = st.columns(5)
    c6.metric(f"❌ Missing in {target_label[:6]}", f"{stats['missing_in_target']:,}")
    c7.metric(f"❓ Missing in {source_label[:6]}", f"{stats['missing_in_source']:,}")
    c8.metric("💰 Amount Mismatch", f"{stats['amount_mismatch']:,}")
    c9.metric("📅 Date Mismatch", f"{stats['date_mismatch']:,}")
    c10.metric("⚠️ Duplicates", f"{stats['source_duplicates'] + stats['target_duplicates']:,}")


# ─────────────────────────────────────────────
# Result Tabs
# ─────────────────────────────────────────────
def render_result_tabs(result: ReconciliationResult, config_ui: dict):
    """Render all reconciliation result tabs."""
    source_label = result.config.source_label if result.config else "Source"
    target_label = result.config.target_label if result.config else "Target"

    tabs = st.tabs([
        f"✅ Matched ({result.matched_count:,})",
        f"❌ Missing in {target_label[:8]} ({result.missing_in_target_count:,})",
        f"❓ Missing in {source_label[:8]} ({result.missing_in_source_count:,})",
        f"💰 Amount Mismatch ({result.amount_mismatch_count:,})",
        f"📅 Date Mismatch ({result.date_mismatch_count:,})",
        f"🔍 Fuzzy ({result.fuzzy_match_count:,})",
        f"🔁 Src Duplicates ({result.source_duplicate_count:,})",
        f"🔁 Tgt Duplicates ({result.target_duplicate_count:,})",
        "🚫 Invalid GSTIN",
        "📦 Vendor Summary",
    ])

    def _show_df(df: pd.DataFrame, empty_msg: str = "No records in this category."):
        if df is None or df.empty:
            st.info(empty_msg)
            return
        # Remove internal columns from display
        display_cols = [c for c in df.columns if not c.startswith("_match_key") and not c.startswith("_source_label")]
        st.dataframe(
            df[display_cols].head(5000),
            use_container_width=True,
            hide_index=True,
        )
        st.caption(f"Showing up to 5,000 of {len(df):,} records.")

    with tabs[0]:
        _show_df(result.matched, "🎉 No records to show — all matched!")

    with tabs[1]:
        _show_df(result.missing_in_target, f"✅ All source records found in {target_label}.")

    with tabs[2]:
        _show_df(result.missing_in_source, f"✅ All target records found in {source_label}.")

    with tabs[3]:
        _show_df(result.amount_mismatch, "✅ No amount mismatches found.")

    with tabs[4]:
        _show_df(result.date_mismatch, "✅ No date mismatches found.")

    with tabs[5]:
        if not config_ui.get("run_fuzzy"):
            st.info("Fuzzy matching was disabled for this run.")
        else:
            _show_df(result.fuzzy_matches, "No fuzzy matches found.")

    with tabs[6]:
        _show_df(result.source_duplicates, f"✅ No duplicates in {source_label}.")

    with tabs[7]:
        _show_df(result.target_duplicates, f"✅ No duplicates in {target_label}.")

    with tabs[8]:
        invalid_combined = pd.concat(
            [result.invalid_gstin_source, result.invalid_gstin_target],
            ignore_index=True
        ) if not result.invalid_gstin_source.empty or not result.invalid_gstin_target.empty else pd.DataFrame()
        _show_df(invalid_combined, "✅ No invalid GSTINs found.")

    with tabs[9]:
        _show_df(result.vendor_summary, "No vendor summary data.")


# ─────────────────────────────────────────────
# Main App
# ─────────────────────────────────────────────
def main():
    init_session_state()
    render_header()

    # Sidebar config
    config_ui = render_sidebar()
    recon_type = config_ui["recon_type"]

    # ── Step 1: File Upload ──
    st.markdown("### 📁 Step 1: Upload Files")
    with st.container():
        render_file_upload(recon_type)

    # ── Step 2: Column Mapping ──
    source_result: Optional[UploadResult] = st.session_state.get("source_result")
    target_result: Optional[UploadResult] = st.session_state.get("target_result")

    if source_result and target_result and source_result.success and target_result.success:
        st.markdown("### 🗂️ Step 2: Review Column Mapping")
        render_column_mapping(recon_type)

        # ── Step 3: Run ──
        st.markdown("### ▶️ Step 3: Run Reconciliation")

        run_col, info_col = st.columns([1, 3])
        with run_col:
            run_clicked = st.button(
                "🚀 Run Reconciliation",
                type="primary",
                use_container_width=True,
            )
        with info_col:
            st.markdown(
                f"<div style='padding-top:8px; color:#5A7A9A; font-size:0.9rem;'>"
                f"Will reconcile <b>{source_result.row_count:,}</b> source records "
                f"against <b>{target_result.row_count:,}</b> target records.</div>",
                unsafe_allow_html=True,
            )

        if run_clicked:
            config = build_config(
                reconciliation_type=recon_type,
                amount_tolerance=config_ui["amount_tolerance"],
                date_tolerance_days=int(config_ui["date_tolerance"]),
                fuzzy_threshold=int(config_ui["fuzzy_threshold"]),
                run_fuzzy=config_ui["run_fuzzy"],
                remove_duplicates=config_ui["remove_duplicates"],
            )

            with st.spinner("⚙️ Running reconciliation... This may take a moment for large files."):
                try:
                    result = execute_reconciliation(
                        source_df=source_result.df,
                        target_df=target_result.df,
                        source_col_map=source_result.col_map,
                        target_col_map=target_result.col_map,
                        source_manual_overrides=st.session_state.get("source_manual_map", {}),
                        target_manual_overrides=st.session_state.get("target_manual_map", {}),
                        config=config,
                    )
                    st.session_state["reconciliation_result"] = result
                    st.session_state["reconciliation_ran"] = True

                    # Generate Excel report
                    excel_bytes = generate_excel_report(result)
                    st.session_state["excel_report_bytes"] = excel_bytes

                    st.success("✅ Reconciliation completed successfully!")
                    logger.info("Reconciliation completed successfully.")

                except Exception as e:
                    st.error(f"❌ Reconciliation failed: {e}")
                    logger.exception("Reconciliation failed.")
                    st.stop()

        # ── Results ──
        if st.session_state.get("reconciliation_ran") and st.session_state.get("reconciliation_result"):
            result: ReconciliationResult = st.session_state["reconciliation_result"]
            stats = get_summary_stats(result)

            st.divider()

            # Dashboard
            render_dashboard(stats, recon_type)

            st.divider()

            # Download button
            dl_col, _ = st.columns([1, 4])
            with dl_col:
                excel_bytes = st.session_state.get("excel_report_bytes")
                if excel_bytes:
                    filename = (
                        f"GST_Recon_{recon_type.upper()}_"
                        f"{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
                    )
                    st.download_button(
                        label="📥 Download Excel Report",
                        data=excel_bytes,
                        file_name=filename,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        type="secondary",
                        use_container_width=True,
                    )

            # Result tabs
            st.markdown("### 📋 Detailed Results")
            render_result_tabs(result, config_ui)

    else:
        # Instruction cards when files not uploaded
        st.markdown("")
        info1, info2, info3 = st.columns(3)
        with info1:
            st.info("**Step 1:** Upload your Purchase Register or Sales Register (XLSX/XLS/CSV)")
        with info2:
            st.info("**Step 2:** Upload the corresponding GSTR-2B or GSTR-1 from GST portal")
        with info3:
            st.info("**Step 3:** Click Run Reconciliation and download the Excel report")

        st.markdown("---")
        st.markdown("""
        #### 💡 Tips
        - The system **automatically detects** header rows — no need to clean your files first
        - Column names are matched **intelligently** (e.g., "Supplier GSTIN", "GSTIN/UIN", "Vendor GST No" all map to GSTIN)
        - Invoice numbers are **normalized** before matching (INV-001 = INV001 = INV 001)
        - **Fuzzy matching** catches near-misses like A/100 vs A100
        - Download the full **Excel report** with 11 categorized sheets
        """)


if __name__ == "__main__":
    main()
