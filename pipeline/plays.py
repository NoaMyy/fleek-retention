"""
Assign a play and rung to each account.

Broker migration play — ss_ratio rungs:
  not_started      ss_ratio == 0
  stalled          0 < ss_ratio <= 0.25
  moving           0.25 < ss_ratio <= 0.40
  nearly_graduated ss_ratio > 0.40

Self-serve feature nudge — pick the feature with the strongest engagement signal gap:
  video_call   video_call_requests == 0 but high PDP views
  chat         chat_threads == 0 but high offer activity
  bundle       bundle_orders == 0 but multi-order buyer
"""
import pandas as pd


def _broker_rung(ss_ratio: float) -> str:
    if ss_ratio == 0:
        return "not_started"
    elif ss_ratio <= 0.25:
        return "stalled"
    elif ss_ratio <= 0.40:
        return "moving"
    else:
        return "nearly_graduated"


def _self_serve_nudge(row: pd.Series) -> str:
    """Return the single best feature nudge for a self-serve account."""
    # Strongest gap = highest potential unlocked / lowest current usage
    scores = {}

    # Video call: high PDP views but zero video calls
    if row["video_call_requests"] == 0 and row["pdp_views_6m"] > 20:
        scores["video_call"] = row["pdp_views_6m"]

    # Chat: active maker of offers but no chat threads
    if row["chat_threads"] == 0 and row["make_an_offer_6m"] > 2:
        scores["chat"] = row["make_an_offer_6m"] * 10

    # Bundle: multi-order buyer not using bundles
    if row["bundle_orders"] == 0 and row["orders_6m"] > 2:
        scores["bundle"] = row["orders_6m"] * 5

    if not scores:
        # Default to video_call if no clear signal
        return "video_call"

    return max(scores, key=lambda k: scores[k])


def assign_plays(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    total_orders = df["manual_orders"] + df["self_serve_orders"]
    df["ss_ratio"] = (
        df["self_serve_orders"] / total_orders.replace(0, 1)
    ).clip(0, 1)

    plays = []
    rungs = []
    nudges = []

    for _, row in df.iterrows():
        if row["segment"] == "BROKER_RELIANT":
            plays.append("broker_migration")
            rungs.append(_broker_rung(row["ss_ratio"]))
            nudges.append(None)
        elif row["segment"] == "HEALTHY_AM":
            plays.append("am_retention" if not row["at_risk"] else "at_risk_save")
            rungs.append(None)
            nudges.append(None)
        else:
            plays.append("self_serve_nudge")
            rungs.append(None)
            nudges.append(_self_serve_nudge(row))

    df["play"] = plays
    df["rung"] = rungs
    df["nudge_feature"] = nudges

    return df
