"""
Assign a play, broker_archetype, journey_position, and nudge_feature to each account.

Broker archetypes — derived from order frequency, GMV consistency, broker reliance,
and platform engagement. Each archetype has a distinct risk profile and migration play.

  BROKER_ANCHORED       High GMV + high frequency + high reliance + low engagement.
                        Highest-value accounts with no platform curiosity.
                        Risk: pushing migration disrupts embedded relationship → churn.
                        Play: protect relationship; introduce platform gently before any ask.

  CROSSOVER_READY       High GMV + high frequency + high reliance + good engagement.
                        Already using the platform alongside the broker.
                        Risk: low — they're signalling openness.
                        Play: push first self-serve order now.

  PLATFORM_EXPLORER     High reliance + good engagement + lower volume.
                        Curious about the platform but haven't committed.
                        Risk: moderate — confidence is building, don't rush it.
                        Play: unblock friction; video call or direct outreach to convert intent.

  CONSISTENT_DEPENDENT  Low-to-mid frequency + very flat monthly GMV + moderate reliance.
                        Reliable, predictable buyer fully routed through AM.
                        Risk: low — small, stable account; easy win.
                        Play: low-risk self-serve ask; frame as convenience.

  ACTIVE_CONVERTER      Moderate reliance + already self-serving ~43% of orders.
                        Furthest along the migration journey — just needs closing.
                        Risk: low — behaviour is already changing.
                        Play: close the gap; reinforce self-serve habit.

Broker journey positions (ss_ratio-based, same as before):
  not_started      ss_ratio == 0
  stalled          0 < ss_ratio <= 0.25
  moving           0.25 < ss_ratio <= 0.40
  nearly_graduated ss_ratio > 0.40

Self-serve journey position — buyer journey stage:
  ss_browser        Low orders, no offers/chat yet
  ss_consideration  Actively making offers or chatting, low order volume
  ss_purchase       Regular ordering with decent engagement
  ss_reengagement   High past GMV but gone quiet

Self-serve nudge — journey-stage-driven:
  ss_browser        → video_call
  ss_consideration  → offer
  ss_purchase       → bundle
  ss_reengagement   → chat
"""
import numpy as np
import pandas as pd

_MONTHLY_GMV_COLS = ["gmv_sep", "gmv_oct", "gmv_nov", "gmv_dec", "gmv_jan", "gmv_feb"]


def _gmv_cv(row: pd.Series) -> float:
    vals = [row.get(c, 0) for c in _MONTHLY_GMV_COLS if row.get(c, 0) > 0]
    if len(vals) < 2:
        return 1.0
    m = np.mean(vals)
    return np.std(vals) / m if m > 0 else 1.0


_ENGAGEMENT_COMPOSITE_THRESHOLD = 12  # app_days*2 + pdp_views/5 + offers*3


def broker_archetype(row: pd.Series, freq_med: float, gmv_med: float,
                     rel_med: float, cv_med: float) -> str:
    """
    Classify a broker account into one of five archetypes.
    Engagement uses a composite score (app days + PDP views + offers) rather than
    app days alone, to avoid false precision from a single median split.

    Archetypes ordered least → most pushable:
      ENTRENCHED_BROKER   High GMV, high orders, high reliance, no platform engagement
      HABITUAL_BROKER     Consistent GMV, low frequency, moderate reliance — defined by flat ordering pattern
      PLATFORM_CURIOUS    High reliance, platform-engaged, lower volume — building confidence
      DUAL_CHANNEL        High GMV, high orders, high reliance, platform-engaged — ready to flip
      MID_MIGRATION       Already self-serving ~44% of orders — close the gap
    """
    high_gmv   = row.get("gmv_total_6m", 0)        >= gmv_med
    high_freq  = row.get("orders_6m", 0)            >= freq_med
    high_rel   = row.get("broker_reliance_pct", 0)  >= rel_med
    consistent = row.get("_gmv_cv", 1.0)            <= cv_med
    engaged    = row.get("_eng_composite", 0)       >= _ENGAGEMENT_COMPOSITE_THRESHOLD

    if high_gmv and high_freq and high_rel and not engaged:
        return "ENTRENCHED_BROKER"
    if high_gmv and high_freq and high_rel and engaged:
        return "DUAL_CHANNEL"
    if high_rel and engaged and not (high_gmv and high_freq):
        return "PLATFORM_CURIOUS"
    if consistent and not high_freq:
        return "HABITUAL_BROKER"
    return "MID_MIGRATION"


def _broker_journey_position(ss_ratio: float) -> str:
    if ss_ratio == 0:
        return "not_started"
    elif ss_ratio <= 0.25:
        return "stalled"
    elif ss_ratio <= 0.40:
        return "moving"
    else:
        return "nearly_graduated"


_MONTHLY_GMV_COLS_SS = ["gmv_sep", "gmv_oct", "gmv_nov", "gmv_dec", "gmv_jan", "gmv_feb"]

# Self-serve archetype display names
SS_ARCHETYPE_DISPLAY = {
    "SS_ACTIVE_BUYER":            "Active Buyer",
    "SS_HIGH_INTENT":             "High Intent, Not Converting",
    "SS_HIGH_SPENDER_LOW_ENG":    "High Spender, Low Engagement",
    "SS_LOW_ENGAGEMENT":          "Low Engagement, Low Spend",
}

# Self-serve archetype nudges
_SS_ARCHETYPE_NUDGE = {
    "SS_ACTIVE_BUYER":            "bundle",      # already buying — make it efficient
    "SS_HIGH_INTENT":             "offer",       # help close the negotiation they've started
    "SS_HIGH_SPENDER_LOW_ENG":    "chat",        # personal re-engagement for high-value quiet accounts
    "SS_LOW_ENGAGEMENT":          "video_call",  # feature intro — show what the platform offers
}


def ss_archetype(row: pd.Series, orders_p90: float, gmv_p75: float,
                 chat_p50: float, offers_p75: float) -> str:
    """
    Classify a self-serve account into one of four archetypes using
    relative thresholds computed from the self-serve cohort.

    Thresholds are percentile-based so they reflect actual behaviour
    distribution rather than fixed absolute values.

    Active Buyer:              top-decile orders AND buying across multiple months
    High Intent, Not Conv.:    meaningful chat or offers but not an active buyer
    High Spender, Low Eng.:    top-quartile GMV, no meaningful intent signals
    Low Engagement, Low Spend: everything else
    """
    orders        = row.get("orders_6m", 0)
    active_months = row.get("_active_months", 1)
    chat          = row.get("chat_threads", 0)
    offers        = row.get("make_an_offer_6m", 0)
    gmv           = row.get("gmv_total_6m", 0)

    is_active_buyer = (orders >= orders_p90) and (active_months >= 2)
    has_intent      = (chat > chat_p50) or (offers >= offers_p75)
    is_high_spender = (gmv >= gmv_p75) and not has_intent

    if is_active_buyer:
        return "SS_ACTIVE_BUYER"
    if has_intent:
        return "SS_HIGH_INTENT"
    if is_high_spender:
        return "SS_HIGH_SPENDER_LOW_ENG"
    return "SS_LOW_ENGAGEMENT"


# Archetype → migration play description
_ARCHETYPE_PLAY = {
    "ENTRENCHED_BROKER": "broker_protect",
    "HABITUAL_BROKER":   "broker_migration",
    "PLATFORM_CURIOUS":  "broker_migration",
    "DUAL_CHANNEL":      "broker_migration",
    "MID_MIGRATION":     "broker_migration",
}

# Archetype → nudge: what action to take to progress migration
_ARCHETYPE_NUDGE = {
    "ENTRENCHED_BROKER": "video_call",  # introduce platform softly — no migration ask yet
    "HABITUAL_BROKER":   "chat",        # low-friction ask to a reliable, consistent account
    "PLATFORM_CURIOUS":  "video_call",  # build confidence before migration ask
    "DUAL_CHANNEL":      "bundle",      # already ordering both channels — make self-serve efficient
    "MID_MIGRATION":     "bundle",      # reinforce self-serve habit, close the remaining gap
}


def assign_plays(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    if "ss_ratio" not in df.columns:
        total_orders = df["manual_orders"] + df["self_serve_orders"]
        df["ss_ratio"] = (
            df["self_serve_orders"] / total_orders.replace(0, 1)
        ).clip(0, 1)

    # Pre-compute signals for broker archetype classification
    broker_mask = df["segment"] == "BROKER_RELIANT"
    if broker_mask.any():
        df.loc[broker_mask, "_gmv_cv"] = df[broker_mask].apply(_gmv_cv, axis=1)
        df.loc[broker_mask, "_eng_composite"] = (
            df.loc[broker_mask, "app_active_days_6m"] * 2
            + (df.loc[broker_mask, "pdp_views_6m"] / 5).clip(0, 10)
            + df.loc[broker_mask, "make_an_offer_6m"] * 3
        )

        b = df[broker_mask]
        freq_med = b["orders_6m"].median()
        gmv_med  = b["gmv_total_6m"].median()
        rel_med  = b["broker_reliance_pct"].median()
        cv_med   = b["_gmv_cv"].median()

        df.loc[broker_mask, "broker_archetype"] = b.apply(
            lambda r: broker_archetype(r, freq_med, gmv_med, rel_med, cv_med),
            axis=1,
        )

    # Self-serve archetype classification
    ss_mask = ~df["is_account_managed"]
    if ss_mask.any():
        avail_months = [c for c in _MONTHLY_GMV_COLS_SS if c in df.columns]
        df.loc[ss_mask, "_active_months"] = df.loc[ss_mask, avail_months].apply(
            lambda r: (r > 0).sum(), axis=1
        )

        s = df[ss_mask]
        orders_p90 = s["orders_6m"].quantile(0.90)
        gmv_p75    = s["gmv_total_6m"].quantile(0.75)
        chat_p50   = s["chat_threads"].quantile(0.50)
        offers_p75 = s["make_an_offer_6m"].quantile(0.75)

        df.loc[ss_mask, "ss_archetype"] = s.apply(
            lambda r: ss_archetype(r, orders_p90, gmv_p75, chat_p50, offers_p75),
            axis=1,
        )

    plays = []
    journey_positions = []
    nudges = []

    for _, row in df.iterrows():
        if row["segment"] == "BROKER_RELIANT":
            arch = row.get("broker_archetype", "ACTIVE_CONVERTER")
            plays.append(_ARCHETYPE_PLAY.get(arch, "broker_migration"))
            journey_positions.append(_broker_journey_position(row["ss_ratio"]))
            nudges.append(_ARCHETYPE_NUDGE.get(arch))
        elif row["segment"] == "HEALTHY_AM":
            plays.append("am_retention")
            journey_positions.append(None)
            nudges.append(None)
        else:
            arch  = row.get("ss_archetype", "SS_LOW_ENGAGEMENT")
            plays.append("self_serve_nudge")
            journey_positions.append(None)
            nudges.append(_SS_ARCHETYPE_NUDGE.get(arch, "video_call"))

    df["play"] = plays
    df["journey_position"] = journey_positions
    df["nudge_feature"] = nudges

    df = df.drop(columns=["_gmv_cv", "_eng_composite", "_active_months"], errors="ignore")

    return df
