"""
Write two-tab (+ Plays tab) Excel workbook to outputs/fleek_retention_actions.xlsx.

Tab 1 — Priority Actions: ranked list with next-best-action per account.
Tab 2 — Full Portfolio:   all accounts with all pipeline fields.
Tab 3 — Plays:            broker migration and self-serve nudge accounts with
                          rung, touch due, and both message variants (A/B).
"""
import os
from datetime import datetime

import pandas as pd
import xlsxwriter


OUTPUT_PATH = "outputs/fleek_retention_actions.xlsx"

PRIORITY_COLS = [
    "priority_rank", "account_id", "segment", "at_risk", "play", "rung",
    "nudge_feature", "gmv_total_6m", "broker_reliance_pct",
    "app_active_days_6m", "pdp_views_6m", "engagement_score",
    "ownership", "buyer_persona", "country",
    "msg_variant_a", "msg_variant_b",
]

FULL_COLS = [
    "priority_rank", "account_id", "segment", "at_risk", "play", "rung",
    "nudge_feature", "ownership", "buyer_persona", "region", "country",
    "account_status", "tenure_months", "gmv_total_6m", "orders_6m",
    "gmv_sep", "gmv_oct", "gmv_nov", "gmv_dec", "gmv_jan", "gmv_feb",
    "gmv_trend_pct", "broker_reliance_pct", "manual_orders", "self_serve_orders",
    "app_active_days_6m", "pdp_views_6m", "make_an_offer_6m",
    "chat_threads", "video_call_requests", "handpick_orders",
    "bundle_orders", "bundle_gmv_share_pct", "engagement_score", "ss_ratio",
    "msg_variant_a", "msg_variant_b",
]

PLAYS_COLS = [
    "priority_rank", "account_id", "segment", "play", "rung",
    "nudge_feature", "gmv_total_6m", "broker_reliance_pct", "ss_ratio",
    "app_active_days_6m", "pdp_views_6m",
    "touch_number", "touch_due",
    "msg_variant_a", "msg_variant_b",
]


def _safe_cols(df: pd.DataFrame, cols: list) -> list:
    return [c for c in cols if c in df.columns]


def write_excel(df: pd.DataFrame) -> str:
    os.makedirs("outputs", exist_ok=True)

    # Add touch metadata
    df = df.copy()
    if "touch_number" not in df.columns:
        df["touch_number"] = 1
    if "touch_due" not in df.columns:
        df["touch_due"] = datetime.today().strftime("%Y-%m-%d")
    if "msg_variant_a" not in df.columns:
        df["msg_variant_a"] = ""
    if "msg_variant_b" not in df.columns:
        df["msg_variant_b"] = ""

    writer = pd.ExcelWriter(OUTPUT_PATH, engine="xlsxwriter")
    wb = writer.book

    # Formats
    header_fmt = wb.add_format({
        "bold": True, "bg_color": "#1A1A2E", "font_color": "#FFFFFF",
        "border": 1, "text_wrap": True, "valign": "vcenter",
    })
    at_risk_fmt = wb.add_format({"bg_color": "#FFE0E0", "border": 1})
    broker_fmt = wb.add_format({"bg_color": "#FFF3CD", "border": 1})
    ss_fmt = wb.add_format({"bg_color": "#D4EDDA", "border": 1})
    normal_fmt = wb.add_format({"border": 1, "text_wrap": False})
    wrap_fmt = wb.add_format({"border": 1, "text_wrap": True, "valign": "top"})

    def write_sheet(sheet_name: str, data: pd.DataFrame, cols: list) -> None:
        cols = _safe_cols(data, cols)
        data = data[cols].copy()
        data.to_excel(writer, sheet_name=sheet_name, index=False, startrow=1, header=False)
        ws = writer.sheets[sheet_name]
        ws.set_row(0, 30, header_fmt)

        for col_idx, col_name in enumerate(cols):
            ws.write(0, col_idx, col_name, header_fmt)
            if "msg_variant" in col_name:
                ws.set_column(col_idx, col_idx, 60, wrap_fmt)
            elif col_name in ("account_id", "segment", "play", "rung", "nudge_feature"):
                ws.set_column(col_idx, col_idx, 20)
            else:
                ws.set_column(col_idx, col_idx, 14)

        # Colour rows by segment
        seg_col = cols.index("segment") if "segment" in cols else None
        risk_col = cols.index("at_risk") if "at_risk" in cols else None
        for row_idx, (_, row) in enumerate(data.iterrows(), start=1):
            seg = row.get("segment", "")
            risk = bool(row.get("at_risk", False))
            if risk:
                row_fmt = at_risk_fmt
            elif seg == "BROKER_RELIANT":
                row_fmt = broker_fmt
            elif "SELF_SERVE" in str(seg):
                row_fmt = ss_fmt
            else:
                row_fmt = normal_fmt
            for col_idx, val in enumerate(row):
                ws.write(row_idx, col_idx, val, row_fmt)

        ws.freeze_panes(1, 0)

    # Tab 1: Priority Actions
    write_sheet("Priority Actions", df, PRIORITY_COLS)

    # Tab 2: Full Portfolio
    write_sheet("Full Portfolio", df, FULL_COLS)

    # Tab 3: Plays (broker + self-serve only)
    plays_df = df[df["play"].isin(["broker_migration", "self_serve_nudge"])].copy()
    write_sheet("Plays", plays_df, PLAYS_COLS)

    writer.close()
    return OUTPUT_PATH
