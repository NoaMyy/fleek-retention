# Fleek Retention Pipeline

A repeatable, agent-ready pipeline that manages a book of Fleek wholesale accounts — segmenting them, prioritising who needs action, assigning plays, drafting outreach messages, and writing a ranked Excel output.

---

## Quick Start

```bash
# 1. Install dependencies
pip3 install -r requirements.txt

# 2. Set environment variables
cp .env.example .env
# Edit .env with your ANTHROPIC_API_KEY and (optionally) SENDGRID_API_KEY

# 3. Run the pipeline
python3 run.py --input data/portfolio.xlsx

# 4. Drop in a new batch (won't duplicate already-processed accounts)
python3 run.py --input data/portfolio.xlsx --new-batch data/new.xlsx

# 5. Draft messages via Claude
python3 run.py --input data/portfolio.xlsx --draft-messages

# 6. Dry-run without any API calls
python3 run.py --input data/portfolio.xlsx --dry-run

# 7. Draft + push to SendGrid
python3 run.py --input data/portfolio.xlsx --draft-messages --push-sendgrid
```

Output lands in `outputs/fleek_retention_actions.xlsx`.

---

## Architecture

```
data/portfolio.xlsx
        │
        ▼
┌─────────────────┐
│  pipeline/clean │  Load Accounts + new_accounts tabs.
│                 │  Deduplicate (last row wins).
│                 │  Coerce types, fill blanks, derive fields.
└────────┬────────┘
         │  filter_new_accounts() — skip already-processed
         ▼
┌──────────────────┐
│ pipeline/segment │  Classify into 4 segments:
│                  │  BROKER_RELIANT, HEALTHY_AM,
│                  │  SELF_SERVE_HEADROOM, SELF_SERVE_MATURE.
│                  │  Flag declining HEALTHY_AM as AT_RISK.
└────────┬─────────┘
         ▼
┌────────────────────┐
│ pipeline/prioritise│  Sort within each segment.
│                    │  Broker: GMV ↓, broker% ↓.
│                    │  Self-serve: engagement ↓, GMV ↑.
│                    │  AM: AT_RISK first, then GMV ↓.
└────────┬───────────┘
         ▼
┌──────────────────┐
│  pipeline/plays  │  Assign play + rung per account.
│                  │  Broker: migration rung (4 rungs).
│                  │  Self-serve: feature nudge.
└────────┬─────────┘
         │
         ├──────────────────────────────────────┐
         ▼                                      ▼
┌──────────────────┐                  ┌──────────────────────┐
│  agents/drafter  │  2 SMS variants  │ pipeline/sendgrid_   │
│  (Claude API)    │  per account.    │ push  (optional)     │
│  Touch 1/2/3 +   │  Reads send log  └──────────────────────┘
│  segment angle.  │  for rung/touch.
└────────┬─────────┘
         ▼
┌─────────────────────┐
│   pipeline/output   │  Excel: Priority Actions / Full Portfolio / Plays
└─────────────────────┘
         │
         ▼
┌──────────────────────┐
│  outputs/            │  processed_ids.json  — dedup state
│                      │  send_log.csv        — every touch logged
│                      │  fleek_retention_actions.xlsx
└──────────────────────┘
```

**Where humans/agents intervene:**
- Review the Priority Actions tab each morning.
- Approve or edit message variants before sending.
- SendGrid push is manual (`--push-sendgrid`) — not automatic.

---

## Segments

| Segment | Criteria | Play |
|---|---|---|
| BROKER_RELIANT | AM-owned, broker_reliance ≥ 50%, low app/PDP activity | broker_migration |
| HEALTHY_AM | AM-owned, not broker-reliant | am_retention (or at_risk_save if declining) |
| SELF_SERVE_HEADROOM | Self-serve, GMV < £5k or high intent signals | self_serve_nudge |
| SELF_SERVE_MATURE | Self-serve, high activity | self_serve_nudge |

### Broker Migration Rungs

| Rung | ss_ratio | Message angle |
|---|---|---|
| not_started | 0 | Explain self-serve; zero jargon |
| stalled | 0–25% | Acknowledge the try; remove the blocker |
| moving | 25–40% | Celebrate progress; name the next step |
| nearly_graduated | 40%+ | One last nudge; offer a walkthrough |

### Self-Serve Feature Nudge

Best gap wins: `video_call` → `chat` → `bundle`.

---

## State & Idempotency

- `outputs/processed_ids.json` — set of account IDs already run through the pipeline. Re-running with the same input won't re-process them.
- `outputs/send_log.csv` — one row per touch per account. Touch number advances from 1 → 2 → 3 across runs.
- To reset a single account, remove its ID from `processed_ids.json`.

---

## Scaling to 30,000 Accounts

- All processing is vectorised via pandas — no per-row Python loops outside the Claude drafting step.
- Drafting is the only slow step (1 API call per account). Use `--max-drafts N` to cap each run.
- Excel output uses xlsxwriter (streaming-compatible). For very large portfolios, swap `pipeline/output.py` for a CSV writer with no code changes to the rest of the pipeline.
- State is stored in flat files. For 30k+ accounts, replace `processed_ids.json` with a SQLite DB — the `send_log.py` interface is unchanged.

---

## Files

```
run.py                    Entry point
pipeline/
  clean.py                Load, clean, deduplicate
  segment.py              Classify accounts into segments
  prioritise.py           Sort within segments
  plays.py                Assign play + rung/nudge
  send_log.py             State: processed IDs + touch log
  output.py               Write Excel workbook
  sendgrid_push.py        Push drafts to SendGrid
agents/
  drafter.py              Draft 2 SMS variants per account (Claude API)
  message_skill.md        Message best-practice rules
data/
  portfolio.xlsx          Input: Accounts + new_accounts tabs
  contacts.csv            Contact names + emails per account_id
outputs/
  processed_ids.json      Dedup state
  send_log.csv            Touch log
  fleek_retention_actions.xlsx  Output workbook
```
