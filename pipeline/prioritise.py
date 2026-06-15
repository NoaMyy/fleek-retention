"""
Sort accounts within each segment and generate plain-English justifications
and engagement summaries.

Broker accounts:   manual_orders desc (highest AM burden first), GMV desc as tiebreaker.
Self-serve:        composite engagement desc, GMV asc as tiebreaker.
Healthy AM:        declining first, then growing, then stable — GMV desc within each.
"""
import pandas as pd


def _gmv_trend_display(row: pd.Series) -> str:
    """Return a readable GMV trend string e.g. '↑ +22%', '↓ -18%', '→ +3%'."""
    first = row.get("first_3m_gmv", 0)
    last = row.get("last_3m_gmv", 0)
    if first == 0:
        return "—"
    pct = (last - first) / first * 100
    if pct > 10:
        return f"↑ +{pct:.0f}%"
    elif pct < -10:
        return f"↓ {pct:.0f}%"
    else:
        return f"→ {pct:+.0f}%"


def _engagement_summary(row: pd.Series) -> str:
    """Plain-English summary of an account's behavioural engagement."""
    app_days = int(row.get("app_active_days_6m", 0))
    pdp = int(row.get("pdp_views_6m", 0))
    offers = int(row.get("make_an_offer_6m", 0))
    chat = int(row.get("chat_threads", 0))
    video = int(row.get("video_call_requests", 0))
    orders = int(row.get("orders_6m", 0))
    bundle = int(row.get("bundle_orders", 0))

    parts = []

    # App activity
    if app_days == 0:
        parts.append("No app activity recorded")
    elif app_days <= 5:
        parts.append(f"Low app usage ({app_days} active days)")
    elif app_days <= 15:
        parts.append(f"Moderate app usage ({app_days} active days)")
    else:
        parts.append(f"Active app user ({app_days} days)")

    # Browsing
    if pdp == 0:
        parts.append("no product browsing")
    elif pdp < 10:
        parts.append(f"light browsing ({pdp} PDP views)")
    else:
        parts.append(f"browsed {pdp} products")

    # Transactional signals
    if offers > 0:
        parts.append(f"{offers} offer{'s' if offers > 1 else ''} made")
    if chat > 0:
        parts.append(f"{chat} chat thread{'s' if chat > 1 else ''}")
    if video > 0:
        parts.append(f"{video} video call request{'s' if video > 1 else ''}")
    if bundle > 0:
        parts.append(f"{bundle} bundle order{'s' if bundle > 1 else ''}")

    return "; ".join(parts) + "."


def _broker_justification(row: pd.Series, rank: int) -> str:
    gmv = row.get("gmv_total_6m", 0)
    broker_pct = row.get("broker_reliance_pct", 0)
    manual = int(row.get("manual_orders", 0))
    ss_ratio = row.get("ss_ratio", 0)
    trend = _gmv_trend_display(row)

    tier = "top-priority" if rank <= 5 else ("high-priority" if rank <= 15 else "mid-priority")

    if ss_ratio == 0:
        migration_note = "No self-serve activity yet — migration not started."
    elif ss_ratio <= 0.25:
        migration_note = f"{ss_ratio * 100:.0f}% of orders self-serve — migration stalled, needs unblocking."
    elif ss_ratio <= 0.40:
        migration_note = f"{ss_ratio * 100:.0f}% of orders self-serve — migration underway, next step needed."
    else:
        migration_note = f"{ss_ratio * 100:.0f}% of orders self-serve — nearly graduated, one nudge to go."

    return (
        f"Ranked #{rank} ({tier}). £{gmv:,.0f} GMV (trend {trend}) · "
        f"{broker_pct:.0f}% broker reliance · {manual} manual orders placed by AM. "
        f"{migration_note}"
    )


def _healthy_am_justification(row: pd.Series, rank: int) -> str:
    gmv = row.get("gmv_total_6m", 0)
    app_days = row.get("app_active_days_6m", 0)
    pdp_views = row.get("pdp_views_6m", 0)
    health = row.get("health_status", "stable") or "stable"
    trend = _gmv_trend_display(row)

    health_note = {
        "growing":   "GMV trending up — nurture and expand.",
        "declining": "GMV trending down — proactive save call recommended.",
        "stable":    "GMV stable — maintain relationship.",
    }.get(health, "")

    return (
        f"Ranked #{rank} by GMV. £{gmv:,.0f} GMV (trend {trend}) · "
        f"account-managed · {app_days} app days · {pdp_views} PDP views · "
        f"health: {health.upper()}. {health_note}"
    )


def _self_serve_justification(row: pd.Series, rank: int, segment: str) -> str:
    gmv = row.get("gmv_total_6m", 0)
    app_days = row.get("app_active_days_6m", 0)
    pdp_views = row.get("pdp_views_6m", 0)
    engagement = row.get("engagement_score", 0)
    nudge = row.get("nudge_feature", "")
    trend = _gmv_trend_display(row)

    nudge_map = {
        "video_call": "high PDP views but no video calls booked — video call nudge recommended",
        "chat":       "active offer-maker but not using chat — in-app chat nudge recommended",
        "bundle":     "multi-order buyer not using bundles — bundle feature nudge recommended",
    }
    nudge_note = nudge_map.get(nudge, "feature adoption opportunity identified")

    if segment == "TRUE_HEADROOM":
        return (
            f"Ranked #{rank} by engagement. £{gmv:,.0f} GMV (trend {trend}) · "
            f"{app_days} app days · {pdp_views} PDP views (score {engagement:.0f}). "
            f"High engagement but low spend — strong upsell potential. {nudge_note.capitalize()}."
        )
    elif segment == "PASSIVE_BUYER":
        return (
            f"Ranked #{rank} by GMV. £{gmv:,.0f} GMV (trend {trend}) · "
            f"{app_days} app days · {pdp_views} PDP views (score {engagement:.0f}). "
            f"High GMV but low engagement — churn risk, needs re-activation. {nudge_note.capitalize()}."
        )
    else:
        return (
            f"£{gmv:,.0f} GMV (trend {trend}) · "
            f"{app_days} app days · {pdp_views} PDP views (score {engagement:.0f}). "
            f"Self-serve account. {nudge_note.capitalize()}."
        )


def prioritise(df: pd.DataFrame) -> pd.DataFrame:
    parts = []

    for segment, group in df.groupby("segment"):
        g = group.copy()

        if segment == "BROKER_RELIANT":
            # Rank by manual_orders desc (highest AM burden first), GMV desc as tiebreaker
            g = g.sort_values(
                ["manual_orders", "gmv_total_6m"],
                ascending=[False, False],
            )

        elif segment == "HEALTHY_AM":
            # Declining first (need attention), then growing, then stable — GMV desc within each
            health_order = {"declining": 0, "growing": 1, "stable": 2}
            g["_health_order"] = g["health_status"].map(health_order).fillna(2)
            g = g.sort_values(["_health_order", "gmv_total_6m"], ascending=[True, False])
            g = g.drop(columns=["_health_order"])

        elif segment == "TRUE_HEADROOM":
            # Rank by engagement desc — highest intent first
            g = g.sort_values(["engagement_score", "gmv_total_6m"], ascending=[False, True])

        elif segment == "PASSIVE_BUYER":
            # Rank by GMV desc — highest value at risk first
            g = g.sort_values(["gmv_total_6m", "engagement_score"], ascending=[False, True])

        elif segment == "SELF_SERVE_OTHER":
            g = g.sort_values(["gmv_total_6m"], ascending=[False])

        parts.append(g)

    # Segment display order
    order = {
        "BROKER_RELIANT":   0,
        "HEALTHY_AM":       1,
        "TRUE_HEADROOM":    2,
        "PASSIVE_BUYER":    3,
        "SELF_SERVE_OTHER": 4,
    }
    result = pd.concat(parts, ignore_index=True)
    result["_seg_order"] = result["segment"].map(order).fillna(99)
    result = result.sort_values("_seg_order").drop(columns=["_seg_order"]).reset_index(drop=True)
    result.insert(0, "priority_rank", range(1, len(result) + 1))

    # Per-segment rank
    result["seg_rank"] = result.groupby("segment").cumcount() + 1

    # GMV trend display and engagement summary
    result["gmv_trend"] = result.apply(_gmv_trend_display, axis=1)
    result["engagement_summary"] = result.apply(_engagement_summary, axis=1)

    # Justification
    justifications = []
    for _, row in result.iterrows():
        seg = row["segment"]
        rank = int(row["seg_rank"])
        if seg == "BROKER_RELIANT":
            justifications.append(_broker_justification(row, rank))
        elif seg == "HEALTHY_AM":
            justifications.append(_healthy_am_justification(row, rank))
        elif seg in ("TRUE_HEADROOM", "PASSIVE_BUYER", "SELF_SERVE_OTHER"):
            justifications.append(_self_serve_justification(row, rank, seg))
        else:
            justifications.append("")

    result["justification"] = justifications

    return result
