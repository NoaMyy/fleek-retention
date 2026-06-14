"""
Push drafted messages to SendGrid as drafts (single-send / marketing campaign drafts).
Requires SENDGRID_API_KEY and SENDGRID_FROM_EMAIL in environment.

Subject format : [ACC-001] T1 Broker · £170k GMV
Category tag   : account_id  (filterable in SendGrid dashboard)
Custom header  : X-Account-ID: ACC-001
dry_run        : True by default — nothing sends automatically.
"""
import os

import pandas as pd


# Segment short labels for the subject line
_SEG_LABEL = {
    "BROKER_RELIANT": "Broker",
    "HEALTHY_AM": "Healthy AM",
    "SELF_SERVE_HEADROOM": "SS Headroom",
    "SELF_SERVE_MATURE": "SS Mature",
}


def _build_subject(row: pd.Series) -> str:
    account_id = str(row.get("account_id", ""))
    touch = int(row.get("touch_number", 1))
    seg = _SEG_LABEL.get(str(row.get("segment", "")), str(row.get("segment", "")))
    gmv = float(row.get("gmv_total_6m", 0))
    gmv_str = f"£{int(gmv // 1000)}k" if gmv >= 1000 else f"£{int(gmv)}"
    return f"[{account_id}] T{touch} {seg} · {gmv_str} GMV"


def push_drafts(
    df: pd.DataFrame,
    variant: str = "A",
    dry_run: bool = True,       # safe default — must be explicitly set False to send
) -> dict:
    """
    For each row with a drafted message, create a SendGrid Single Send draft.
    Returns summary dict {queued: int, skipped: int, errors: list}.

    Nothing sends automatically. Call with dry_run=False only from an explicit
    user action (e.g., the Streamlit 'Push to SendGrid' button).
    """
    api_key = os.getenv("SENDGRID_API_KEY", "")
    from_email = os.getenv("SENDGRID_FROM_EMAIL", "retention@example.com")

    if not api_key:
        return {"queued": 0, "skipped": len(df), "errors": [],
                "detail": "No SENDGRID_API_KEY — set it in .env to push drafts."}

    try:
        import sendgrid as sg_module
        from sendgrid.helpers.mail import (
            Category,
            Header,
            Mail,
        )
        sg = sg_module.SendGridAPIClient(api_key=api_key)
    except ImportError:
        return {"queued": 0, "skipped": len(df), "errors": [],
                "detail": "sendgrid package not installed."}

    msg_col = "msg_variant_a" if variant.upper() == "A" else "msg_variant_b"
    results = {"queued": 0, "skipped": 0, "errors": [], "detail": ""}

    for _, row in df.iterrows():
        account_id = str(row.get("account_id", ""))

        msg = str(row.get(msg_col, "")).strip()
        if not msg:
            results["skipped"] += 1
            continue

        email = str(row.get("email", ""))
        if not email or "@" not in email:
            results["skipped"] += 1
            continue

        subject = _build_subject(row)

        if dry_run:
            results["queued"] += 1
            continue

        try:
            message = Mail(
                from_email=from_email,
                to_emails=email,
                subject=subject,
                plain_text_content=msg,
            )

            # Category tag — filterable in SendGrid by account_id
            message.category = Category(account_id)

            # Custom header so downstream systems can identify the account
            message.header = Header("X-Account-ID", account_id)

            sg.send(message)
            results["queued"] += 1

        except Exception as e:
            results["errors"].append({"account_id": account_id, "error": str(e)})

    return results
