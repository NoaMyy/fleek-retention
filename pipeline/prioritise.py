"""
Sort accounts within each segment.

Broker accounts:   GMV desc, then broker_reliance_pct desc as tiebreaker.
Self-serve:        composite engagement desc (app_active_days + pdp_views/10),
                   GMV asc as tiebreaker (lower spend = more headroom).
HEALTHY_AM:        AT_RISK first, then GMV desc.
"""
import pandas as pd


def prioritise(df: pd.DataFrame) -> pd.DataFrame:
    parts = []

    for segment, group in df.groupby("segment"):
        g = group.copy()

        if segment == "BROKER_RELIANT":
            g = g.sort_values(
                ["gmv_total_6m", "broker_reliance_pct"],
                ascending=[False, False],
            )

        elif segment == "HEALTHY_AM":
            g = g.sort_values(
                ["at_risk", "gmv_total_6m"],
                ascending=[False, False],
            )

        elif segment in ("SELF_SERVE_HEADROOM", "SELF_SERVE_MATURE"):
            g = g.sort_values(
                ["engagement_score", "gmv_total_6m"],
                ascending=[False, True],
            )

        parts.append(g)

    # Segment display order
    order = {
        "BROKER_RELIANT": 0,
        "HEALTHY_AM": 1,
        "SELF_SERVE_HEADROOM": 2,
        "SELF_SERVE_MATURE": 3,
    }
    result = pd.concat(parts, ignore_index=True)
    result["_seg_order"] = result["segment"].map(order).fillna(99)
    result = result.sort_values("_seg_order").drop(columns=["_seg_order"]).reset_index(drop=True)
    result.insert(0, "priority_rank", range(1, len(result) + 1))
    return result
