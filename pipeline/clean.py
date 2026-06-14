"""
Clean and deduplicate portfolio data.
Handles blanks, coerces types, merges Accounts + new_accounts.
Returns a single deduplicated DataFrame (last-seen row wins).
"""
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


def load_and_clean(portfolio_path: str, new_batch_path=None) -> pd.DataFrame:
    """Load portfolio Excel (Accounts tab + optional new batch), clean and deduplicate."""
    frames = []

    # Main portfolio — Accounts tab
    df_main = pd.read_excel(portfolio_path, sheet_name="Accounts")
    df_main["_source"] = "main"
    frames.append(df_main)

    # Optional explicit new batch file
    if new_batch_path:
        df_new = pd.read_excel(new_batch_path, sheet_name=0)
        df_new["_source"] = "new_batch_file"
        frames.append(df_new)

    df = pd.concat(frames, ignore_index=True)

    # Normalise column names
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

    # Drop rows with no account_id
    df = df[df["account_id"].notna()].copy()
    df["account_id"] = df["account_id"].astype(str).str.strip().str.upper()

    # Coerce numerics
    for col in NUMERIC_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # Coerce strings
    for col in STRING_COLS:
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str).str.strip()

    # Derived fields
    df["ownership_clean"] = df["ownership"].str.lower()
    df["is_account_managed"] = df["ownership_clean"].str.contains("account managed", na=False)

    total_orders = df["manual_orders"] + df["self_serve_orders"]
    # Recalculate broker_reliance_pct from raw order counts where possible;
    # fall back to reported value when order counts are both zero
    recalc_mask = total_orders > 0
    df["broker_reliance_pct"] = df["broker_reliance_pct"].astype(float)
    df.loc[recalc_mask, "broker_reliance_pct"] = (
        df.loc[recalc_mask, "manual_orders"] / total_orders[recalc_mask] * 100
    )

    # Engagement composite (for self-serve prioritisation)
    df["engagement_score"] = df["app_active_days_6m"] + df["pdp_views_6m"] / 10

    # Monthly GMV trend flag
    monthly = ["gmv_sep", "gmv_oct", "gmv_nov", "gmv_dec", "gmv_jan", "gmv_feb"]
    df["last_3m_gmv"] = df[["gmv_dec", "gmv_jan", "gmv_feb"]].sum(axis=1)
    df["first_3m_gmv"] = df[["gmv_sep", "gmv_oct", "gmv_nov"]].sum(axis=1)
    df["is_declining"] = (df["last_3m_gmv"] < df["first_3m_gmv"] * 0.7) & (df["first_3m_gmv"] > 0)

    # Deduplicate: last row wins (new batch rows placed after main)
    df = df.drop_duplicates(subset=["account_id"], keep="last").reset_index(drop=True)

    return df


def load_new_accounts_tab(portfolio_path: str) -> pd.DataFrame:
    """Load the new_accounts tab from the main portfolio file."""
    try:
        df = pd.read_excel(portfolio_path, sheet_name="new_accounts")
        df["_source"] = "new_accounts_tab"
        return df
    except Exception:
        return pd.DataFrame()
