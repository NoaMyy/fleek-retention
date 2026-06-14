"""
Push drafted messages to SendGrid as drafts (single-send / marketing campaign drafts).
Requires SENDGRID_API_KEY and SENDGRID_FROM_EMAIL in environment.
"""
import os

import pandas as pd


def push_drafts(df: pd.DataFrame, variant: str = "A", dry_run: bool = False) -> dict:
    """
    For each row with a drafted message, create a SendGrid Single Send draft.
    Returns summary dict {queued: int, skipped: int, errors: list}.
    """
    api_key = os.getenv("SENDGRID_API_KEY", "")
    from_email = os.getenv("SENDGRID_FROM_EMAIL", "retention@example.com")

    if not api_key:
        print("  [sendgrid] No SENDGRID_API_KEY — skipping push.")
        return {"queued": 0, "skipped": len(df), "errors": []}

    try:
        import sendgrid
        from sendgrid.helpers.mail import Mail
        sg = sendgrid.SendGridAPIClient(api_key=api_key)
    except ImportError:
        print("  [sendgrid] sendgrid package not installed — skipping push.")
        return {"queued": 0, "skipped": len(df), "errors": []}

    msg_col = "msg_variant_a" if variant.upper() == "A" else "msg_variant_b"
    results = {"queued": 0, "skipped": 0, "errors": []}

    for _, row in df.iterrows():
        msg = str(row.get(msg_col, "")).strip()
        if not msg:
            results["skipped"] += 1
            continue

        contact_name = str(row.get("contact_name", row["account_id"]))
        email = str(row.get("email", ""))
        if not email or "@" not in email:
            results["skipped"] += 1
            continue

        subject = f"[Fleek] {row['play']} — {row['account_id']}"

        if dry_run:
            print(f"  [dry-run] Would send to {email}: {msg[:60]}...")
            results["queued"] += 1
            continue

        try:
            message = Mail(
                from_email=from_email,
                to_emails=email,
                subject=subject,
                plain_text_content=msg,
            )
            sg.send(message)
            results["queued"] += 1
        except Exception as e:
            results["errors"].append({"account_id": row["account_id"], "error": str(e)})

    return results
