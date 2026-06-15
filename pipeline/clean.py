"""
Clean and deduplicate portfolio data.
Handles blanks, coerces types, merges Accounts + new_accounts.
Returns (DataFrame, stats_dict).

Also handles versioned saves and merging into a master portfolio file.
"""
import os
from datetime import datetime

import pandas as pd


NUMERIC_COLS = [
    "tenure_months", "gmv_total_6m", "orders_6m",
    "gmv_sep", "gmv_oct", "gmv_nov", "gmv_dec", "gmv_jan", "gmv_feb",
    "gmv_trend_pct", "broker_reliance_pct", "manual_orders", "self_serve_orders",
    "app_active_days_6m", "pdp_views_6m", "make_an_offer_6m",
    "chat_threads", "video_call_requests", "handpick_orders",
    "bundle_orders", "bundle_gmv_share_pct",
]

STRING_COLS = [
    "account_id", "ownership", "buyer_persona", "region",
    "country", "account_status",
]

MASTER_PATH = "data/master_portfolio.xlsx"
VERSIONS_DIR = "data/versions"


def save_versioned_upload(file_bytes: bytes, filename: str) -> str:
    """Save a versioned copy of an uploaded file. Returns the saved path."""
    os.makedirs(VERSIONS_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = os.path.splitext(os.path.basename(filename))[0]
    dest = os.path.join(VERSIONS_DIR, f"{base}_{ts}.xlsx")
    with open(dest, "wb") as f:
        f.write(file_bytes)
    return dest


def merge_into_master(df: pd.DataFrame) -> int:
    """
    Append/update df into the master portfolio file (last seen wins).
    Returns number of net new accounts added.
    """
    os.makedirs("data", exist_ok=True)

    # Only persist core columns (drop internal derived fields)
    drop_cols = [c for c in ["_source", "ownership_clean", "is_account_managed",
                              "engagement_score", "last_3m_gmv", "first_3m_gmv",
                              "is_declining", "ss_ratio"] if c in df.columns]
    export_df = df.drop(columns=drop_cols, errors="ignore")

    if os.path.exists(MASTER_PATH):
        try:
            master = pd.read_excel(MASTER_PATH, sheet_name="Accounts")
            pre_count = master["account_id"].nunique()
            combined = pd.concat([master, export_df], ignore_index=True)
            combined = combined.drop_duplicates(subset=["account_id"], keep="last")
            new_accounts = combined["account_id"].nunique() - pre_count
        except Exception:
            combined = export_df.copy()
            new_accounts = len(export_df)
    else:
        combined = export_df.copy()
        new_accounts = len(export_df)

    with pd.ExcelWriter(MASTER_PATH, engine="xlsxwriter") as writer:
        combined.to_excel(writer, sheet_name="Accounts", index=False)

    return max(new_accounts, 0)


def load_and_clean(portfolio_path: str, new_batch_path=None) -> tuple:
    """
    Load portfolio Excel (Accounts tab + optional new batch), clean and deduplicate.
    Returns (df, stats) where stats is a dict describing what was done.
    """
    stats = {}
    frames = []

    # Main portfolio — Accounts tab
    df_main = pd.read_excel(portfolio_path, sheet_name="Accounts")
    df_main["_source"] = "main"
    frames.append(df_main)
    stats["accounts_loaded"] = len(df_main)
    stats["source_file"] = os.path.basename(portfolio_path)

    # Auto-detect new_accounts tab in the same file
    try:
        df_auto_new = pd.read_excel(portfolio_path, sheet_name="new_accounts")
        df_auto_new["_source"] = "new_accounts_tab"
        frames.append(df_auto_new)
        stats["new_accounts_tab_loaded"] = len(df_auto_new)
    except Exception:
        stats["new_accounts_tab_loaded"] = 0

    # Optional explicit new batch file
    if new_batch_path:
        df_new = pd.read_excel(new_batch_path, sheet_name=0)
        df_new["_source"] = "new_batch_file"
        frames.append(df_new)
        stats["new_batch_loaded"] = len(df_new)

    df = pd.concat(frames, ignore_index=True)
    stats["total_rows_before_dedup"] = len(df)

    # Normalise column names
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

    # Drop rows with no account_id
    no_id = int(df["account_id"].isna().sum())
    df = df[df["account_id"].notna()].copy()
    stats["rows_dropped_no_id"] = no_id

    df["account_id"] = df["account_id"].astype(str).str.strip().str.upper()

    # Coerce numerics — track gaps filled
    data_gaps = {}
    for col in NUMERIC_COLS:
        if col in df.columns:
            nulls = int(df[col].isna().sum())
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
            if nulls > 0:
                data_gaps[col] = nulls
    stats["data_gaps_filled"] = data_gaps
    stats["fields_with_gaps"] = len(data_gaps)
    stats["total_gap_cells"] = sum(data_gaps.values())

    # Coerce strings
    for col in STRING_COLS:
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str).str.strip()

    # Derived fields
    df["ownership_clean"] = df["ownership"].str.lower()
    df["is_account_managed"] = df["ownership_clean"].str.contains("account managed", na=False)

    total_orders = df["manual_orders"] + df["self_serve_orders"]
    recalc_mask = total_orders > 0
    df["broker_reliance_pct"] = df["broker_reliance_pct"].astype(float)
    df.loc[recalc_mask, "broker_reliance_pct"] = (
        df.loc[recalc_mask, "manual_orders"] / total_orders[recalc_mask] * 100
    )

    # Engagement composite
    df["engagement_score"] = df["app_active_days_6m"] + df["pdp_views_6m"] / 10

    # Self-serve ratio (used by prioritise and plays)
    total_orders = df["manual_orders"] + df["self_serve_orders"]
    df["ss_ratio"] = (
        df["self_serve_orders"] / total_orders.replace(0, 1)
    ).clip(0, 1)

    # Monthly GMV trend
    df["last_3m_gmv"] = df[["gmv_dec", "gmv_jan", "gmv_feb"]].sum(axis=1)
    df["first_3m_gmv"] = df[["gmv_sep", "gmv_oct", "gmv_nov"]].sum(axis=1)
    df["is_declining"] = (df["last_3m_gmv"] < df["first_3m_gmv"] * 0.7) & (df["first_3m_gmv"] > 0)

    # Deduplicate: last row wins
    pre_dedup = len(df)
    df = df.drop_duplicates(subset=["account_id"], keep="last").reset_index(drop=True)
    stats["duplicates_removed"] = pre_dedup - len(df)
    stats["accounts_after_clean"] = len(df)

    # Ownership split
    stats["account_managed_count"] = int(df["is_account_managed"].sum())
    stats["self_serve_count"] = int((~df["is_account_managed"]).sum())

    return df, stats


def load_new_accounts_tab(portfolio_path: str) -> pd.DataFrame:
    """Load the new_accounts tab from the main portfolio file."""
    try:
        df = pd.read_excel(portfolio_path, sheet_name="new_accounts")
        df["_source"] = "new_accounts_tab"
        return df
    except Exception:
        return pd.DataFrame()
