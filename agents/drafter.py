"""
Draft two SMS variants (A and B) per account via the Claude API.
Variant angles are loaded from config/variants.json and can be edited
in the dashboard — call draft_messages(df, variants=load_variants()) to
apply updated angles without re-uploading.
"""
import json
import os
from pathlib import Path

import anthropic
import pandas as pd

from pipeline.send_log import log_touch

DRAFT_CACHE_PATH = "data/drafts_cache.json"


def _load_draft_cache() -> dict:
    try:
        with open(DRAFT_CACHE_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_draft_cache(cache: dict) -> None:
    os.makedirs("data", exist_ok=True)
    with open(DRAFT_CACHE_PATH, "w") as f:
        json.dump(cache, f)


def _cache_key(row: pd.Series) -> str:
    """Unique key per account+context — cache busts if play/nudge/journey changes."""
    return "|".join([
        str(row.get("account_id", "")),
        str(row.get("play", "")),
        str(row.get("journey_position", "")),
        str(row.get("nudge_feature", "")),
        str(row.get("segment", "")),
    ])

VARIANTS_PATH = "config/variants.json"


def _load_variants() -> dict:
    try:
        with open(VARIANTS_PATH) as f:
            return json.load(f)
    except Exception:
        return {"broker_stages": {}, "ss_pathways": {}}

SKILL_PATH = Path(__file__).parent / "message_skill.md"
SKILL = SKILL_PATH.read_text()

# Broker stage A/B angles — A: self-serve empowerment; B: feature discovery
# RULE: never suggest contacting the AM — always direct to the app/platform
BROKER_STAGE_ANGLES = {
    "not_started": {
        "a": "social proof + loss aversion — buyers in their category ordering themselves get stock 2 days faster, no waiting. Direct them to place their next restock in the app right now. Do NOT reference contacting the AM.",
        "b": "feature discovery — real-time stock and saved order templates are in the app. Everything they need is one tap. Do NOT suggest asking the AM for anything.",
    },
    "stalled": {
        "a": "commitment/consistency + friction removal — they already did it once (hardest part done). Second order takes half the time. Tell them to try the next one in the app. Do NOT reference contacting the AM.",
        "b": "feature discovery — saved order lists and one-tap reorder from history are now live in the app. The friction they hit before may be gone. Direct to the app, not the AM.",
    },
    "moving": {
        "a": "progress milestone + social proof — already placing most orders themselves. Crossing 50% self-serve unlocks faster fulfilment. They're 2–3 orders away. Direct action: place the next one in the app.",
        "b": "feature discovery — reorder full order history in one tap from the app. Buyers using it cut sourcing time by 40%. Set it up in 2 mins. No AM involvement.",
    },
    "nearly_graduated": {
        "a": "loss aversion + identity — majority self-serve, one more order crosses the line. Faster fulfilment, fully in control. Direct to the app. Do NOT frame AM as a fallback.",
        "b": "feature discovery — order templates in the app: save regular restocks, each reorder under 60 seconds. Set up once, reuse every time. No AM involvement.",
    },
}

# Self-serve A/B angles keyed on nudge_feature (aligned to buyer journey stage)
SS_PATHWAY_ANGLES = {
    "video_call": {
        "a": "Browser — social proof + confidence: buyers who video call before a big order convert 3× more. They browsed many PDPs but haven't committed — a video call removes the uncertainty about stock quality.",
        "b": "Browser — scarcity + outcome: limited slots this week, 30% higher spend per session for buyers who use video calls. Seeing stock live before ordering is what separates browsers from buyers.",
    },
    "offer": {
        "a": "Consideration — loss aversion + urgency: they've been exploring but suppliers move stock daily. The price on viewed items won't hold. Making an offer takes 2 mins and locks in what they want before it goes.",
        "b": "Consideration — social proof + ease: buyers at their stage get a supplier response within 4 hours of making an offer. Their browsing history already shows exactly what to target — the conversation is halfway done.",
    },
    "bundle": {
        "a": "Purchase — efficiency + quantified value: 18% GMV saving and 2 days faster fulfilment per cycle for buyers at their volume. Their last few orders could have shipped together — frame it as optimisation, not a new behaviour.",
        "b": "Purchase — social proof + identity: they're top-tier self-serve. 9 in 10 buyers at their level who try bundles don't go back to single orders. Frame it as the next natural step for buyers at their level.",
    },
    "chat": {
        "a": "Re-engagement — reciprocity + personalisation: new stock has arrived that matches exactly what they were buying before. A shortlist is already built from their order history — one message to receive it.",
        "b": "Re-engagement — FOMO + social proof: buyers in their category are placing early-season orders now and best stock goes fast. Their account is ready — one message gets them back in before shortages hit.",
    },
}


def _build_prompt(row: pd.Series, variants: dict) -> str:
    journey_position = row.get("journey_position") or ""
    nudge = row.get("nudge_feature") or ""
    segment = row["segment"]

    broker_stages = variants.get("broker_stages", {})
    ss_pathways   = variants.get("ss_pathways", {})

    if segment == "BROKER_RELIANT" and journey_position in broker_stages:
        s = broker_stages[journey_position]
        angle_a = s.get("variant_a", "")
        angle_b = s.get("variant_b", "")
    elif nudge in ss_pathways:
        p = ss_pathways[nudge]
        angle_a = p.get("variant_a", "")
        angle_b = p.get("variant_b", "")
    else:
        angle_a = "value — highlight the benefit most relevant to this account"
        angle_b = "social proof — how similar buyers have benefited"

    context = (
        f"Account: {row['account_id']}\n"
        f"Segment: {segment}\n"
        f"Play: {row.get('play', 'n/a')}\n"
        f"Journey stage: {journey_position or 'n/a'}\n"
        f"Nudge feature: {nudge or 'n/a'}\n"
        f"GMV last 6m (GBP): {row.get('gmv_total_6m', 0):,.0f}\n"
        f"Broker reliance: {row.get('broker_reliance_pct', 0):.0f}%\n"
        f"Self-serve ratio: {row.get('ss_ratio', 0):.0%}\n"
        f"App active days: {row.get('app_active_days_6m', 0)}\n"
        f"PDP views: {row.get('pdp_views_6m', 0)}\n"
        f"Variant A angle: {angle_a}\n"
        f"Variant B angle: {angle_b}\n"
    )


    return (
        f"{SKILL}\n\n"
        "---\n\n"
        "Draft two SMS variants (A and B) for this account.\n"
        "Variant A must follow the Variant A angle. Variant B must follow the Variant B angle.\n"
        "CRITICAL RULE: Never suggest the buyer contacts the account manager, replies to the AM, "
        "or reaches out via any channel other than the platform itself. "
        "All CTAs must direct the buyer to act in the app (place an order, make an offer, open a chat, book a call). "
        "Do not use 'I', 'me', or 'my' in a way that positions the AM as an intermediary.\n"
        "Return ONLY:\n"
        "VARIANT_A: <message>\n"
        "VARIANT_B: <message>\n\n"
        f"{context}"
    )


def _parse_variants(text: str) -> tuple[str, str]:
    a, b = "", ""
    for line in text.splitlines():
        if line.startswith("VARIANT_A:"):
            a = line.replace("VARIANT_A:", "").strip()
        elif line.startswith("VARIANT_B:"):
            b = line.replace("VARIANT_B:", "").strip()
    return a, b


def draft_messages(
    df: pd.DataFrame,
    max_accounts=None,
    dry_run: bool = False,
    variants: dict = None,
) -> pd.DataFrame:
    """
    Add msg_variant_a and msg_variant_b columns to df.
    Calls are made in parallel (up to 20 concurrent) to keep total time under ~15s.
    Skips accounts that already have a drafted message unless variants changed.
    """
    import concurrent.futures

    if variants is None:
        variants = _load_variants()

    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    df = df.copy()

    if "msg_variant_a" not in df.columns:
        df["msg_variant_a"] = ""
    if "msg_variant_b" not in df.columns:
        df["msg_variant_b"] = ""
    if "touch_number" not in df.columns:
        df["touch_number"] = 1

    if not api_key:
        df["msg_variant_a"] = df.apply(
            lambda r: f"[A] {r['play']} nudge for {r['account_id']}",
            axis=1,
        )
        df["msg_variant_b"] = df.apply(
            lambda r: f"[B] {r['play']} nudge for {r['account_id']}",
            axis=1,
        )
        return df

    client = anthropic.Anthropic(api_key=api_key)
    cache = _load_draft_cache()

    subset = df if max_accounts is None else df.head(max_accounts)

    # Fill from cache first
    for idx, row in subset.iterrows():
        key = _cache_key(row)
        if key in cache:
            entry = cache[key]
            df.at[idx, "msg_variant_a"] = entry.get("a", "")
            df.at[idx, "msg_variant_b"] = entry.get("b", "")

    # Only call API for rows still without a draft
    needs_draft = df[df["msg_variant_a"].fillna("") == ""].copy()

    def _draft_one(idx_row):
        idx, row = idx_row
        if dry_run:
            return idx, "[dry-run A]", "[dry-run B]"
        prompt = _build_prompt(row, variants)
        try:
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}],
            )
            a, b = _parse_variants(response.content[0].text)
            return idx, a, b
        except Exception as e:
            print(f"  [drafter] Error for {row['account_id']}: {e}")
            return idx, f"[error] {e}", f"[error] {e}"

    if not needs_draft.empty:
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
            results = list(pool.map(_draft_one, needs_draft.iterrows()))

        for idx, a, b in results:
            df.at[idx, "msg_variant_a"] = a
            df.at[idx, "msg_variant_b"] = b
            key = _cache_key(df.loc[idx])
            cache[key] = {"a": a, "b": b}

        _save_draft_cache(cache)

    return df
