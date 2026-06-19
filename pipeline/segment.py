"""
Classify each account into one of three segments:

  HEALTHY_AM     — AM-owned, already self-serving ≥70% of orders.
                   Not a migration burden — no archetype profiling needed.

  BROKER_RELIANT — AM-owned, self-serve ratio < 70%.
                   Needs migration support — receives one of five archetypes
                   (ENTRENCHED_BROKER, HABITUAL_BROKER, PLATFORM_CURIOUS,
                    DUAL_CHANNEL, MID_MIGRATION) assigned in plays.py.

  SELF_SERVE     — Not account-managed.
                   Receives one of four archetypes based on intent/GMV signals
                   (SS_ACTIVE_BUYER, SS_HIGH_INTENT, SS_HIGH_SPENDER_LOW_ENG,
                    SS_LOW_ENGAGEMENT) assigned in plays.py.
"""
import pandas as pd

# Healthy AM threshold: accounts self-serving 70%+ of their orders need no migration push
HEALTHY_AM_SS_RATIO = 0.70


def segment(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # Compute ss_ratio for all AM accounts
    total_orders = (df["manual_orders"] + df["self_serve_orders"]).replace(0, 1)
    df["ss_ratio"] = (df["self_serve_orders"] / total_orders).clip(0, 1)

    # HEALTHY_AM: account-managed AND already ≥70% self-serve
    healthy_am = df["is_account_managed"] & (df["ss_ratio"] >= HEALTHY_AM_SS_RATIO)

    # BROKER_RELIANT: account-managed AND not yet at the healthy threshold
    broker_reliant = df["is_account_managed"] & ~healthy_am

    def assign(row_idx):
        if broker_reliant.iloc[row_idx]: return "BROKER_RELIANT"
        if healthy_am.iloc[row_idx]:     return "HEALTHY_AM"
        return "SELF_SERVE"

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
