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

from pipeline.send_log import get_touch_number, log_touch

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


def _build_prompt(row: pd.Series, touch_number: int, variants: dict) -> str:
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
    Skips accounts already at touch 3.
    """
    if variants is None:
        variants = _load_variants()

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("  [drafter] No ANTHROPIC_API_KEY — filling placeholder messages.")
        df = df.copy()
        df["msg_variant_a"] = df.apply(
            lambda r: f"[A] {r['play']} nudge for {r['account_id']} (touch {get_touch_number(r['account_id'])})",
            axis=1,
        )
        df["msg_variant_b"] = df.apply(
            lambda r: f"[B] {r['play']} nudge for {r['account_id']} (touch {get_touch_number(r['account_id'])})",
            axis=1,
        )
        df["touch_number"] = df["account_id"].apply(get_touch_number)
        return df

    client = anthropic.Anthropic(api_key=api_key)
    df = df.copy()
    df["msg_variant_a"] = ""
    df["msg_variant_b"] = ""
    df["touch_number"] = 1

    subset = df if max_accounts is None else df.head(max_accounts)

    for idx, row in subset.iterrows():
        touch = get_touch_number(row["account_id"])
        df.at[idx, "touch_number"] = touch

        if dry_run:
            df.at[idx, "msg_variant_a"] = f"[dry-run A] touch {touch}"
            df.at[idx, "msg_variant_b"] = f"[dry-run B] touch {touch}"
            continue

        prompt = _build_prompt(row, touch, variants)
        try:
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text
            a, b = _parse_variants(text)
            df.at[idx, "msg_variant_a"] = a
            df.at[idx, "msg_variant_b"] = b

            log_touch(
                account_id=row["account_id"],
                segment=row["segment"],
                play=str(row.get("play", "")),
                journey_position=row.get("journey_position"),
                touch_number=touch,
                variant="A",
                send_status="drafted",
            )
            log_touch(
                account_id=row["account_id"],
                segment=row["segment"],
                play=str(row.get("play", "")),
                journey_position=row.get("journey_position"),
                touch_number=touch,
                variant="B",
                send_status="drafted",
            )

        except Exception as e:
            print(f"  [drafter] Error for {row['account_id']}: {e}")
            df.at[idx, "msg_variant_a"] = f"[error] {e}"
            df.at[idx, "msg_variant_b"] = f"[error] {e}"

    return df
