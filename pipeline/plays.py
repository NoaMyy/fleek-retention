"""
Assign a play, journey_position, and nudge_feature to each account.

Broker migration play — ss_ratio journey positions:
  not_started      ss_ratio == 0
  stalled          0 < ss_ratio <= 0.25
  moving           0.25 < ss_ratio <= 0.40
  nearly_graduated ss_ratio > 0.40

  Bundle nudge for broker accounts:
  Accounts in stalled / moving / nearly_graduated that have started self-serving
  (self_serve_orders > 0) but have never placed a bundle order are flagged with
  nudge_feature = "bundle". Bundle makes their self-serve orders faster and more
  efficient — accelerating migration away from the broker.

Self-serve journey position — buyer journey stage:
  ss_browser        Low orders, no offers/chat yet — just browsing
  ss_consideration  Actively making offers or chatting, but low order volume
  ss_purchase       Regular ordering (2+ orders) with decent engagement
  ss_reengagement   High past GMV but gone quiet (high GMV, low eng, low orders)

Self-serve nudge — journey-stage-driven:
  ss_browser        → video_call  (see stock, build confidence before committing)
  ss_consideration  → offer       (already negotiating — help close the deal)
  ss_purchase       → bundle      (optimise high-frequency buyers)
  ss_reengagement   → chat        (personal, low-friction restart for lapsed accounts)
"""
import pandas as pd


def _broker_journey_position(ss_ratio: float) -> str:
    if ss_ratio == 0:
        return "not_started"
    elif ss_ratio <= 0.25:
        return "stalled"
    elif ss_ratio <= 0.40:
        return "moving"
    else:
        return "nearly_graduated"


def _ss_journey_position(row: pd.Series) -> str:
    """Buyer-journey-driven stage for self-serve accounts."""
    gmv    = row.get("gmv_total_6m", 0)
    eng    = row.get("engagement_score", 0)
    offers = row.get("make_an_offer_6m", 0)
    chat   = row.get("chat_threads", 0)
    orders = row.get("orders_6m", 0)

    # Re-engagement: high past spend but gone quiet
    if gmv > 200 and eng < 15 and orders <= 2:
        return "ss_reengagement"
    # Purchase: ordering regularly with decent engagement
    if orders >= 2 and eng >= 20:
        return "ss_purchase"
    # Consideration: actively negotiating but low order volume
    if (offers > 0 or chat > 0) and orders <= 2:
        return "ss_consideration"
    # Browser: hasn't engaged with negotiation tools yet
    return "ss_browser"


def _self_serve_nudge(row: pd.Series) -> str:
    """Journey-stage-driven nudge logic."""
    pos = _ss_journey_position(row)
    return {
        "ss_browser":       "video_call",
        "ss_consideration": "offer",
        "ss_purchase":      "bundle",
        "ss_reengagement":  "chat",
    }.get(pos, "video_call")


def assign_plays(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # ss_ratio is computed in clean.py; recalculate only if missing
    if "ss_ratio" not in df.columns:
        total_orders = df["manual_orders"] + df["self_serve_orders"]
        df["ss_ratio"] = (
            df["self_serve_orders"] / total_orders.replace(0, 1)
        ).clip(0, 1)

    plays = []
    journey_positions = []
    nudges = []

    for _, row in df.iterrows():
        if row["segment"] == "BROKER_RELIANT":
            plays.append("broker_migration")
            pos = _broker_journey_position(row["ss_ratio"])
            journey_positions.append(pos)
            # Flag bundle opportunity: started self-serving but never bundled
            if (
                pos in ("stalled", "moving", "nearly_graduated")
                and row.get("self_serve_orders", 0) > 0
                and row.get("bundle_orders", 0) == 0
            ):
                nudges.append("bundle")
            else:
                nudges.append(None)
        elif row["segment"] == "HEALTHY_AM":
            plays.append("am_retention")
            journey_positions.append(None)
            nudges.append(None)
        else:
            nudge = _self_serve_nudge(row)
            plays.append("self_serve_nudge")
            journey_positions.append(_ss_journey_position(row))
            nudges.append(nudge)

    df["play"] = plays
    df["journey_position"] = journey_positions
    df["nudge_feature"] = nudges

    return df
