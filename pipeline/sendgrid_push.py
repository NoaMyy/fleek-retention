"""
Push drafted messages to SendGrid as Single Send DRAFTS (Marketing Campaigns API).
Drafts appear in SendGrid → Marketing → Campaigns and must be scheduled/sent manually.
Nothing is delivered to recipients until you click Send in the SendGrid dashboard.

Requires SENDGRID_API_KEY and SENDGRID_FROM_EMAIL in environment.
"""
import os

import pandas as pd
import requests

_SEG_LABEL = {
    "BROKER_RELIANT": "Broker",
    "HEALTHY_AM":     "Healthy AM",
    "SELF_SERVE":     "Self-Serve",
}

BASE_URL = "https://api.sendgrid.com/v3"


def _build_subject(row: pd.Series) -> str:
    account_id = str(row.get("account_id", ""))
    seg        = _SEG_LABEL.get(str(row.get("segment", "")), str(row.get("segment", "")))
    gmv        = float(row.get("gmv_total_6m", 0))
    gmv_str    = f"£{int(gmv // 1000)}k" if gmv >= 1000 else f"£{int(gmv)}"
    return f"[{account_id}] {seg} · {gmv_str} GMV"


def _get_sender_id(headers: dict):
    """Return the first verified sender ID on the account."""
    r = requests.get(f"{BASE_URL}/verified_senders", headers=headers, timeout=10)
    if r.status_code == 200:
        senders = r.json().get("results", [])
        if senders:
            return senders[0].get("id")
    return None


def _create_draft(headers: dict, name: str, subject: str, body: str,
                  sender_id: int) -> tuple[bool, str]:
    """Create a Single Send draft. Returns (success, id_or_error)."""
    payload = {
        "name": name,
        "email_config": {
            "subject":       subject,
            "plain_content": body,
            "sender_id":     sender_id,
        },
    }
    r = requests.post(
        f"{BASE_URL}/marketing/singlesends",
        headers=headers,
        json=payload,
        timeout=15,
    )
    if r.status_code in (200, 201):
        return True, r.json().get("id", "")
    return False, f"HTTP {r.status_code}: {r.text[:120]}"


def push_drafts(
    df: pd.DataFrame,
    variant: str = "A",
    dry_run: bool = True,
) -> dict:
    """
    Create a SendGrid Single Send DRAFT for each account row.
    Drafts sit in SendGrid → Marketing → Campaigns until you send them manually.
    dry_run=True (default) counts rows without calling the API.
    """
    api_key    = os.getenv("SENDGRID_API_KEY", "").strip()
    from_email = os.getenv("SENDGRID_FROM_EMAIL", "")

    if not api_key:
        return {
            "queued": 0, "skipped": len(df), "errors": [],
            "detail": "No SENDGRID_API_KEY — set it in .env to create drafts.",
        }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type":  "application/json",
    }

    msg_col  = "msg_variant_a" if variant.upper() == "A" else "msg_variant_b"
    results  = {"queued": 0, "skipped": 0, "errors": [], "detail": ""}

    if dry_run:
        for _, row in df.iterrows():
            msg = str(row.get(msg_col, "")).strip()
            if msg:
                results["queued"] += 1
            else:
                results["skipped"] += 1
        results["detail"] = "Dry run — no drafts created in SendGrid."
        return results

    # Fetch sender ID once
    sender_id = _get_sender_id(headers)
    if not sender_id:
        return {
            "queued": 0, "skipped": len(df), "errors": [],
            "detail": "Could not find a verified sender on this SendGrid account. "
                      "Add one at sendgrid.com → Settings → Sender Authentication.",
        }

    for _, row in df.iterrows():
        account_id = str(row.get("account_id", ""))
        msg        = str(row.get(msg_col, "")).strip()

        if not msg:
            results["skipped"] += 1
            continue

        subject = _build_subject(row)
        # Name must be unique in SendGrid — include account + touch
        name    = f"Fleek | {account_id} | Variant {variant.upper()}"

        ok, info = _create_draft(headers, name, subject, msg, sender_id)
        if ok:
            results["queued"] += 1
        else:
            results["errors"].append({"account_id": account_id, "error": info})

    return results
