"""
Classify each account into one of five segments:
  BROKER_RELIANT    — AM-owned, high broker reliance, low self-serve activity
  HEALTHY_AM        — AM-owned, already buying via product
  TRUE_HEADROOM     — Self-serve: high engagement, low GMV (best upsell opportunity)
  PASSIVE_BUYER     — Self-serve: high GMV, low engagement (churn risk)
  SELF_SERVE_OTHER  — Self-serve: all other accounts (Already There or Dormant)

Self-serve quadrant splits on median engagement score and median GMV within
the self-serve population (computed dynamically per upload).
"""
import pandas as pd

# Thresholds (tuneable)
BROKER_RELIANCE_HIGH = 50  # % manual orders
APP_DAYS_LOW = 10          # 6-month app active days
PDP_VIEWS_LOW = 20         # 6-month PDP views


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

    healthy_am = df["is_account_managed"] & ~broker_reliant

    self_serve = ~df["is_account_managed"]

    # Dynamic medians computed from self-serve population
    ss_df = df[self_serve]
    eng_median = ss_df["engagement_score"].median() if len(ss_df) > 0 else 0
    gmv_median = ss_df["gmv_total_6m"].median() if len(ss_df) > 0 else 0

    high_eng = self_serve & (df["engagement_score"] >= eng_median)
    low_eng  = self_serve & (df["engagement_score"] <  eng_median)
    high_gmv = self_serve & (df["gmv_total_6m"]     >= gmv_median)
    low_gmv  = self_serve & (df["gmv_total_6m"]     <  gmv_median)

    true_headroom = high_eng & low_gmv   # high intent, room to grow
    passive_buyer = low_eng  & high_gmv  # high value, low stickiness
    ss_other      = self_serve & ~true_headroom & ~passive_buyer

    def assign(row_idx):
        if broker_reliant.iloc[row_idx]:  return "BROKER_RELIANT"
        if healthy_am.iloc[row_idx]:      return "HEALTHY_AM"
        if true_headroom.iloc[row_idx]:   return "TRUE_HEADROOM"
        if passive_buyer.iloc[row_idx]:   return "PASSIVE_BUYER"
        return "SELF_SERVE_OTHER"

    df["segment"] = [assign(i) for i in range(len(df))]

    # Health status for HEALTHY_AM accounts based on GMV trend
    # Growing: last 3m GMV > first 3m GMV by 10%+
    # Declining: last 3m GMV < first 3m GMV by 30%+
    # Stable: everything in between
    def _health_status(row):
        if row["segment"] != "HEALTHY_AM":
            return None
        first = row.get("first_3m_gmv", 0)
        last  = row.get("last_3m_gmv", 0)
        eng   = row.get("engagement_score", 0)
        app_days = row.get("app_active_days_6m", 0)

        if first == 0:
            return "stable"

        gmv_change = (last - first) / first  # positive = growth

        # Growing: GMV up >10%
        if gmv_change > 0.10:
            return "growing"

        # Declining: requires a STRONG pattern — both revenue AND engagement
        # must be deteriorating.  A single bad GMV quarter alone = stable.
        # Criteria: GMV down >20% from first half to second half
        #           AND engagement is genuinely low (app barely used)
        low_engagement = (app_days < 5) or (eng < 10)
        if gmv_change < -0.20 and low_engagement:
            return "declining"

        return "stable"

    df["health_status"] = df.apply(_health_status, axis=1)

    return df
