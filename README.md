# Fleek Retention Pipeline

A buyer retention dashboard for a wholesale marketplace. Segments a portfolio of accounts, maps each buyer to a journey stage, prioritises who needs action, drafts A/B outreach messages via Claude, and pushes to SendGrid.

---

## Quick start

```bash
# 1. Clone and install
git clone <repo-url>
cd fleek-retention
pip install -r requirements.txt

# 2. Add credentials
cp .env.example .env
# Fill in ANTHROPIC_API_KEY and SENDGRID_API_KEY

# 3. Launch the dashboard
streamlit run app.py
```

Opens at `http://localhost:8501`. Upload a portfolio `.xlsx` to run the full pipeline.

---

## What it does

| Step | Description |
|---|---|
| **Clean** | Normalises ownership labels, fills gaps, deduplicates, merges into a cumulative master portfolio |
| **Segment** | Classifies accounts into Broker Managed, Healthy AM, True Headroom, Passive Buyer, Self-Serve Other |
| **Prioritise** | Ranks each segment by the criteria most relevant to its risk profile |
| **Journey** | Assigns broker migration stage (Broker Only → Building Habit) or self-serve buyer journey stage (Browser → Re-engagement) |
| **Play** | Sets a nudge feature per account (video call, offer, bundle, in-app chat) based on journey stage |
| **Draft** | Generates two A/B SMS variants per account via Claude using engagement psychology (social proof, scarcity, loss aversion) |
| **Push** | Sends drafted messages to SendGrid with structured subject line, category tag, and account header |

---

## Input format

Upload an `.xlsx` with an **Accounts** tab containing at minimum:

| Column | Description |
|---|---|
| `account_id` | Unique buyer identifier |
| `ownership` | `"Account Managed"` or `"Self Serve"` |
| `gmv_sep` … `gmv_feb` | Monthly GMV (6-month window) |
| `orders_6m` | Total orders in 6 months |
| `self_serve_orders` | Orders placed without AM |
| `manual_orders` | Orders placed via AM |
| `engagement_score` | Platform engagement index |
| `pdp_views_6m` | Product detail page views |
| `make_an_offer_6m` | Offers made |
| `chat_threads` | In-app chat conversations |
| `bundle_orders` | Bundle orders placed |
| `video_call_requests` | Video calls booked |

---

## Segmentation

| Segment | Criteria |
|---|---|
| **Broker Managed** | Account-managed + ≥50% broker reliance + low app activity |
| **Healthy AM** | Account-managed, not broker-reliant |
| **True Headroom** | Self-serve, engagement ≥ median, GMV < median |
| **Passive Buyer** | Self-serve, GMV ≥ median, engagement < median |
| **Self-Serve Other** | Self-serve, above median on both |

## Broker journey stages

| Stage | Broker % | Nudge direction |
|---|---|---|
| Broker Only | 100% | First self-serve order |
| Tried, Reverted | 75–99% | Restart self-serve habit |
| Gaining Momentum | 60–74% | Cross 50% threshold |
| Building Habit | 50–59% | Full graduation |

## Self-serve buyer journey stages

| Stage | Signal | Nudge |
|---|---|---|
| Browser | Low orders, no offers/chat yet | Video call |
| Consideration | Active on offers + chat, low order volume | Make an offer |
| Purchase | Regular buyer, high engagement | Bundle |
| Re-engagement | High past GMV, gone quiet | In-app chat |

---

## Project structure

```
app.py                  Streamlit dashboard
run.py                  Headless CLI entry point
pipeline/
  clean.py              Data cleaning + master portfolio merge
  segment.py            Segmentation logic
  prioritise.py         Ranking per segment
  plays.py              Journey stage + nudge assignment
  output.py             Excel export helpers
  send_log.py           Touch number tracking
agents/
  drafter.py            Claude API message drafter
  message_skill.md      Messaging best-practice framework
config/
  variants.json         Editable A/B message templates per stage
data/                   Portfolio files — gitignored
```

## Message templates

Templates live in `config/variants.json`. They are also editable live in the dashboard under **✏️ Message Templates** — changes take effect on the next draft run without restarting.

---

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes (for drafting) | Claude API key |
| `SENDGRID_API_KEY` | Yes (for push) | SendGrid API key |
| `SENDGRID_FROM_EMAIL` | Yes (for push) | Verified sender address |
