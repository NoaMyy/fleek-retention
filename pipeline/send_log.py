"""
Send log — one row per message touch per account.
Persists to outputs/send_log.csv and outputs/processed_ids.json.
"""
import json
import os
from datetime import datetime, timezone

import pandas as pd


SEND_LOG_PATH = "outputs/send_log.csv"
PROCESSED_IDS_PATH = "outputs/processed_ids.json"

SEND_LOG_COLUMNS = [
    "account_id", "segment", "play", "rung", "touch_number",
    "variant", "send_status", "response", "sent_at",
]


def load_send_log() -> pd.DataFrame:
    if os.path.exists(SEND_LOG_PATH):
        return pd.read_csv(SEND_LOG_PATH)
    return pd.DataFrame(columns=SEND_LOG_COLUMNS)


def save_send_log(df: pd.DataFrame) -> None:
    os.makedirs("outputs", exist_ok=True)
    df.to_csv(SEND_LOG_PATH, index=False)


def load_processed_ids() -> set:
    if os.path.exists(PROCESSED_IDS_PATH):
        with open(PROCESSED_IDS_PATH) as f:
            return set(json.load(f))
    return set()


def save_processed_ids(ids: set) -> None:
    os.makedirs("outputs", exist_ok=True)
    with open(PROCESSED_IDS_PATH, "w") as f:
        json.dump(sorted(ids), f, indent=2)


def filter_new_accounts(df: pd.DataFrame) -> pd.DataFrame:
    """Return only accounts not yet in the processed set."""
    processed = load_processed_ids()
    return df[~df["account_id"].isin(processed)].copy()


def log_touch(
    account_id: str,
    segment: str,
    play: str,
    rung,
    touch_number: int,
    variant: str,
    send_status: str = "drafted",
    response: str = "",
) -> None:
    """Append a single touch row to the send log."""
    log = load_send_log()
    new_row = pd.DataFrame([{
        "account_id": account_id,
        "segment": segment,
        "play": play,
        "rung": rung or "",
        "touch_number": touch_number,
        "variant": variant,
        "send_status": send_status,
        "response": response,
        "sent_at": datetime.now(timezone.utc).isoformat(),
    }])
    log = pd.concat([log, new_row], ignore_index=True)
    save_send_log(log)


def get_touch_number(account_id: str) -> int:
    """Return next touch number for this account (1, 2, or 3)."""
    log = load_send_log()
    if log.empty or account_id not in log["account_id"].values:
        return 1
    existing = log[log["account_id"] == account_id]["touch_number"].max()
    return min(int(existing) + 1, 3)


def mark_accounts_processed(account_ids) -> None:
    processed = load_processed_ids()
    processed.update(account_ids)
    save_processed_ids(processed)
