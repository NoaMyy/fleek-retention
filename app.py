"""
Fleek Retention — Streamlit dashboard.

Sections
--------
1. UPLOAD          — drop an .xlsx, run the full pipeline, show cleaning summary.
2. PORTFOLIO VIEW  — segment counts + downloads (actions Excel + cleaned data).
3. PRIORITY TABLES — three separate ranked tables (Broker Managed / Healthy AM / Self-Serve).
4. JOURNEY VIEW    — journey position distribution chart + message drafts.
5. SENDGRID STATUS — push results summary.

Run with:
    streamlit run app.py
"""
import io
import json
import os
import tempfile
from datetime import datetime

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

VARIANTS_PATH = "config/variants.json"


def load_variants() -> dict:
    """Load A/B message variants from config file. Returns defaults if missing."""
    try:
        with open(VARIANTS_PATH) as f:
            return json.load(f)
    except Exception:
        return {"broker_stages": {}, "ss_pathways": {}}


def save_variants(variants: dict) -> None:
    os.makedirs("config", exist_ok=True)
    with open(VARIANTS_PATH, "w") as f:
        json.dump(variants, f, indent=2)

# ── page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Fleek Retention",
    page_icon="🧥",
    layout="wide",
    initial_sidebar_state="expanded",
)

CONTACTS_PATH = "data/contacts.csv"

JOURNEY_ORDER = ["not_started", "stalled", "moving", "nearly_graduated"]
JOURNEY_LABELS = {
    "not_started":      "Broker Only",
    "stalled":          "Tried, Reverted",
    "moving":           "Gaining Momentum",
    "nearly_graduated": "Building Habit",
}

# A/B message angle per stage — used by drafter and sidebar
JOURNEY_VARIANTS = {
    "not_started": {
        "behaviour": "All orders placed via AM. No app activity. Goal: first self-serve order.",
        "a_angle":   "Value — 'Buyers in your category are saving X hours a week ordering directly.'",
        "b_angle":   "Simplicity — 'Your next order can be placed in under 2 minutes.'",
    },
    "stalled": {
        "behaviour": "Placed at least one self-serve order but reverted to AM. Something blocked them.",
        "a_angle":   "Remove friction — ask what got in the way, offer to fix it.",
        "b_angle":   "Encourage — acknowledge the first order; make the second feel easy.",
    },
    "moving": {
        "behaviour": "Regularly mixing self-serve with AM orders. Habit forming but not yet default.",
        "a_angle":   "Celebrate progress — name their current % and show the next milestone.",
        "b_angle":   "Concrete next step — flag the single easiest order to place themselves.",
    },
    "nearly_graduated": {
        "behaviour": "Majority self-serve. One nudge away from full graduation.",
        "a_angle":   "Close the gap — show what graduation unlocks (speed, availability).",
        "b_angle":   "Reassurance — 'You've got this; I'm still here if anything's unclear.'",
    },
}
NUDGE_LABELS = {
    "video_call": "Video Call",
    "chat":       "In-App Chat",
    "bundle":     "Bundle",
    "offer":      "Make an Offer",
}

# ── sidebar: category legend ──────────────────────────────────────────────────
with st.sidebar:
    st.title("🧥 Fleek Retention")
    st.divider()

    with st.expander("📖 Category Legend", expanded=False):
        st.markdown("""
**🟡 Broker Managed**
Account-managed buyers where the majority of orders are placed via a broker rather than the app.
- *Goal:* migrate to self-serve ordering
- *Signal:* broker reliance ≥ 50%, low app activity
- *Play:* Broker Migration — move through journey positions until they graduate

---

**🔵 Healthy AM**
Account-managed buyers already transacting through the platform with good engagement.
- *Goal:* retain and grow GMV
- *Signal:* account-managed, not broker-reliant
- *Play:* AM Retention — priority by GMV value

---

**🟢 True Headroom**
Self-serve buyers with high engagement (above-median) but low spend (below-median GMV).
- *Goal:* convert intent into purchases — strongest upsell opportunity
- *Play:* Self-Serve Nudge — targeted feature activation

---

**🟠 Passive Buyer**
Self-serve buyers with high GMV (above-median) but low engagement (below-median).
- *Goal:* re-activate before they go quiet — prevent churn
- *Play:* Re-engagement nudge — remind them what they're missing
        """)

    with st.expander("🗺 Broker Journey Stages", expanded=False):
        _vdata = load_variants()
        _b_stages = _vdata.get("broker_stages", {})
        for pos in JOURNEY_ORDER:
            s = _b_stages.get(pos, {})
            st.caption(f"{s.get('stage_name', pos)} · {s.get('criteria', '')}")
            st.markdown(f"**A:** {s.get('variant_a', '—')}")
            st.markdown(f"**B:** {s.get('variant_b', '—')}")
            st.divider()

    with st.expander("💬 Engagement Methods (Self-Serve)", expanded=False):
        st.markdown("""
| Method | Trigger |
|---|---|
| **Video Call** | High PDP views but no video calls booked |
| **In-App Chat** | Active offer-maker but not using chat |
| **Bundle** | Multi-order buyer not using bundles |
        """)

    st.divider()
    st.caption("Nothing sends automatically. SendGrid push requires explicit approval.")


# ── account card renderers ────────────────────────────────────────────────────

def _card_css():
    """Inject shared card styles once."""
    st.markdown("""
    <style>
    .fleek-card {
        border: 1px solid #e0e0e0;
        border-radius: 8px;
        padding: 12px 16px;
        margin-bottom: 10px;
        background: #fafafa;
    }
    .fleek-card-broker  { border-left: 4px solid #F4A700; background: #fffdf4; }
    .fleek-card-headroom{ border-left: 4px solid #27AE60; background: #f4fff8; }
    .fleek-card-passive { border-left: 4px solid #E67E22; background: #fff8f4; }
    .fleek-card-title   { font-weight: 700; font-size: 14px; margin-bottom: 6px; color: #111; }
    .fleek-card-metrics { display: flex; gap: 20px; flex-wrap: wrap;
                          font-size: 13px; margin-bottom: 6px; }
    .fleek-card-metric  { display: flex; flex-direction: column; }
    .fleek-card-label   { font-size: 10px; color: #888; text-transform: uppercase; }
    .fleek-card-value   { font-size: 14px; font-weight: 600; color: #222; }
    .fleek-card-just    { font-size: 12px; color: #555; line-height: 1.4; }
    </style>
    """, unsafe_allow_html=True)


def _metric_html(label, value):
    return (
        f'<div class="fleek-card-metric">'
        f'<span class="fleek-card-label">{label}</span>'
        f'<span class="fleek-card-value">{value}</span>'
        f'</div>'
    )


def _render_broker_cards(broker_df: "pd.DataFrame") -> None:
    _card_css()
    for _, row in broker_df.iterrows():
        rank      = int(row.get("seg_rank", 0))
        account   = row.get("account_id", "")
        country   = row.get("country", "")
        broker_pct= row.get("broker_reliance_pct", 0)
        manual    = int(row.get("manual_orders", 0))
        ss_orders = int(row.get("self_serve_orders", 0))
        gmv       = row.get("gmv_total_6m", 0)
        trend     = row.get("gmv_trend", "—")
        journey   = JOURNEY_LABELS.get(row.get("journey_position", ""), "—")
        just      = row.get("justification", "")

        metrics = "".join([
            _metric_html("Broker Reliance", f"{broker_pct:.0f}%"),
            _metric_html("Manual Orders", str(manual)),
            _metric_html("Self-Serve Orders", str(ss_orders)),
            _metric_html("GMV (6m)", f"£{gmv:,.0f}"),
            _metric_html("GMV Trend", trend),
            _metric_html("Journey Position", journey),
        ])
        st.markdown(f"""
        <div class="fleek-card fleek-card-broker">
          <div class="fleek-card-title">#{rank} · {account} · {country}</div>
          <div class="fleek-card-metrics">{metrics}</div>
          <div class="fleek-card-just">{just}</div>
        </div>
        """, unsafe_allow_html=True)


def _render_ss_cards(ss_df: "pd.DataFrame", card_class: str) -> None:
    _card_css()
    for _, row in ss_df.iterrows():
        rank    = int(row.get("seg_rank", 0))
        account = row.get("account_id", "")
        country = row.get("country", "")
        eng     = row.get("engagement_score", 0)
        pdp     = int(row.get("pdp_views_6m", 0))
        days    = int(row.get("app_active_days_6m", 0))
        gmv     = row.get("gmv_total_6m", 0)
        gmv_feb = row.get("gmv_feb", 0)
        trend   = row.get("gmv_trend", "—")
        nudge   = NUDGE_LABELS.get(row.get("nudge_feature", ""), "—")
        just    = row.get("justification", "")

        metrics = "".join([
            _metric_html("Engagement Score", f"{eng:.0f}"),
            _metric_html("App Days", str(days)),
            _metric_html("PDP Views", str(pdp)),
            _metric_html("GMV (6m)", f"£{gmv:,.0f}"),
            _metric_html("GMV Trend", trend),
            _metric_html("Recommended Feature", nudge),
        ])
        st.markdown(f"""
        <div class="fleek-card {card_class}">
          <div class="fleek-card-title">#{rank} · {account} · {country}</div>
          <div class="fleek-card-metrics">{metrics}</div>
          <div class="fleek-card-just">{just}</div>
        </div>
        """, unsafe_allow_html=True)


# ── helpers ───────────────────────────────────────────────────────────────────

def _run_pipeline(uploaded_bytes: bytes, filename: str) -> tuple:
    from pipeline.clean import load_and_clean, save_versioned_upload, merge_into_master
    from pipeline.segment import segment
    from pipeline.prioritise import prioritise
    from pipeline.plays import assign_plays
    from agents.drafter import draft_messages

    log = []

    # Save versioned upload copy
    versioned_path = save_versioned_upload(uploaded_bytes, filename)
    log.append(f"💾 Saved versioned copy: `{os.path.basename(versioned_path)}`")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        tmp.write(uploaded_bytes)
        tmp_path = tmp.name

    try:
        # 1. Clean
        df, stats = load_and_clean(tmp_path)
        log.append(f"✅ Loaded **{stats['accounts_loaded']}** rows from `{filename}`")
        if stats.get("new_accounts_tab_loaded", 0) > 0:
            log.append(f"✅ Auto-detected **new_accounts** tab — **{stats['new_accounts_tab_loaded']}** additional rows included")
        if stats["duplicates_removed"] > 0:
            log.append(f"🔁 **{stats['duplicates_removed']}** duplicate account IDs removed (last row kept)")
        if stats["rows_dropped_no_id"] > 0:
            log.append(f"⚠️ **{stats['rows_dropped_no_id']}** rows dropped — missing account ID")
        if stats["total_gap_cells"] > 0:
            gap_detail = ", ".join(f"{k}: {v}" for k, v in stats["data_gaps_filled"].items())
            log.append(
                f"🔧 **{stats['total_gap_cells']}** blank cells filled with 0 across "
                f"{stats['fields_with_gaps']} numeric fields ({gap_detail})"
            )
        log.append(
            f"✅ Clean complete — **{stats['accounts_after_clean']}** accounts · "
            f"{stats['account_managed_count']} account-managed · "
            f"{stats['self_serve_count']} self-serve"
        )

        # Merge into master
        new_count = merge_into_master(df)
        if new_count > 0:
            log.append(f"📚 Master portfolio updated — **{new_count}** net new accounts added")
        else:
            log.append("📚 Master portfolio updated — no new accounts (all already in master)")

        # Reload from master so pipeline runs on the full cumulative portfolio
        from pipeline.clean import MASTER_PATH
        if os.path.exists(MASTER_PATH):
            df, master_stats = load_and_clean(MASTER_PATH)
            log.append(
                f"🔄 Running on full master portfolio — **{len(df)}** accounts "
                f"({stats['accounts_after_clean']} in this upload)"
            )

        # 2. Segment
        df = segment(df)
        counts = df["segment"].value_counts().to_dict()
        broker_n = counts.get("BROKER_RELIANT", 0)
        am_n = counts.get("HEALTHY_AM", 0)
        ss_th = counts.get("TRUE_HEADROOM", 0)
        ss_pb = counts.get("PASSIVE_BUYER", 0)
        ss_other = counts.get("SELF_SERVE_OTHER", 0)
        log.append(
            f"✅ Segmented — 🟡 Broker Managed: **{broker_n}** · "
            f"🔵 Healthy AM: **{am_n}** · "
            f"🟢 Self-Serve: **{ss_th + ss_pb + ss_other}** "
            f"({ss_th} true headroom · {ss_pb} passive buyer · {ss_other} other)"
        )
        log.append(
            "_Criteria — Broker Managed: account-managed + ≥50% broker reliance + low app activity. "
            "Healthy AM: account-managed, not broker-reliant. "
            "True Headroom: self-serve with engagement ≥ median but GMV < median. "
            "Passive Buyer: self-serve with GMV ≥ median but engagement < median._"
        )

        # 3. Prioritise
        df = prioritise(df)
        log.append("✅ Prioritised — Broker by manual orders↓ + GMV↓ · AM by health then GMV↓ · Self-Serve by engagement↓")

        # 4. Plays
        df = assign_plays(df)
        log.append("✅ Journey positions assigned")

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

        if "touch_number" not in df.columns:
            df["touch_number"] = 1
        df["tier"] = "T" + df["touch_number"].astype(int).astype(str)

    finally:
        os.unlink(tmp_path)

    return df, log, stats


def _make_excel_bytes(df: pd.DataFrame) -> bytes:
    from pipeline.output import get_excel_bytes
    return get_excel_bytes(df)


def _make_cleaned_bytes(df: pd.DataFrame) -> bytes:
    from pipeline.output import get_cleaned_excel_bytes
    return get_cleaned_excel_bytes(df)


def _do_push(rows_df: pd.DataFrame, variant: str = "A") -> dict:
    from pipeline.sendgrid_push import push_drafts
    return push_drafts(rows_df, variant=variant, dry_run=False)


def _get_journey_context(row):
    seg = row.get("segment", "")
    if seg == "BROKER_RELIANT":
        pos = row.get("journey_position", "") or ""
        return JOURNEY_LABELS.get(pos, pos)
    elif seg == "HEALTHY_AM":
        health = row.get("health_status", "stable") or "stable"
        return {"growing": "🟢 Growing", "declining": "🔴 Declining", "stable": "🟡 Stable"}.get(health, health.title())
    elif seg in ("TRUE_HEADROOM", "PASSIVE_BUYER", "SELF_SERVE_OTHER"):
        nudge = row.get("nudge_feature", "") or ""
        return NUDGE_LABELS.get(nudge, nudge)
    return "—"


def _get_engagement_method(row):
    seg = row.get("segment", "")
    if seg == "BROKER_RELIANT":
        return "SMS / Direct outreach"
    elif seg in ("TRUE_HEADROOM", "PASSIVE_BUYER", "SELF_SERVE_OTHER"):
        nudge = row.get("nudge_feature", "") or ""
        return NUDGE_LABELS.get(nudge, nudge)
    return "SMS / Account Manager"


# ── session state ─────────────────────────────────────────────────────────────
for key, default in [
    ("df", None), ("log", []), ("stats", {}),
    ("sg_status", None), ("upload_name", ""),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# ── version history helpers ───────────────────────────────────────────────────
VERSIONS_DIR = "data/versions"
os.makedirs(VERSIONS_DIR, exist_ok=True)


def _list_versions() -> list[str]:
    """Return versioned upload files sorted newest first."""
    files = [f for f in os.listdir(VERSIONS_DIR) if f.endswith(".xlsx")]
    return sorted(files, reverse=True)


# ── header ────────────────────────────────────────────────────────────────────
st.title("🧥 Fleek Retention Pipeline")
st.caption("Segment · Prioritise · Play · Draft · Push")
st.divider()

# ── previous uploads sidebar ─────────────────────────────────────────────────
with st.sidebar:
    st.header("Previous Uploads")
    _versions = _list_versions()
    if not _versions:
        st.caption("No previous uploads found.")
    else:
        _selected = st.selectbox(
            "Load a previous dataset",
            options=_versions,
            index=None,
            placeholder="Choose a file…",
        )
        if _selected and _selected != st.session_state.get("upload_name"):
            if st.button("Load", use_container_width=True):
                _path = os.path.join(VERSIONS_DIR, _selected)
                with st.spinner(f"Running pipeline on `{_selected}`…"):
                    try:
                        df, log, stats = _run_pipeline(open(_path, "rb").read(), _selected)
                        st.session_state.df = df
                        st.session_state.log = log
                        st.session_state.stats = stats
                        st.session_state.upload_name = _selected
                        st.session_state.sg_status = None
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Failed to load: {exc}")

# ═════════════════════════════════════════════════════════════════════════════
# SECTION 1: UPLOAD
# ═════════════════════════════════════════════════════════════════════════════
st.header("📂 Upload")

uploaded = st.file_uploader(
    "Drop a portfolio .xlsx file (needs an **Accounts** tab)",
    type=["xlsx"],
    help="Expected schema: Accounts tab with account_id, ownership, GMV columns, and behavioural signals.",
)

if uploaded is not None and uploaded.name != st.session_state.upload_name:
    with st.spinner(f"Running pipeline on `{uploaded.name}`…"):
        try:
            df, log, stats = _run_pipeline(uploaded.read(), uploaded.name)
            st.session_state.df = df
            st.session_state.log = log
            st.session_state.stats = stats
            st.session_state.upload_name = uploaded.name
            st.session_state.sg_status = None
        except Exception as exc:
            st.error(f"Pipeline failed: {exc}")
            st.session_state.df = None
            st.session_state.log = [f"❌ {exc}"]

if st.session_state.log:
    with st.expander("📋 Data Cleaning & Pipeline Log", expanded=True):
        for line in st.session_state.log:
            st.markdown(line)

# ═════════════════════════════════════════════════════════════════════════════
# SECTION 2: PORTFOLIO OVERVIEW
# ═════════════════════════════════════════════════════════════════════════════
if st.session_state.df is not None:
    df = st.session_state.df
    stats = st.session_state.stats
    st.divider()
    st.header("📊 Portfolio Overview")

    broker_n = int((df["segment"] == "BROKER_RELIANT").sum())
    am_n = int((df["segment"] == "HEALTHY_AM").sum())
    ss_n = int(df["segment"].isin(["TRUE_HEADROOM", "PASSIVE_BUYER", "SELF_SERVE_OTHER"]).sum())
    ss_th = int((df["segment"] == "TRUE_HEADROOM").sum())
    ss_pb = int((df["segment"] == "PASSIVE_BUYER").sum())

    # ── What Changed summary ──────────────────────────────────────────────────
    with st.expander("🔍 What Changed in This Upload", expanded=True):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Rows loaded", stats.get("accounts_loaded", "—"))
        c2.metric("Duplicates removed", stats.get("duplicates_removed", 0))
        c3.metric("Blank cells filled", stats.get("total_gap_cells", 0))
        c4.metric("Clean accounts", stats.get("accounts_after_clean", "—"))

        new_tab = stats.get("new_accounts_tab_loaded", 0)
        if new_tab > 0:
            st.info(f"**new_accounts tab detected** — {new_tab} rows included and merged (duplicates deduplicated).")

        if stats.get("total_gap_cells", 0) > 0:
            gaps = stats.get("data_gaps_filled", {})
            gap_text = " · ".join(f"{k}: {v} blank{'s' if v>1 else ''}" for k, v in gaps.items())
            st.caption(f"Fields with blanks filled → {gap_text}")

        # Segment breakdown
        st.markdown("**How the book was segmented:**")
        growing   = int(((df["segment"] == "HEALTHY_AM") & (df["health_status"] == "growing")).sum())
        stable    = int(((df["segment"] == "HEALTHY_AM") & (df["health_status"] == "stable")).sum())
        declining = int(((df["segment"] == "HEALTHY_AM") & (df["health_status"] == "declining")).sum())
        ss_other  = int((df["segment"] == "SELF_SERVE_OTHER").sum())

        seg_summary = (
            f"🟡 **Broker Managed: {broker_n}** — account-managed with ≥50% orders via broker, low app activity. "
            f"Goal: migrate to self-serve.  \n"
            f"🔵 **Healthy AM: {am_n}** — account-managed, transacting on platform "
            f"({growing} growing · {stable} stable · {declining} declining). "
            f"Goal: retain and grow.  \n"
            f"🟢 **True Headroom: {ss_th}** — self-serve with high engagement but low spend. "
            f"Strongest upsell opportunity.  \n"
            f"🟠 **Passive Buyer: {ss_pb}** — self-serve with high GMV but low engagement. "
            f"Re-activation needed to reduce churn risk."
        )
        st.markdown(seg_summary)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Accounts", len(df))
    m2.metric("🟡 Broker Managed", broker_n)
    m3.metric("🔵 Healthy AM", am_n)
    m4.metric("🟢 Self-Serve", ss_n)

    dl1, dl2, _ = st.columns([1, 1, 4])
    with dl1:
        try:
            st.download_button(
                label="⬇️ Priority Excel",
                data=_make_excel_bytes(df),
                file_name=f"fleek_retention_{datetime.today().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        except Exception as e:
            st.warning(f"Excel generation failed: {e}")
    with dl2:
        try:
            st.download_button(
                label="⬇️ Cleaned Data",
                data=_make_cleaned_bytes(df),
                file_name=f"fleek_cleaned_{datetime.today().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        except Exception as e:
            st.warning(f"Cleaned data export failed: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 2b: PORTFOLIO HEALTH CHARTS
    # ─────────────────────────────────────────────────────────────────────────
    import altair as alt

    st.divider()
    st.header("📈 Portfolio Health")

    ch1, ch2 = st.columns(2)

    with ch1:
        st.subheader("Monthly GMV trend")
        gmv_month_map = [
            ("Sep", "gmv_sep"), ("Oct", "gmv_oct"), ("Nov", "gmv_nov"),
            ("Dec", "gmv_dec"), ("Jan", "gmv_jan"), ("Feb", "gmv_feb"),
        ]
        monthly_data = pd.DataFrame([
            {"Month": label, "GMV": df[col].sum()}
            for label, col in gmv_month_map if col in df.columns
        ])
        if not monthly_data.empty:
            trend_chart = (
                alt.Chart(monthly_data)
                .mark_line(point=True, strokeWidth=2, color="#185FA5")
                .encode(
                    x=alt.X("Month:N",
                            sort=[m for m, _ in gmv_month_map],
                            axis=alt.Axis(labelAngle=0, title=None)),
                    y=alt.Y("GMV:Q",
                            axis=alt.Axis(title="GMV (£)",
                                          labelExpr="'£' + format(datum.value / 1000, ',.0f') + 'k'")),
                    tooltip=[alt.Tooltip("Month:N", title="Month"),
                             alt.Tooltip("GMV:Q", format=",.0f", title="GMV (£)")],
                )
                .properties(height=220)
            )
            st.altair_chart(trend_chart, use_container_width=True)
        else:
            st.info("No monthly GMV data available.")

    with ch2:
        st.subheader("GMV at risk")
        declining_mask = (df["segment"] == "HEALTHY_AM") & (df["health_status"] == "declining")
        passive_mask = df["segment"] == "PASSIVE_BUYER"
        at_risk_gmv = df[declining_mask | passive_mask]["gmv_total_6m"].sum()
        total_gmv = df["gmv_total_6m"].sum()
        safe_gmv = total_gmv - at_risk_gmv
        risk_pct = (at_risk_gmv / total_gmv * 100) if total_gmv > 0 else 0

        ra, rb = st.columns(2)
        ra.metric("At-risk GMV", f"£{at_risk_gmv:,.0f}")
        rb.metric("% of portfolio", f"{risk_pct:.0f}%")

        risk_data = pd.DataFrame([
            {"Category": "Safe", "GMV": safe_gmv},
            {"Category": "Declining AM", "GMV": df[declining_mask]["gmv_total_6m"].sum()},
            {"Category": "Passive Buyer", "GMV": df[passive_mask]["gmv_total_6m"].sum()},
        ])
        risk_chart = (
            alt.Chart(risk_data)
            .mark_bar()
            .encode(
                x=alt.X("GMV:Q", axis=alt.Axis(
                    title="GMV (£)",
                    labelExpr="'£' + format(datum.value / 1000, ',.0f') + 'k'",
                )),
                y=alt.Y("Category:N", sort="-x", axis=alt.Axis(title=None)),
                color=alt.Color(
                    "Category:N",
                    scale=alt.Scale(
                        domain=["Safe", "Declining AM", "Passive Buyer"],
                        range=["#27AE60", "#E24B4A", "#E67E22"],
                    ),
                    legend=None,
                ),
                tooltip=[alt.Tooltip("Category:N"), alt.Tooltip("GMV:Q", format=",.0f", title="GMV (£)")],
            )
            .properties(height=130)
        )
        st.altair_chart(risk_chart, use_container_width=True)

        with st.expander("👁 View at-risk accounts", expanded=False):
            _at_risk_cols = [c for c in ["account_id", "country", "segment", "health_status", "gmv_total_6m", "gmv_trend"] if c in df.columns]
            _at_risk = df[declining_mask | passive_mask][_at_risk_cols].copy()
            _at_risk["Risk Reason"] = _at_risk.apply(
                lambda r: "🔴 Declining AM" if r.get("segment") == "HEALTHY_AM" else "🟠 Passive Buyer", axis=1
            )
            _at_risk_display = _at_risk.rename(columns={
                "account_id": "Account", "country": "Country",
                "segment": "Segment", "health_status": "Health",
                "gmv_total_6m": "GMV 6m (£)", "gmv_trend": "Trend",
            }).drop(columns=["Segment"], errors="ignore")
            st.dataframe(
                _at_risk_display.style.format({"GMV 6m (£)": "£{:,.0f}"}),
                use_container_width=True, hide_index=True,
            )

    ch3, ch4 = st.columns(2)

    with ch3:
        st.subheader("Broker migration funnel")
        broker_seg = df[df["segment"] == "BROKER_RELIANT"].copy()
        if broker_seg.empty:
            st.info("No broker accounts.")
        else:
            funnel_rows = []
            for pos in JOURNEY_ORDER:
                subset = broker_seg[broker_seg["journey_position"] == pos]
                funnel_rows.append({
                    "Stage": JOURNEY_LABELS.get(pos, pos),
                    "Accounts": len(subset),
                    "GMV": subset["gmv_total_6m"].sum(),
                })
            funnel_data = pd.DataFrame(funnel_rows)
            funnel_chart = (
                alt.Chart(funnel_data)
                .mark_bar(color="#F4A700")
                .encode(
                    y=alt.Y(
                        "Stage:N",
                        sort=[JOURNEY_LABELS[p] for p in JOURNEY_ORDER],
                        axis=alt.Axis(title=None),
                    ),
                    x=alt.X("Accounts:Q", axis=alt.Axis(title="Accounts")),
                    tooltip=[
                        alt.Tooltip("Stage:N"),
                        alt.Tooltip("Accounts:Q"),
                        alt.Tooltip("GMV:Q", format=",.0f", title="GMV (£)"),
                    ],
                )
                .properties(height=220)
            )
            st.altair_chart(funnel_chart, use_container_width=True)

    with ch4:
        st.subheader("Feature adoption (self-serve)")
        ss_mask = df["segment"].isin(["TRUE_HEADROOM", "PASSIVE_BUYER", "SELF_SERVE_OTHER"])
        ss_total = int(ss_mask.sum()) or 1
        feat_rows = [
            ("Bundle", "bundle_orders"),
            ("Offers", "make_an_offer_6m"),
            ("In-app chat", "chat_threads"),
            ("Handpick", "handpick_orders"),
            ("Video call", "video_call_requests"),
        ]
        feat_data = pd.DataFrame([
            {
                "Feature": label,
                "Adoption %": round((df.loc[ss_mask, col] > 0).sum() / ss_total * 100),
            }
            for label, col in feat_rows
        ]).sort_values("Adoption %")
        feat_chart = (
            alt.Chart(feat_data)
            .mark_bar(color="#1D9E75")
            .encode(
                x=alt.X(
                    "Adoption %:Q",
                    scale=alt.Scale(domain=[0, 100]),
                    axis=alt.Axis(format=".0f", title="% of self-serve accounts"),
                ),
                y=alt.Y("Feature:N", sort="-x", axis=alt.Axis(title=None)),
                tooltip=[
                    alt.Tooltip("Feature:N"),
                    alt.Tooltip("Adoption %:Q", format=".0f", title="Adoption %"),
                ],
            )
            .properties(height=220)
        )
        st.altair_chart(feat_chart, use_container_width=True)

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 3: PRIORITY TABLES
    # ─────────────────────────────────────────────────────────────────────────
    st.divider()
    st.header("🎯 Priority Rankings")
    st.caption(
        "Three separate tables ranked by the criteria most relevant to each category. "
        "Each row includes a justification explaining why the account is positioned where it is."
    )

    tab_broker, tab_am, tab_th, tab_pb = st.tabs([
        f"🟡 Broker Managed ({broker_n})",
        f"🔵 Healthy AM ({am_n})",
        f"🟢 True Headroom ({ss_th})",
        f"🟠 Passive Buyer ({ss_pb})",
    ])

    with tab_broker:
        broker_df = df[df["segment"] == "BROKER_RELIANT"].copy()
        if broker_df.empty:
            st.info("No Broker Managed accounts in this portfolio.")
        else:
            st.caption(
                "Ranked by manual orders↓ (highest AM burden first), then GMV↓. "
                "These accounts consume the most AM time — highest priority to migrate to self-serve."
            )
            display_cols = {
                "seg_rank": "#", "account_id": "Account ID",
                "country": "Location", "broker_reliance_pct": "Broker %",
                "manual_orders": "Manual Orders", "self_serve_orders": "Self-Serve Orders",
                "orders_6m": "Total Orders (6m)", "gmv_total_6m": "GMV (£)",
                "gmv_trend": "GMV Trend",
                "journey_position": "Journey Position",
                "engagement_summary": "Engagement Behaviour",
            }
            avail = [c for c in display_cols if c in broker_df.columns]
            display = broker_df[avail].rename(columns=display_cols).copy()
            if "Journey Position" in display.columns:
                display["Journey Position"] = display["Journey Position"].map(
                    JOURNEY_LABELS
                ).fillna(display["Journey Position"])
            st.dataframe(
                display.style.format({"GMV (£)": "£{:,.0f}", "Broker %": "{:.0f}%"}),
                use_container_width=True, hide_index=True,
                column_config={
                    "Engagement Behaviour": st.column_config.TextColumn("Engagement Behaviour", width="large"),
                    "Journey Position": st.column_config.TextColumn("Journey Position", width="medium"),
                },
            )
            st.divider()
            with st.expander("📋 Account Summaries", expanded=True):
                _render_broker_cards(broker_df)

    with tab_am:
        am_df = df[df["segment"] == "HEALTHY_AM"].copy()
        if am_df.empty:
            st.info("No Healthy AM accounts in this portfolio.")
        else:
            # ── Declining alert banner ────────────────────────────────────
            _declining = am_df[am_df["health_status"] == "declining"]
            if not _declining.empty:
                _dec_ids  = ", ".join(_declining["account_id"].tolist())
                _dec_gmv  = _declining["gmv_total_6m"].sum()
                st.error(
                    f"🚨 **{len(_declining)} account{'s' if len(_declining) > 1 else ''} require immediate attention** — "
                    f"declining GMV and low engagement confirmed on both signals.  \n"
                    f"**Accounts:** {_dec_ids}  \n"
                    f"**GMV at risk:** £{_dec_gmv:,.0f} — proactive save call recommended before further deterioration.",
                    icon="🚨",
                )

            st.caption(
                "Ranked by health status (declining first), then GMV. "
                "🔴 Declining = GMV down >20% first-half to second-half AND very low app engagement — strong combined signal."
            )
            display_cols = {
                "seg_rank": "#", "account_id": "Account ID",
                "health_status": "Health",
                "gmv_total_6m": "GMV (£)", "gmv_trend": "GMV Trend",
                "app_active_days_6m": "App Days", "pdp_views_6m": "PDP Views",
                "engagement_score": "Engagement Score", "justification": "Justification",
            }
            avail = [c for c in display_cols if c in am_df.columns]
            display = am_df[avail].rename(columns=display_cols).copy()
            if "Health" in display.columns:
                health_map = {"growing": "🟢 Growing", "declining": "🔴 Declining — act now", "stable": "🟡 Stable"}
                display["Health"] = display["Health"].map(health_map).fillna("🟡 Stable")
            st.dataframe(
                display.style.format({"GMV (£)": "£{:,.0f}", "Engagement Score": "{:.0f}"}),
                use_container_width=True, hide_index=True,
                column_config={
                    "Health":        st.column_config.TextColumn("Health", width="medium"),
                    "Justification": st.column_config.TextColumn("Justification", width="large"),
                },
            )

    def _render_ss_tab(seg_df, caption_text):
        if seg_df.empty:
            st.info("No accounts in this segment.")
            return
        st.caption(caption_text)
        display_cols = {
            "seg_rank": "#", "account_id": "Account ID", "country": "Country",
            "self_serve_orders": "Self-Serve Orders",
            "engagement_score": "Engagement Score",
            "pdp_views_6m": "PDP Views", "app_active_days_6m": "App Days",
            "gmv_total_6m": "GMV 6m (£)",
            "gmv_trend": "GMV Trend",
            "make_an_offer_6m": "Offers", "chat_threads": "Chats",
            "video_call_requests": "Video Calls",
            "bundle_orders": "Bundle Orders", "handpick_orders": "Handpick Orders",
            "bundle_gmv_share_pct": "Bundle GMV %",
            "nudge_feature": "Recommended Feature", "justification": "Justification",
        }
        avail = [c for c in display_cols if c in seg_df.columns]
        display = seg_df[avail].rename(columns=display_cols).copy()
        if "Recommended Feature" in display.columns:
            display["Recommended Feature"] = display["Recommended Feature"].map(
                NUDGE_LABELS
            ).fillna(display["Recommended Feature"])
        fmt = {"GMV 6m (£)": "£{:,.0f}", "Engagement Score": "{:.1f}"}
        st.dataframe(
            display.style.format(fmt),
            use_container_width=True, hide_index=True,
            column_config={
                "Justification":        st.column_config.TextColumn("Justification", width="large"),
                "Recommended Feature":  st.column_config.TextColumn("Recommended Feature", width="medium"),
            },
        )

    with tab_th:
        th_df = df[df["segment"] == "TRUE_HEADROOM"].copy()
        _render_ss_tab(
            th_df,
            "Ranked by engagement score (highest intent first). "
            "High engagement + low spend = best upsell opportunity — focus on converting browsing to buying.",
        )
        if not th_df.empty:
            st.divider()
            with st.expander("📋 Account Summaries", expanded=True):
                _render_ss_cards(th_df, "fleek-card-headroom")

    with tab_pb:
        pb_df = df[df["segment"] == "PASSIVE_BUYER"].copy()
        _render_ss_tab(
            pb_df,
            "Ranked by GMV (highest value at risk first). "
            "High spend + low engagement = churn risk — re-activate before they go quiet.",
        )
        if not pb_df.empty:
            st.divider()
            with st.expander("📋 Account Summaries", expanded=True):
                _render_ss_cards(pb_df, "fleek-card-passive")

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 4: JOURNEY MAP
    # ─────────────────────────────────────────────────────────────────────────
    st.divider()
    st.header("🗺 Journey Map")

    _jmap_broker, _jmap_ss = st.tabs([
        f"🟡 Broker Migration ({broker_n})",
        f"🟢 Self-Serve Engagement ({ss_n})",
    ])

    # ── Broker Journey Map ──────────────────────────────────────────────────
    with _jmap_broker:
        if broker_n == 0:
            st.info("No broker accounts in this portfolio.")
        else:
            _bdf = df[df["segment"] == "BROKER_RELIANT"].copy()
            _bvariants = load_variants().get("broker_stages", {})

            st.caption(
                "Accounts ordered by priority rank (highest AM burden first). "
                "Goal at every stage: move them one step closer to self-serve independence."
            )
            _bcols = st.columns(4)

            for _i, _pos in enumerate(JOURNEY_ORDER):
                _stage_df = _bdf[_bdf["journey_position"] == _pos].sort_values(
                    "seg_rank", ascending=True
                )
                _s = _bvariants.get(_pos, {})
                _label = _s.get("stage_name", JOURNEY_LABELS.get(_pos, _pos))
                _n = len(_stage_df)
                _gmv = _stage_df["gmv_total_6m"].sum()

                with _bcols[_i]:
                    st.markdown(f"**{_label}**")
                    st.caption(f"{_s.get('criteria', '')}  \n**{_n}** accounts · £{_gmv:,.0f} GMV")
                    if _n == 0:
                        st.markdown(
                            "<div style='font-size:12px;color:var(--color-text-tertiary);"
                            "padding:8px 0'>No accounts at this stage</div>",
                            unsafe_allow_html=True,
                        )
                        continue

                    for _, _row in _stage_df.iterrows():
                        _bp      = _row.get("broker_reliance_pct", 0)
                        _man     = int(_row.get("manual_orders", 0))
                        _ss      = int(_row.get("self_serve_orders", 0))
                        _gmv_acc = _row.get("gmv_total_6m", 0)
                        _trend   = _row.get("gmv_trend", "—")

                        st.markdown(
                            f"<div style='border:0.5px solid var(--color-border-tertiary);"
                            f"border-left:3px solid #F4A700;border-radius:6px;"
                            f"padding:8px 10px;margin-bottom:6px;background:var(--color-background-primary)'>"
                            f"<div style='font-weight:500;font-size:13px'>"
                            f"{_row['account_id']} · {_row.get('country','')}</div>"
                            f"<div style='font-size:11px;color:var(--color-text-secondary);margin-top:3px'>"
                            f"£{_gmv_acc:,.0f} · {_trend} · {_bp:.0f}% broker</div>"
                            f"<div style='font-size:11px;color:var(--color-text-secondary)'>"
                            f"{_man} manual · {_ss} self-serve orders</div>"
                            f"</div>",
                            unsafe_allow_html=True,
                        )

    # ── Self-Serve Engagement Journey ───────────────────────────────────────
    with _jmap_ss:
        # 4 buyer journey stages — derived from behavioural signals, not segment labels.
        # Browser → Consideration → Purchase, plus Re-engagement for lapsed accounts.
        _SS_STAGES = [
            (
                "ss_browser",
                "Browser",
                "#8E8E93",
                "Low orders · no negotiation activity yet",
                "video_call",
                "Just getting started — placed orders but haven't engaged with offers or chat. "
                "Average 1.3 orders, £194 GMV. A video call lets them see stock before committing "
                "and builds the supplier relationship that drives repeat buying.",
            ),
            (
                "ss_consideration",
                "Consideration",
                "#378ADD",
                "Active on offers & chat · not yet converting",
                "offer",
                "Researching and negotiating (3.2 avg offers, 3.1 avg chat, 173 PDP views) "
                "but only 1 order on average. Already comfortable with the platform — "
                "an offer prompt helps close the deal they're already building toward.",
            ),
            (
                "ss_purchase",
                "Purchase",
                "#1D9E75",
                "Regular buyer · high engagement",
                "bundle",
                "Your strongest self-serve accounts — £2,266 avg GMV, 5 avg orders, very active. "
                "Bundle ordering reduces fulfilment time and consolidates spend. "
                "No outreach urgency; nudge toward efficiency.",
            ),
            (
                "ss_reengagement",
                "Re-engagement",
                "#E67E22",
                "High past spend · gone quiet",
                "chat",
                "Spent well before (£406 avg GMV) but now low engagement (6.9 avg) and barely ordering. "
                "In-app chat is personal and low-effort — the right restart signal for lapsed accounts "
                "who already know the platform.",
            ),
        ]

        _ss_all = df[df["segment"].isin(["TRUE_HEADROOM", "PASSIVE_BUYER", "SELF_SERVE_OTHER"])].copy()

        # Compute buyer journey stage inline (mirrors plays.py logic)
        def _buyer_stage(row):
            gmv    = row.get("gmv_total_6m", 0)
            eng    = row.get("engagement_score", 0)
            offers = row.get("make_an_offer_6m", 0)
            chat   = row.get("chat_threads", 0)
            orders = row.get("orders_6m", 0)
            if gmv > 200 and eng < 15 and orders <= 2:
                return "ss_reengagement"
            if orders >= 2 and eng >= 20:
                return "ss_purchase"
            if (offers > 0 or chat > 0) and orders <= 2:
                return "ss_consideration"
            return "ss_browser"

        _ss_all["buyer_stage"] = _ss_all.apply(_buyer_stage, axis=1)

        _sscols = st.columns(4)

        for _i, (_stage_key, _sname, _scol, _signal, _nudge_key, _rationale) in enumerate(_SS_STAGES):
            _col_df = _ss_all[_ss_all["buyer_stage"] == _stage_key].sort_values(
                "gmv_total_6m", ascending=False
            )
            _n       = len(_col_df)
            _gmv     = _col_df["gmv_total_6m"].sum()
            _avg_gmv = _col_df["gmv_total_6m"].mean() if _n > 0 else 0
            _avg_eng = _col_df["engagement_score"].mean() if _n > 0 else 0

            with _sscols[_i]:
                st.markdown(f"**{_sname}**")
                st.caption(f"{_signal}  \n**{_n}** accounts · £{_gmv:,.0f} total GMV")
                st.markdown(
                    f"<div style='display:flex;gap:16px;margin:4px 0 4px;font-size:11px'>"
                    f"<span>avg GMV <strong>£{_avg_gmv:,.0f}</strong></span>"
                    f"<span>avg eng <strong>{_avg_eng:.0f}</strong></span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
                _nudge_display = NUDGE_LABELS.get(_nudge_key, _nudge_key)
                st.markdown(
                    f"<div style='font-size:11px;font-weight:600;color:{_scol};"
                    f"margin-bottom:3px'>→ {_nudge_display}</div>",
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f"<div style='font-size:10px;color:var(--color-text-secondary);"
                    f"line-height:1.4;margin-bottom:8px;border-left:2px solid {_scol};"
                    f"padding-left:6px'>{_rationale}</div>",
                    unsafe_allow_html=True,
                )

                if _n == 0:
                    st.markdown(
                        "<div style='font-size:12px;color:var(--color-text-tertiary);"
                        "padding:8px 0'>No accounts in this group</div>",
                        unsafe_allow_html=True,
                    )
                    continue

                for _, _row in _col_df.iterrows():
                    _gmva  = _row.get("gmv_total_6m", 0)
                    _ord   = int(_row.get("orders_6m", 0))
                    _eng   = _row.get("engagement_score", 0)
                    _pdp   = int(_row.get("pdp_views_6m", 0))
                    _nudge = NUDGE_LABELS.get(_row.get("nudge_feature", ""), "")

                    st.markdown(
                        f"<div style='border:0.5px solid var(--color-border-tertiary);"
                        f"border-left:3px solid {_scol};border-radius:6px;"
                        f"padding:8px 10px;margin-bottom:6px;"
                        f"background:var(--color-background-primary)'>"
                        f"<div style='font-weight:500;font-size:13px'>"
                        f"{_row['account_id']} · {_row.get('country','')}</div>"
                        f"<div style='font-size:11px;color:var(--color-text-secondary);margin-top:4px;"
                        f"display:flex;gap:14px;flex-wrap:wrap'>"
                        f"<span>£{_gmva:,.0f} GMV</span>"
                        f"<span>{_ord} orders</span>"
                        f"<span>{_pdp} PDP views</span>"
                        f"<span>eng {_eng:.0f}</span>"
                        f"</div>"
                        + (f"<div style='font-size:10px;font-weight:600;color:{_scol};"
                           f"margin-top:4px'>→ {_nudge}</div>" if _nudge else "")
                        + f"</div>",
                        unsafe_allow_html=True,
                    )

    # ── Message Drafts ─────────────────────────────────────────────────────
    st.divider()
    st.header("✉️ Message Drafts")
    st.caption(
        "Each row is tagged with the account's category, journey stage (broker) or engagement method "
        "(self-serve), and touch number. Approve and push to SendGrid when ready."
    )

    f1, f2, f3 = st.columns(3)
    with f1:
        seg_filter = st.multiselect(
            "Category", options=sorted(df["segment"].unique()),
            default=sorted(df["segment"].unique()), key="draft_seg_filter",
        )
    with f2:
        tier_options = sorted(df["tier"].unique()) if "tier" in df.columns else ["T1", "T2", "T3"]
        tier_filter = st.multiselect("Touch", options=tier_options, default=tier_options, key="draft_tier_filter")
    with f3:
        has_drafts_only = st.checkbox("Drafted only", value=True, key="draft_filter")

    mask = df["segment"].isin(seg_filter)
    if "tier" in df.columns:
        mask = mask & df["tier"].isin(tier_filter)
    if has_drafts_only and "msg_variant_a" in df.columns:
        mask = mask & (df["msg_variant_a"].fillna("") != "")
    view_df = df[mask].copy()

    st.caption(f"Showing **{len(view_df)}** accounts")

    view_df["Journey Stage"] = view_df.apply(_get_journey_context, axis=1)
    view_df["Engagement Method"] = view_df.apply(_get_engagement_method, axis=1)

    display_col_map = {
        "account_id": "Account ID", "segment": "Category",
        "tier": "Touch", "Journey Stage": "Journey Stage",
        "Engagement Method": "Engagement Method",
        "msg_variant_a": "Variant A", "msg_variant_b": "Variant B",
    }
    display_df = view_df[
        [c for c in display_col_map.keys() if c in view_df.columns]
    ].copy().rename(columns=display_col_map)
    display_df.insert(0, "Push?", False)

    edited = st.data_editor(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Push?":             st.column_config.CheckboxColumn("Push?", default=False),
            "Variant A":         st.column_config.TextColumn("Variant A", width="large"),
            "Variant B":         st.column_config.TextColumn("Variant B", width="large"),
            "Journey Stage":     st.column_config.TextColumn("Journey Stage", width="medium"),
            "Engagement Method": st.column_config.TextColumn("Engagement Method", width="medium"),
        },
        disabled=[c for c in display_df.columns if c != "Push?"],
        key="drafts_editor",
    )

    btn1, btn2, btn3, _ = st.columns([1, 1, 1, 4])
    with btn1:
        push_all_t1 = st.button("🚀 Push all T1", type="primary")
    with btn2:
        push_selected = st.button("📤 Push selected")
    with btn3:
        variant_choice = st.radio("Variant", ["A", "B"], horizontal=True, label_visibility="collapsed")

    if push_all_t1 or push_selected:
        if push_all_t1:
            target_ids = view_df[view_df["tier"] == "T1"]["account_id"].tolist()
            label = "T1"
        else:
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
    # SECTION 5: MESSAGE TEMPLATES
    # ─────────────────────────────────────────────────────────────────────────
    st.divider()
    st.header("✏️ Message Templates")
    st.caption(
        "Edit the A/B variants for each stage and pathway. "
        "Save, then click **Redraft messages** to regenerate with the updated angles."
    )

    _variants = load_variants()
    _changed = False

    _active_positions = set(
        df[df["segment"] == "BROKER_RELIANT"]["journey_position"].dropna().unique()
    )
    _broker_stages = _variants.get("broker_stages", {})
    # Only draft messages for the highest-priority stages — Building Habit (nearly_graduated) doesn't need outreach
    _MESSAGING_STAGES = {"not_started", "stalled", "moving"}
    _active_broker = [p for p in JOURNEY_ORDER if p in _active_positions and p in _broker_stages and p in _MESSAGING_STAGES]

    _ss_segs = ["TRUE_HEADROOM", "PASSIVE_BUYER", "SELF_SERVE_OTHER"]
    _active_nudges = set(
        df[df["segment"].isin(_ss_segs)]["nudge_feature"].dropna().unique()
    )
    _ss_pathways = _variants.get("ss_pathways", {})
    _active_ss = [p for p in _ss_pathways if p in _active_nudges]

    _tmpl_tabs = []
    if _active_broker:
        _tmpl_tabs.append("🟡 Broker stages")
    if _active_ss:
        _tmpl_tabs.append("🟢 Self-serve pathways")

    if _tmpl_tabs:
        _t = st.tabs(_tmpl_tabs)
        _tab_idx = 0

        if _active_broker:
            with _t[_tab_idx]:
                _tab_idx += 1
                for pos in _active_broker:
                    s = _broker_stages[pos]
                    st.markdown(
                        f"**{s['stage_name']}** · _{s['criteria']}_ · "
                        f"<span style='color:var(--color-text-secondary);font-size:12px'>{s['behaviour']}</span>",
                        unsafe_allow_html=True,
                    )
                    c1, c2 = st.columns(2)
                    new_a = c1.text_area(
                        "Variant A", value=s["variant_a"],
                        height=90, key=f"broker_a_{pos}",
                    )
                    new_b = c2.text_area(
                        "Variant B", value=s["variant_b"],
                        height=90, key=f"broker_b_{pos}",
                    )
                    if new_a != s["variant_a"] or new_b != s["variant_b"]:
                        _variants["broker_stages"][pos]["variant_a"] = new_a
                        _variants["broker_stages"][pos]["variant_b"] = new_b
                        _changed = True
                    st.divider()

        if _active_ss:
            with _t[_tab_idx]:
                for pathway in _active_ss:
                    p = _ss_pathways[pathway]
                    st.markdown(
                        f"**{p['pathway_name']} pathway** · "
                        f"<span style='color:var(--color-text-secondary);font-size:12px'>Trigger: {p['trigger']}</span>",
                        unsafe_allow_html=True,
                    )
                    c1, c2 = st.columns(2)
                    new_a = c1.text_area(
                        "Variant A", value=p["variant_a"],
                        height=90, key=f"ss_a_{pathway}",
                    )
                    new_b = c2.text_area(
                        "Variant B", value=p["variant_b"],
                        height=90, key=f"ss_b_{pathway}",
                    )
                    if new_a != p["variant_a"] or new_b != p["variant_b"]:
                        _variants["ss_pathways"][pathway]["variant_a"] = new_a
                        _variants["ss_pathways"][pathway]["variant_b"] = new_b
                        _changed = True
                    st.divider()

    _sv_col, _rd_col, _ = st.columns([1, 1, 5])
    with _sv_col:
        if st.button("💾 Save variants", disabled=not _changed):
            save_variants(_variants)
            st.success("Saved.")
    with _rd_col:
        if st.button("🔄 Redraft messages"):
            with st.spinner("Redrafting with updated variants…"):
                from agents.drafter import draft_messages
                st.session_state.df = draft_messages(
                    st.session_state.df,
                    variants=load_variants(),
                )
            st.success("Messages redrafted.")
            st.rerun()

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 6: SENDGRID STATUS
    # ─────────────────────────────────────────────────────────────────────────
    if st.session_state.sg_status is not None:
        st.divider()
        st.header("📡 SendGrid Status")
        s = st.session_state.sg_status
        detail = s.get("detail", "")

        if detail:
            st.warning(detail)
        else:
            c1, c2, c3 = st.columns(3)
            c1.metric("✅ Pushed", s.get("queued", 0))
            c2.metric("⏸ Held (no email)", s.get("skipped", 0))
            c3.metric("❌ Errors", len(s.get("errors", [])))

        if s.get("errors"):
            with st.expander("Error details"):
                st.dataframe(pd.DataFrame(s["errors"]), use_container_width=True, hide_index=True)

        st.caption(
            f"Last push: **{s.get('label', '')}** accounts · "
            f"{datetime.now().strftime('%H:%M:%S')}"
        )

# ── footer ────────────────────────────────────────────────────────────────────
st.markdown("---")
st.caption("Fleek Retention Pipeline · drafts only · nothing sends automatically")
