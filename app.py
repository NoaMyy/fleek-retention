"""
Fleek Retention — Streamlit web interface.

Sections
--------
1. UPLOAD          — drop an .xlsx, run the full pipeline, show a log summary.
2. PORTFOLIO VIEW  — segment counts (Total / T1 / T2 / T3 / At Risk) + Excel download.
3. MESSAGE DRAFTS  — per-account table with A/B variants; push to SendGrid per row or all T1.
4. SENDGRID STATUS — push results summary.

Run with:
    streamlit run app.py
"""
import io
import os
import tempfile
from datetime import datetime

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# ── page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Fleek Retention",
    page_icon="🧥",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── helpers ───────────────────────────────────────────────────────────────────

SEGMENT_COLOURS = {
    "BROKER_RELIANT":      "#FFF3CD",
    "HEALTHY_AM":          "#D1ECF1",
    "SELF_SERVE_HEADROOM": "#D4EDDA",
    "SELF_SERVE_MATURE":   "#E2E3E5",
}

CONTACTS_PATH = "data/contacts.csv"


def _run_pipeline(uploaded_bytes: bytes, filename: str) -> tuple:
    """
    Run clean → segment → prioritise → assign_plays → draft_messages.
    Returns (df, log_lines).
    Writes the file to a temp path so the pipeline functions get a real path.
    """
    from pipeline.clean import load_and_clean
    from pipeline.segment import segment
    from pipeline.prioritise import prioritise
    from pipeline.plays import assign_plays
    from agents.drafter import draft_messages

    log = []

    # Save upload to temp file
    suffix = ".xlsx" if filename.endswith(".xlsx") else ".xlsx"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(uploaded_bytes)
        tmp_path = tmp.name

    try:
        # 1. Clean
        df = load_and_clean(tmp_path)
        log.append(f"✅ Loaded **{len(df)}** accounts from `{filename}`")

        # 2. Segment
        df = segment(df)
        counts = df["segment"].value_counts().to_dict()
        at_risk_n = int(df["at_risk"].sum())
        seg_summary = "  ·  ".join(f"{s}: {n}" for s, n in sorted(counts.items()))
        log.append(f"✅ Segmented — {seg_summary}  ·  AT_RISK: {at_risk_n}")

        # 3. Prioritise
        df = prioritise(df)
        log.append("✅ Prioritised within each segment")

        # 4. Plays
        df = assign_plays(df)
        play_counts = df["play"].value_counts().to_dict()
        log.append("✅ Plays assigned — " + "  ·  ".join(f"{p}: {n}" for p, n in play_counts.items()))

        # 5. Merge contacts
        if os.path.exists(CONTACTS_PATH):
            contacts = pd.read_csv(CONTACTS_PATH)
            df = df.merge(contacts, on="account_id", how="left")
            log.append(f"✅ Merged contacts ({contacts['account_id'].nunique()} records)")
        else:
            log.append("⚠️ `data/contacts.csv` not found — email column will be empty")

        # 6. Draft messages
        df = draft_messages(df)
        drafted = int((df.get("msg_variant_a", pd.Series([])) != "").sum())
        log.append(f"✅ Drafted messages for **{drafted}** accounts")

        # Add touch tier label
        if "touch_number" not in df.columns:
            df["touch_number"] = 1
        df["tier"] = "T" + df["touch_number"].astype(int).astype(str)

    finally:
        os.unlink(tmp_path)

    return df, log


def _segment_counts_table(df: pd.DataFrame) -> pd.DataFrame:
    """Build the Segment / Total / T1 / T2 / T3 / At Risk summary table."""
    rows = []
    for seg in ["BROKER_RELIANT", "HEALTHY_AM", "SELF_SERVE_HEADROOM", "SELF_SERVE_MATURE"]:
        sub = df[df["segment"] == seg]
        rows.append({
            "Segment":  seg,
            "Total":    len(sub),
            "T1":       int((sub["touch_number"] == 1).sum()),
            "T2":       int((sub["touch_number"] == 2).sum()),
            "T3":       int((sub["touch_number"] == 3).sum()),
            "At Risk":  int(sub["at_risk"].sum()) if "at_risk" in sub.columns else 0,
        })
    rows.append({
        "Segment": "TOTAL",
        "Total":   len(df),
        "T1":      int((df["touch_number"] == 1).sum()),
        "T2":      int((df["touch_number"] == 2).sum()),
        "T3":      int((df["touch_number"] == 3).sum()),
        "At Risk": int(df["at_risk"].sum()) if "at_risk" in df.columns else 0,
    })
    return pd.DataFrame(rows)


def _make_excel_bytes(df: pd.DataFrame) -> bytes:
    """Generate the priority Excel workbook and return as bytes for download."""
    from pipeline.output import write_excel, OUTPUT_PATH
    write_excel(df)
    with open(OUTPUT_PATH, "rb") as f:
        return f.read()


def _do_push(rows_df: pd.DataFrame, variant: str = "A") -> dict:
    """Call push_drafts with dry_run=False (explicit user action)."""
    from pipeline.sendgrid_push import push_drafts
    return push_drafts(rows_df, variant=variant, dry_run=False)


# ── session state init ────────────────────────────────────────────────────────
for key, default in [
    ("df", None),
    ("log", []),
    ("sg_status", None),
    ("upload_name", ""),
]:
    if key not in st.session_state:
        st.session_state[key] = default


# ── header ────────────────────────────────────────────────────────────────────
st.title("🧥 Fleek Retention Pipeline")
st.caption("Segment · Prioritise · Play · Draft · Push")

st.divider()

# ═════════════════════════════════════════════════════════════════════════════
# SECTION 1: UPLOAD
# ═════════════════════════════════════════════════════════════════════════════
st.header("📂 Upload")

uploaded = st.file_uploader(
    "Drop a portfolio .xlsx file (needs an **Accounts** tab)",
    type=["xlsx"],
    help="The pipeline expects the same schema as portfolio.xlsx: Accounts tab with 27 columns.",
)

if uploaded is not None and uploaded.name != st.session_state.upload_name:
    with st.spinner(f"Running pipeline on `{uploaded.name}`…"):
        try:
            df, log = _run_pipeline(uploaded.read(), uploaded.name)
            st.session_state.df = df
            st.session_state.log = log
            st.session_state.upload_name = uploaded.name
            st.session_state.sg_status = None   # reset push status on new upload
        except Exception as exc:
            st.error(f"Pipeline failed: {exc}")
            st.session_state.df = None
            st.session_state.log = [f"❌ {exc}"]

if st.session_state.log:
    with st.expander("Pipeline log", expanded=True):
        for line in st.session_state.log:
            st.markdown(line)

# ═════════════════════════════════════════════════════════════════════════════
# SECTION 2: PORTFOLIO VIEW
# ═════════════════════════════════════════════════════════════════════════════
if st.session_state.df is not None:
    df = st.session_state.df
    st.divider()
    st.header("📊 Portfolio View")

    col_tbl, col_dl = st.columns([3, 1])

    with col_tbl:
        counts_df = _segment_counts_table(df)
        # Highlight the TOTAL row
        def _style_counts(row):
            if row["Segment"] == "TOTAL":
                return ["font-weight: bold; background-color: #f0f0f0"] * len(row)
            colour = SEGMENT_COLOURS.get(row["Segment"], "")
            return [f"background-color: {colour}"] * len(row)

        st.dataframe(
            counts_df.style.apply(_style_counts, axis=1),
            use_container_width=True,
            hide_index=True,
        )

    with col_dl:
        st.markdown("**Download**")
        try:
            xlsx_bytes = _make_excel_bytes(df)
            st.download_button(
                label="⬇️ Priority Excel",
                data=xlsx_bytes,
                file_name=f"fleek_retention_{datetime.today().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        except Exception as e:
            st.warning(f"Excel generation failed: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 3: MESSAGE DRAFTS
    # ─────────────────────────────────────────────────────────────────────────
    st.divider()
    st.header("✉️ Message Drafts")

    # Filter controls
    filter_col1, filter_col2, filter_col3 = st.columns(3)
    with filter_col1:
        seg_filter = st.multiselect(
            "Segment",
            options=sorted(df["segment"].unique()),
            default=sorted(df["segment"].unique()),
        )
    with filter_col2:
        tier_filter = st.multiselect(
            "Tier",
            options=["T1", "T2", "T3"],
            default=["T1", "T2", "T3"],
        )
    with filter_col3:
        at_risk_only = st.checkbox("At Risk only")

    mask = df["segment"].isin(seg_filter) & df["tier"].isin(tier_filter)
    if at_risk_only:
        mask = mask & df["at_risk"].astype(bool)
    view_df = df[mask].copy()

    st.caption(f"Showing **{len(view_df)}** accounts")

    # Build display table
    display_cols = {
        "account_id":       "Account ID",
        "segment":          "Segment",
        "tier":             "Tier",
        "buyer_persona":    "Persona",
        "region":           "Region",
        "gmv_total_6m":     "GMV (£)",
        "msg_variant_a":    "Variant A",
        "msg_variant_b":    "Variant B",
    }
    available = [c for c in display_cols if c in view_df.columns]
    display_df = view_df[available].rename(columns=display_cols).copy()

    # Add a "Push?" checkbox column for row-level selection
    display_df.insert(0, "Push?", False)

    edited = st.data_editor(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Push?":       st.column_config.CheckboxColumn("Push?", default=False),
            "Variant A":   st.column_config.TextColumn("Variant A", width="large"),
            "Variant B":   st.column_config.TextColumn("Variant B", width="large"),
            "GMV (£)":     st.column_config.NumberColumn("GMV (£)", format="£%.0f"),
        },
        disabled=[c for c in display_df.columns if c != "Push?"],
        key="drafts_editor",
    )

    # Action buttons
    btn_col1, btn_col2, btn_col3, _ = st.columns([1, 1, 1, 4])

    with btn_col1:
        push_all_t1 = st.button("🚀 Push all T1", type="primary")
    with btn_col2:
        push_selected = st.button("📤 Push selected")
    with btn_col3:
        variant_choice = st.radio("Variant", ["A", "B"], horizontal=True, label_visibility="collapsed")

    if push_all_t1 or push_selected:
        if push_all_t1:
            # Push all T1 accounts currently in the filtered view
            target_ids = view_df[view_df["tier"] == "T1"]["account_id"].tolist()
            label = "T1"
        else:
            # Push rows the user ticked
            selected_ids = edited[edited["Push?"] == True]["Account ID"].tolist()
            target_ids = selected_ids
            label = "selected"

        if not target_ids:
            st.warning(f"No {label} accounts to push.")
        else:
            push_rows = df[df["account_id"].isin(target_ids)]
            with st.spinner(f"Pushing {len(push_rows)} {label} drafts to SendGrid…"):
                result = _do_push(push_rows, variant=variant_choice)
            st.session_state.sg_status = {**result, "pushed_count": len(push_rows), "label": label}
            st.rerun()

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 4: SENDGRID STATUS
    # ─────────────────────────────────────────────────────────────────────────
    if st.session_state.sg_status is not None:
        st.divider()
        st.header("📡 SendGrid Status")

        s = st.session_state.sg_status
        detail = s.get("detail", "")

        if detail:
            st.warning(detail)
        else:
            m1, m2, m3 = st.columns(3)
            m1.metric("✅ Pushed", s.get("queued", 0))
            m2.metric("⏸ Held (no email)", s.get("skipped", 0))
            m3.metric("❌ Errors", len(s.get("errors", [])))

        if s.get("errors"):
            with st.expander("Error details"):
                err_df = pd.DataFrame(s["errors"])
                st.dataframe(err_df, use_container_width=True, hide_index=True)

        st.caption(
            f"Last push: **{s.get('label', '')}** accounts · "
            f"{datetime.now().strftime('%H:%M:%S')}"
        )

# ── footer ────────────────────────────────────────────────────────────────────
st.markdown("---")
st.caption("Fleek Retention Pipeline · drafts only · nothing sends automatically")
