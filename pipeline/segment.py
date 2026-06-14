"""
Classify each account into one of four segments:
  BROKER_RELIANT      — AM-owned, high broker reliance, low self-serve activity
  HEALTHY_AM          — AM-owned, already buying via product
  SELF_SERVE_HEADROOM — Self-serve with growth potential
  SELF_SERVE_MATURE   — Self-serve, high activity, near ceiling

AT_RISK flag is set on HEALTHY_AM accounts that are in GMV decline.
"""
import pandas as pd

# Thresholds (tuneable)
BROKER_RELIANCE_HIGH = 50       # % manual orders
APP_DAYS_LOW = 10               # 6-month app active days
PDP_VIEWS_LOW = 20              # 6-month PDP views
OFFER_LOW = 3                   # make-an-offer events
SELF_SERVE_HEADROOM_GMV = 5000  # GBP — below this = headroom
SELF_SERVE_MATURE_ENGAGEMENT = 30  # app days threshold for mature


def segment(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    broker_reliant = (
        df["is_account_managed"]
        & (df["broker_reliance_pct"] >= BROKER_RELIANCE_HIGH)
        & (
            (df["app_active_days_6m"] <= APP_DAYS_LOW)
            | (df["pdp_views_6m"] <= PDP_VIEWS_LOW)
        )
    )

    healthy_am = (
        df["is_account_managed"]
        & ~broker_reliant
    )

    self_serve = ~df["is_account_managed"]

    self_serve_headroom = self_serve & (
        (df["gmv_total_6m"] < SELF_SERVE_HEADROOM_GMV)
        | (df["pdp_views_6m"] > PDP_VIEWS_LOW)   # high intent, room to grow
    )

    self_serve_mature = self_serve & ~self_serve_headroom

    def assign(row_idx):
        if broker_reliant.iloc[row_idx]:
            return "BROKER_RELIANT"
        if healthy_am.iloc[row_idx]:
            return "HEALTHY_AM"
        if self_serve_headroom.iloc[row_idx]:
            return "SELF_SERVE_HEADROOM"
        return "SELF_SERVE_MATURE"

    df["segment"] = [assign(i) for i in range(len(df))]

    # AT_RISK: HEALTHY_AM in GMV decline
    df["at_risk"] = (df["segment"] == "HEALTHY_AM") & df["is_declining"]

    return df
