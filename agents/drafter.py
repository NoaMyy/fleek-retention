"""
Draft two SMS variants (A and B) per account via the Claude API.
Reads send log for rung and touch number.
Touch 1 = awareness, touch 2 = social proof, touch 3 = scarcity.
"""
import os
from pathlib import Path

import anthropic
import pandas as pd

from pipeline.send_log import get_touch_number, log_touch

SKILL_PATH = Path(__file__).parent / "message_skill.md"
SKILL = SKILL_PATH.read_text()

TOUCH_ANGLE = {
    1: "awareness",
    2: "social proof",
    3: "scarcity / urgency",
}


def _build_prompt(row: pd.Series, touch_number: int) -> str:
    angle = TOUCH_ANGLE.get(touch_number, "awareness")
    rung = row.get("rung") or "n/a"
    nudge = row.get("nudge_feature") or "n/a"
    at_risk = bool(row.get("at_risk", False))
    segment = row["segment"]

    context = (
        f"Account: {row['account_id']}\n"
        f"Segment: {segment}{' (AT_RISK)' if at_risk else ''}\n"
        f"Play: {row.get('play', 'n/a')}\n"
        f"Rung: {rung}\n"
        f"Nudge feature: {nudge}\n"
        f"GMV last 6m (GBP): {row.get('gmv_total_6m', 0):,.0f}\n"
        f"Broker reliance: {row.get('broker_reliance_pct', 0):.0f}%\n"
        f"App active days: {row.get('app_active_days_6m', 0)}\n"
        f"PDP views: {row.get('pdp_views_6m', 0)}\n"
        f"Touch number: {touch_number} of 3 — angle: {angle}\n"
    )

    return (
        f"{SKILL}\n\n"
        "---\n\n"
        "Draft two SMS variants (A and B) for this account.\n"
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
) -> pd.DataFrame:
    """
    Add msg_variant_a and msg_variant_b columns to df.
    Skips accounts already at touch 3.
    """
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

        prompt = _build_prompt(row, touch)
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
                rung=row.get("rung"),
                touch_number=touch,
                variant="A",
                send_status="drafted",
            )
            log_touch(
                account_id=row["account_id"],
                segment=row["segment"],
                play=str(row.get("play", "")),
                rung=row.get("rung"),
                touch_number=touch,
                variant="B",
                send_status="drafted",
            )

        except Exception as e:
            print(f"  [drafter] Error for {row['account_id']}: {e}")
            df.at[idx, "msg_variant_a"] = f"[error] {e}"
            df.at[idx, "msg_variant_b"] = f"[error] {e}"

    return df
