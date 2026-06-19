"""
Sort accounts within each segment and generate plain-English justifications
and engagement summaries.

Broker accounts:   burden_score desc — four weighted signal groups:
                     Reliance Depth 30% + AM Workload 30% +
                     GMV Consistency 20% + Migration Stall 20%
Self-serve:        composite engagement desc, GMV asc as tiebreaker.
Healthy AM:        declining first, then growing, then stable — GMV desc within each.
"""
import numpy as np
import pandas as pd


# ── Broker burden scoring ─────────────────────────────────────────────────────

_MONTHLY_GMV_COLS = ["gmv_sep", "gmv_oct", "gmv_nov", "gmv_dec", "gmv_jan", "gmv_feb"]

# Display names for archetypes (ordered least → most pushable)
ARCHETYPE_DISPLAY = {
    "ENTRENCHED_BROKER": "Entrenched Broker Buyer",
    "HABITUAL_BROKER":   "Habitual Broker Buyer",
    "PLATFORM_CURIOUS":  "Broker Reliant, Platform Curious",
    "DUAL_CHANNEL":      "Active Dual-Channel Buyer",
    "MID_MIGRATION":     "Mid-Migration Self-Server",
}


def _minmax(series: pd.Series) -> pd.Series:
    lo, hi = series.min(), series.max()
    if hi == lo:
        return pd.Series(5.0, index=series.index)
    return (series - lo) / (hi - lo) * 10


def _gmv_consistency_score(row: pd.Series) -> float:
    """
    How steady is monthly GMV? 0 = completely volatile, 10 = perfectly flat.
    Accounts with no monthly data return 5 (neutral).
    """
    vals = [row.get(c, 0) for c in _MONTHLY_GMV_COLS]
    nonzero = [v for v in vals if v > 0]
    if len(nonzero) < 2:
        return 5.0
    mean = np.mean(nonzero)
    if mean == 0:
        return 5.0
    cv = np.std(nonzero) / mean      # coefficient of variation: 0 = flat, high = volatile
    score = max(0.0, 1.0 - cv) * 10  # invert so flat = high score
    return round(score, 2)


def compute_broker_burden(broker_df: pd.DataFrame) -> pd.DataFrame:
    """
    Add burden dimension columns and final burden_score (0–100) to broker_df.
    Also records which two dimensions drove each account's ranking.
    """
    df = broker_df.copy()

    # 1. Reliance Depth — normalised broker_reliance_pct within cohort
    df["_dim_reliance"] = _minmax(df["broker_reliance_pct"])

    # 2. AM Workload — normalised manual_orders within cohort
    df["_dim_workload"] = _minmax(df["manual_orders"])

    # 3. GMV Consistency — row-level calculation
    df["_dim_consistency"] = df.apply(_gmv_consistency_score, axis=1)

    # Weighted sum → 0–100  (reliance 40% · workload 40% · consistency 20%)
    df["burden_score"] = (
        df["_dim_reliance"]    * 0.40 +
        df["_dim_workload"]    * 0.40 +
        df["_dim_consistency"] * 0.20
    ) * 10  # scale: max raw = 10 → ×10 = 100

    df["burden_score"] = df["burden_score"].round(1)

    # Which two dimensions drove each account's score?
    _dim_labels = {
        "_dim_reliance":    "reliance depth",
        "_dim_workload":    "AM workload",
        "_dim_consistency": "GMV consistency",
    }
    _dim_weights = {
        "_dim_reliance":    0.40,
        "_dim_workload":    0.40,
        "_dim_consistency": 0.20,
    }

    def _top_drivers(row):
        contributions = {
            label: row[col] * _dim_weights[col]
            for col, label in _dim_labels.items()
        }
        top2 = sorted(contributions, key=contributions.get, reverse=True)[:2]
        return top2

    df["_burden_drivers"] = df.apply(_top_drivers, axis=1)

    return df


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


_ARCHETYPE_RISK = {
    "ENTRENCHED_BROKER": "HIGH RISK — do not push migration",
    "HABITUAL_BROKER":   "LOW RISK — gentle first ask",
    "PLATFORM_CURIOUS":  "MODERATE RISK — build confidence first",
    "DUAL_CHANNEL":      "LOW RISK — push migration now",
    "MID_MIGRATION":     "LOW RISK — reinforce and close",
}

_ARCHETYPE_ACTION = {
    "ENTRENCHED_BROKER": "High-value, high-volume account with no platform engagement. Introduce platform gently — protect the relationship before any migration ask.",
    "HABITUAL_BROKER":   "Consistent, predictable ordering pattern fully routed through AM. Low-friction ask — frame self-serve as a convenience upgrade for their regular orders.",
    "PLATFORM_CURIOUS":  "High broker reliance but actively exploring the platform. Build confidence first — video call or direct outreach before any migration push.",
    "DUAL_CHANNEL":      "High-volume, platform-engaged, high reliance — already using both channels. Safe to push the first self-serve order directly.",
    "MID_MIGRATION":     "Already self-serving 44% of orders on average. Reinforce the behaviour and close the remaining gap — the hardest work is done.",
}


def _broker_justification(row: pd.Series, rank: int) -> str:
    gmv        = row.get("gmv_total_6m", 0)
    broker_pct = row.get("broker_reliance_pct", 0)
    manual     = int(row.get("manual_orders", 0))
    ss_ratio   = row.get("ss_ratio", 0)
    trend      = _gmv_trend_display(row)
    burden     = row.get("burden_score", 0)
    arch       = row.get("broker_archetype", "")

    tier = "top-priority" if rank <= 5 else ("high-priority" if rank <= 15 else "mid-priority")

    if ss_ratio == 0:
        migration_note = "No self-serve orders placed yet."
    elif ss_ratio <= 0.25:
        migration_note = f"{ss_ratio * 100:.0f}% of orders self-serve — stalled."
    elif ss_ratio <= 0.40:
        migration_note = f"{ss_ratio * 100:.0f}% of orders self-serve — progressing."
    else:
        migration_note = f"{ss_ratio * 100:.0f}% of orders self-serve — nearly there."

    risk_label  = _ARCHETYPE_RISK.get(arch, "")
    action_note = _ARCHETYPE_ACTION.get(arch, "")

    # Derive top two burden drivers from raw dimension scores on the row
    _dim_scores = {
        "reliance depth":  row.get("_dim_reliance", 0) * 0.30,
        "AM workload":     row.get("_dim_workload", 0) * 0.30,
        "GMV consistency": row.get("_dim_consistency", 0) * 0.20,
    }
    top_drivers = sorted(_dim_scores, key=_dim_scores.get, reverse=True)[:2]
    _driver_explain = {
        "reliance depth":  f"{broker_pct:.0f}% broker reliance",
        "AM workload":     f"{manual} manual orders",
        "GMV consistency": "consistent monthly GMV",
    }
    driver_notes = " · ".join(
        _driver_explain[d] for d in top_drivers if _dim_scores[d] > 0
    ) or "—"

    arch_display = ARCHETYPE_DISPLAY.get(arch, arch.replace("_", " ").title()) if arch else "—"

    return (
        f"#{rank} ({tier}) · {arch_display} · {risk_label} · burden {burden:.0f}/100. "
        f"£{gmv:,.0f} GMV ({trend}) · {broker_pct:.0f}% broker reliance · {manual} manual orders. "
        f"{migration_note} "
        f"Score driven by: {driver_notes}. "
        f"{action_note}"
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


_SS_ARCH_ACTION = {
    "SS_ACTIVE_BUYER":         "Retain and grow — bundle ordering to improve efficiency and increase frequency.",
    "SS_HIGH_INTENT":          "Direct buying nudge — high negotiation activity signals purchase intent. Help close.",
    "SS_HIGH_SPENDER_LOW_ENG": "Re-engage before they go quiet — high spend but not using platform features.",
    "SS_LOW_ENGAGEMENT":       "Feature introduction — show offer and chat tools to build toward purchase intent.",
}

_SS_ARCH_RANK_BY = {
    "SS_ACTIVE_BUYER":         ("gmv_total_6m", False),  # highest GMV first
    "SS_HIGH_INTENT":          ("chat_threads",  False),  # most active negotiators first
    "SS_HIGH_SPENDER_LOW_ENG": ("gmv_total_6m", False),  # highest at-risk value first
    "SS_LOW_ENGAGEMENT":       ("gmv_total_6m", False),  # any residual GMV first
}


def _self_serve_justification(row: pd.Series, rank: int) -> str:
    from pipeline.plays import SS_ARCHETYPE_DISPLAY
    gmv      = row.get("gmv_total_6m", 0)
    orders   = int(row.get("orders_6m", 0))
    chat     = int(row.get("chat_threads", 0))
    offers   = int(row.get("make_an_offer_6m", 0))
    pdp      = int(row.get("pdp_views_6m", 0))
    app_days = int(row.get("app_active_days_6m", 0))
    trend    = _gmv_trend_display(row)
    arch     = row.get("ss_archetype", "SS_LOW_ENGAGEMENT")
    nudge    = row.get("nudge_feature", "")

    arch_display = SS_ARCHETYPE_DISPLAY.get(arch, arch)
    action       = _SS_ARCH_ACTION.get(arch, "")

    nudge_label = {
        "bundle":     "Bundle orders",
        "offer":      "Make an offer",
        "chat":       "In-app chat",
        "video_call": "Video call",
    }.get(nudge, nudge)

    return (
        f"#{rank} · {arch_display}. "
        f"£{gmv:,.0f} GMV ({trend}) · {orders} orders · {chat} chats · {offers} offers · "
        f"{pdp} PDP views · {app_days} app days. "
        f"{action} Recommended: {nudge_label}."
    )


def prioritise(df: pd.DataFrame) -> pd.DataFrame:
    parts = []

    for segment, group in df.groupby("segment"):
        g = group.copy()

        if segment == "BROKER_RELIANT":
            g = compute_broker_burden(g)
            g = g.sort_values("burden_score", ascending=False)

        elif segment == "HEALTHY_AM":
            # Declining first (need attention), then growing, then stable — GMV desc within each
            health_order = {"declining": 0, "growing": 1, "stable": 2}
            g["_health_order"] = g["health_status"].map(health_order).fillna(2)
            g = g.sort_values(["_health_order", "gmv_total_6m"], ascending=[True, False])
            g = g.drop(columns=["_health_order"])

        elif segment == "SELF_SERVE":
            # Sort within each ss_archetype group by its preferred rank column
            if "ss_archetype" in g.columns:
                ranked_parts = []
                arch_order = ["SS_ACTIVE_BUYER", "SS_HIGH_INTENT",
                              "SS_HIGH_SPENDER_LOW_ENG", "SS_LOW_ENGAGEMENT"]
                for arch in arch_order:
                    arch_group = g[g["ss_archetype"] == arch].copy()
                    if len(arch_group) == 0:
                        continue
                    sort_col, asc = _SS_ARCH_RANK_BY.get(arch, ("gmv_total_6m", False))
                    if sort_col in arch_group.columns:
                        arch_group = arch_group.sort_values(sort_col, ascending=asc)
                    ranked_parts.append(arch_group)
                # Any accounts without an archetype go last
                no_arch = g[~g["ss_archetype"].isin(arch_order)] if "ss_archetype" in g.columns else g
                if len(no_arch) > 0:
                    ranked_parts.append(no_arch)
                g = pd.concat(ranked_parts, ignore_index=True) if ranked_parts else g
            else:
                g = g.sort_values("gmv_total_6m", ascending=False)

        parts.append(g)

    # Segment display order
    order = {
        "BROKER_RELIANT": 0,
        "HEALTHY_AM":     1,
        "SELF_SERVE":     2,
    }
    result = pd.concat(parts, ignore_index=True)
    result["_seg_order"] = result["segment"].map(order).fillna(99)
    result = result.sort_values("_seg_order").drop(
        columns=["_seg_order", "_dim_stall"],
        errors="ignore",
    ).reset_index(drop=True)
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
        elif seg == "SELF_SERVE":
            justifications.append(_self_serve_justification(row, rank))
        else:
            justifications.append("")

    result["justification"] = justifications

    return result
