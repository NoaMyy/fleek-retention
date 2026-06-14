#!/usr/bin/env python3
"""
Fleek Retention Pipeline — single entry point.

Usage:
  python3 run.py --input data/portfolio.xlsx
  python3 run.py --input data/portfolio.xlsx --new-batch data/new.xlsx
  python3 run.py --input data/portfolio.xlsx --draft-messages
  python3 run.py --input data/portfolio.xlsx --draft-messages --max-drafts 20
  python3 run.py --input data/portfolio.xlsx --draft-messages --push-sendgrid
"""
import argparse
import os
import sys
import time

from dotenv import load_dotenv

load_dotenv()


def main():
    parser = argparse.ArgumentParser(description="Fleek Retention Pipeline")
    parser.add_argument("--input", required=True, help="Path to portfolio Excel file")
    parser.add_argument("--new-batch", default=None, help="Path to new batch Excel file")
    parser.add_argument("--draft-messages", action="store_true", help="Draft messages via Claude API")
    parser.add_argument("--max-drafts", type=int, default=None, help="Cap number of accounts to draft for")
    parser.add_argument("--push-sendgrid", action="store_true", help="Push drafts to SendGrid")
    parser.add_argument("--dry-run", action="store_true", help="Skip API calls; use placeholders")
    parser.add_argument("--contacts", default="data/contacts.csv", help="Path to contacts CSV")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"[error] Portfolio file not found: {args.input}")
        sys.exit(1)

    # --- 1. Clean ---
    print("[1/5] Cleaning portfolio data...")
    from pipeline.clean import load_and_clean
    df = load_and_clean(args.input, new_batch_path=args.new_batch)
    print(f"      {len(df)} accounts loaded.")

    # --- 2. Filter to new accounts only (for processing) ---
    from pipeline.send_log import filter_new_accounts, mark_accounts_processed
    df_new = filter_new_accounts(df)
    print(f"      {len(df_new)} new (unprocessed) accounts this run.")

    if df_new.empty:
        print("      All accounts already processed. Use --new-batch to add fresh accounts.")
        # Still regenerate output from full df
    else:
        df_to_process = df_new
        df_to_process = df_to_process.reset_index(drop=True)

        # --- 3. Segment ---
        print("[2/5] Segmenting accounts...")
        from pipeline.segment import segment
        df_to_process = segment(df_to_process)
        counts = df_to_process["segment"].value_counts().to_dict()
        for seg, n in sorted(counts.items()):
            at_risk = (df_to_process["at_risk"] & (df_to_process["segment"] == seg)).sum()
            suffix = f" ({at_risk} AT_RISK)" if at_risk else ""
            print(f"      {seg}: {n}{suffix}")

        # --- 4. Prioritise ---
        print("[3/5] Prioritising...")
        from pipeline.prioritise import prioritise
        df_to_process = prioritise(df_to_process)

        # --- 5. Assign plays ---
        print("[4/5] Assigning plays...")
        from pipeline.plays import assign_plays
        df_to_process = assign_plays(df_to_process)

        # --- Merge contacts ---
        if os.path.exists(args.contacts):
            import pandas as pd
            contacts = pd.read_csv(args.contacts)
            df_to_process = df_to_process.merge(contacts, on="account_id", how="left")

        # --- Draft messages ---
        if args.draft_messages or args.dry_run:
            print("[4.5] Drafting messages via Claude API...")
            from agents.drafter import draft_messages
            df_to_process = draft_messages(
                df_to_process,
                max_accounts=args.max_drafts,
                dry_run=args.dry_run,
            )
            print(f"      Drafted for {(df_to_process['msg_variant_a'] != '').sum()} accounts.")
        else:
            df_to_process["msg_variant_a"] = ""
            df_to_process["msg_variant_b"] = ""
            df_to_process["touch_number"] = 1

        # --- Push to SendGrid ---
        if args.push_sendgrid:
            print("[4.6] Pushing drafts to SendGrid...")
            from pipeline.sendgrid_push import push_drafts
            result = push_drafts(df_to_process, dry_run=args.dry_run)
            print(f"      Queued: {result['queued']}, Skipped: {result['skipped']}, Errors: {len(result['errors'])}")

        # --- Write output ---
        print("[5/5] Writing Excel output...")
        from pipeline.output import write_excel
        path = write_excel(df_to_process)
        print(f"      Output: {path}")

        # --- Mark processed ---
        mark_accounts_processed(df_to_process["account_id"].tolist())
        print(f"      Marked {len(df_to_process)} accounts as processed.")

    print("\nDone.")


if __name__ == "__main__":
    main()
