"""
Write Excel workbooks to outputs/.

Tab 1 — Priority Actions: ranked list, all segments.
Tab 2 — Broker Managed:   detailed broker sheet with engagement summary + justification.
Tab 3 — Healthy AM:       AM account priority list.
Tab 4 — Self-Serve:       self-serve priority list.
Tab 5 — Full Portfolio:   all accounts, all fields.
Tab 6 — Plays:            broker + self-serve with message variants.
"""
import io
import os
from datetime import datetime

import pandas as pd
import xlsxwriter


OUTPUT_PATH = "outputs/fleek_retention_actions.xlsx"
VERSIONS_DIR = "outputs/versions"

PRIORITY_COLS = [
    "priority_rank", "account_id", "segment", "health_status", "play", "journey_position",
    "nudge_feature", "gmv_total_6m", "gmv_trend", "broker_reliance_pct",
    "app_active_days_6m", "pdp_views_6m", "engagement_score",
    "ownership", "buyer_persona", "country",
    "justification", "msg_variant_a", "msg_variant_b",
]

# Broker sheet — full detail per the brief
BROKER_COLS = [
    "seg_rank", "account_id", "country", "region",
    "broker_reliance_pct", "manual_orders", "self_serve_orders", "orders_6m", "ss_ratio",
    "gmv_total_6m", "gmv_trend",
    "gmv_sep", "gmv_oct", "gmv_nov", "gmv_dec", "gmv_jan", "gmv_feb",
    "app_active_days_6m", "pdp_views_6m", "make_an_offer_6m",
    "chat_threads", "video_call_requests", "bundle_orders",
    "engagement_summary", "journey_position", "justification",
]

HEALTHY_AM_COLS = [
    "seg_rank", "account_id", "country", "region", "health_status",
    "gmv_total_6m", "gmv_trend", "orders_6m",
    "app_active_days_6m", "pdp_views_6m", "engagement_score",
    "engagement_summary", "justification",
]

# Simplified self-serve columns per the brief:
# account_id, country, self_serve_orders, engagement_score, pdp_views, app_days,
# GMV last month, gmv_total_6m, gmv_trend, then remaining engagement features
SELF_SERVE_COLS = [
    "seg_rank", "account_id", "country",
    "self_serve_orders",
    "engagement_score", "pdp_views_6m", "app_active_days_6m",
    "gmv_feb",        # last month GMV
    "gmv_total_6m", "gmv_trend",
    "make_an_offer_6m", "chat_threads", "video_call_requests",
    "bundle_orders", "handpick_orders", "bundle_gmv_share_pct",
    "journey_position", "justification",
]

FULL_COLS = [
    "priority_rank", "account_id", "segment", "health_status", "play", "journey_position",
    "nudge_feature", "ownership", "buyer_persona", "region", "country",
    "account_status", "tenure_months", "gmv_total_6m", "gmv_trend", "orders_6m",
    "gmv_sep", "gmv_oct", "gmv_nov", "gmv_dec", "gmv_jan", "gmv_feb",
    "gmv_trend_pct", "broker_reliance_pct", "manual_orders", "self_serve_orders",
    "app_active_days_6m", "pdp_views_6m", "make_an_offer_6m",
    "chat_threads", "video_call_requests", "handpick_orders",
    "bundle_orders", "bundle_gmv_share_pct", "engagement_score", "ss_ratio",
    "engagement_summary", "justification", "msg_variant_a", "msg_variant_b",
]

PLAYS_COLS = [
    "priority_rank", "account_id", "segment", "play", "journey_position",
    "nudge_feature", "gmv_total_6m", "broker_reliance_pct", "ss_ratio",
    "app_active_days_6m", "pdp_views_6m",
    "touch_number", "touch_due",
    "msg_variant_a", "msg_variant_b",
]

# Cleaned data export — segment and justification first
CLEANED_COLS_FIRST = [
    "account_id", "segment", "health_status", "justification",
    "ownership", "buyer_persona", "region", "country", "account_status", "tenure_months",
    "gmv_total_6m", "gmv_trend", "orders_6m",
    "gmv_sep", "gmv_oct", "gmv_nov", "gmv_dec", "gmv_jan", "gmv_feb",
    "broker_reliance_pct", "manual_orders", "self_serve_orders", "ss_ratio",
    "app_active_days_6m", "pdp_views_6m", "make_an_offer_6m",
    "chat_threads", "video_call_requests", "handpick_orders",
    "bundle_orders", "bundle_gmv_share_pct", "engagement_score", "engagement_summary",
]


def _safe_cols(df: pd.DataFrame, cols: list) -> list:
    return [c for c in cols if c in df.columns]


def _write_workbook(df: pd.DataFrame, path: str) -> None:
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else "outputs", exist_ok=True)

    df = df.copy()
    if "touch_number" not in df.columns:
        df["touch_number"] = 1
    if "touch_due" not in df.columns:
        df["touch_due"] = datetime.today().strftime("%Y-%m-%d")
    if "msg_variant_a" not in df.columns:
        df["msg_variant_a"] = ""
    if "msg_variant_b" not in df.columns:
        df["msg_variant_b"] = ""

    writer = pd.ExcelWriter(path, engine="xlsxwriter")
    wb = writer.book

    # Formats
    header_fmt = wb.add_format({
        "bold": True, "bg_color": "#1A1A2E", "font_color": "#FFFFFF",
        "border": 1, "text_wrap": True, "valign": "vcenter",
    })
    broker_fmt  = wb.add_format({"bg_color": "#FFF3CD", "border": 1})
    ss_fmt      = wb.add_format({"bg_color": "#D4EDDA", "border": 1})
    am_fmt      = wb.add_format({"bg_color": "#D1ECF1", "border": 1})
    normal_fmt  = wb.add_format({"border": 1})
    wrap_fmt    = wb.add_format({"border": 1, "text_wrap": True, "valign": "top"})

    def _row_fmt(seg):
        if seg == "BROKER_RELIANT":                           return broker_fmt
        if seg in ("TRUE_HEADROOM", "PASSIVE_BUYER",
                   "SELF_SERVE_OTHER", "SELF_SERVE_HEADROOM",
                   "SELF_SERVE_MATURE"):                      return ss_fmt
        if seg == "HEALTHY_AM":                               return am_fmt
        return normal_fmt

    def write_sheet(sheet_name: str, data: pd.DataFrame, cols: list,
                    fixed_seg: str = None) -> None:
        cols = _safe_cols(data, cols)
        data = data[cols].copy()
        data.to_excel(writer, sheet_name=sheet_name, index=False, startrow=1, header=False)
        ws = writer.sheets[sheet_name]
        ws.set_row(0, 30)

        for col_idx, col_name in enumerate(cols):
            ws.write(0, col_idx, col_name, header_fmt)
            if col_name in ("justification", "engagement_summary", "msg_variant_a", "msg_variant_b"):
                ws.set_column(col_idx, col_idx, 65, wrap_fmt)
            elif col_name in ("account_id", "segment", "journey_position", "nudge_feature", "health_status"):
                ws.set_column(col_idx, col_idx, 20)
            elif col_name in ("country", "region", "buyer_persona", "gmv_trend"):
                ws.set_column(col_idx, col_idx, 14)
            else:
                ws.set_column(col_idx, col_idx, 12)

        for row_idx, (_, row) in enumerate(data.iterrows(), start=1):
            seg = fixed_seg or row.get("segment", "")
            fmt = _row_fmt(seg)
            for col_idx, val in enumerate(row):
                ws.write(row_idx, col_idx, val, fmt)

        ws.freeze_panes(1, 0)

    # Tab 1 — Priority Actions (all segments)
    write_sheet("Priority Actions", df, PRIORITY_COLS)

    # Tab 2 — Broker Managed (detailed)
    broker_df = df[df["segment"] == "BROKER_RELIANT"].copy()
    write_sheet("Broker Managed", broker_df, BROKER_COLS, fixed_seg="BROKER_RELIANT")

    # Tab 3 — Healthy AM
    am_df = df[df["segment"] == "HEALTHY_AM"].copy()
    write_sheet("Healthy AM", am_df, HEALTHY_AM_COLS, fixed_seg="HEALTHY_AM")

    # Tab 4b — True Headroom (high engagement, low spend)
    th_df = df[df["segment"] == "TRUE_HEADROOM"].copy()
    write_sheet("True Headroom", th_df, SELF_SERVE_COLS, fixed_seg="TRUE_HEADROOM")

    # Tab 4c — Passive Buyer (high GMV, low engagement)
    pb_df = df[df["segment"] == "PASSIVE_BUYER"].copy()
    write_sheet("Passive Buyer", pb_df, SELF_SERVE_COLS, fixed_seg="PASSIVE_BUYER")

    # Tab 6 — Full Portfolio
    write_sheet("Full Portfolio", df, FULL_COLS)

    # Tab 7 — Plays
    plays_df = df[df["play"].isin(["broker_migration", "self_serve_nudge"])].copy()
    write_sheet("Plays", plays_df, PLAYS_COLS)

    writer.close()


def write_excel(df: pd.DataFrame) -> str:
    """Write main output and a versioned copy. Returns the main output path."""
    os.makedirs("outputs", exist_ok=True)
    os.makedirs(VERSIONS_DIR, exist_ok=True)
    _write_workbook(df, OUTPUT_PATH)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    _write_workbook(df, os.path.join(VERSIONS_DIR, f"fleek_retention_{ts}.xlsx"))
    return OUTPUT_PATH


def get_excel_bytes(df: pd.DataFrame) -> bytes:
    write_excel(df)
    with open(OUTPUT_PATH, "rb") as f:
        return f.read()


def get_cleaned_excel_bytes(df: pd.DataFrame) -> bytes:
    """Cleaned data download — segment and justification columns first."""
    cols = _safe_cols(df, CLEANED_COLS_FIRST)
    # append any remaining columns not already listed
    extra = [c for c in df.columns if c not in cols and not c.startswith("_")]
    cols = cols + extra
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="xlsxwriter") as writer:
        df[cols].to_excel(writer, sheet_name="Cleaned Portfolio", index=False)
    return out.getvalue()
