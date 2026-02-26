# ForexMind — Cursor AI Context & Project Reference

### Read this file before making ANY change to this codebase.

---

## What This Product Is

ForexMind is a **multi-agent agentic AI platform** that generates personalised Forex trading signals. It combines macro-economic analysis, technical pattern detection, and personal trade history into a unified pipeline that gets smarter the more the user trades.

This is **not** a simple chatbot or signal copy service. It is a five-agent LangGraph pipeline backed by a RAG system built on Supabase pgvector. Every architectural decision has been made deliberately — do not change patterns without understanding why they exist.

---

## Core Rules for Cursor

1. **Read this file first.** Before touching any file, understand the architecture below.
2. **One task at a time.** Each Cursor prompt will give you one specific task. Do only that task. Do not refactor other files, rename things, or "improve" code that wasn't mentioned.
3. **Never hardcode secrets.** All API keys, URLs, and credentials come from `.env`. Never write a key directly in code.
4. **Never break the agent pipeline.** The LangGraph graph in `backend/agents/graph.py` is the central nervous system. If you touch it, be surgical.
5. **Preserve error handling.** Every agent has try/except with fallback logic. Never remove or simplify error handling.
6. **Ask before adding dependencies.** Do not add new pip packages without it being specified in the prompt.
7. **Type hints always.** All Python functions must have type hints.
8. **Langfuse on every agent.** Every agent function must keep its `@observe` decorator. Never remove it.

---

## Repository Structure

```
forexmind/
│
├── CURSOR.md                        ← THIS FILE — read before every change
├── .env                             ← Never commit. All secrets live here.
├── .env.example                     ← Committed. Shows all required keys, no values.
├── .gitignore
├── README.md
├── requirements.txt
│
├── streamlit_app.py                 ← Phase 1 & 2 UI. Single file. Connects to Railway backend.
│
├── backend/
│   ├── main.py                      ← FastAPI app. All endpoints defined here.
│   ├── Procfile                     ← Railway deployment: web: uvicorn main:app
│   ├── requirements.txt
│   │
│   ├── agents/
│   │   ├── graph.py                 ← LangGraph StateGraph. The pipeline orchestrator.
│   │   ├── macro_agent.py           ← RBA/Fed/ECB sentiment → hawkish/dovish/neutral
│   │   ├── technical_agent.py       ← OANDA price data → setup detection
│   │   ├── journal_agent.py         ← User trade history → win-rate gate + pattern analysis
│   │   ├── coach_agent.py           ← Synthesis + 3-condition gate → should_trade decision
│   │   └── signal_agent.py          ← Structured signal JSON output
│   │
│   ├── rag/
│   │   ├── ingest.py                ← Chunk + embed + insert into Supabase pgvector
│   │   ├── retriever.py             ← Query vector store with freshness check
│   │   ├── cache.py                 ← Agent response cache using Supabase agent_cache table
│   │   └── sources/
│   │       ├── rba_scraper.py       ← Primary scraper + RSS fallback + NewsAPI fallback
│   │       ├── forexfactory.py      ← Economic calendar scraper + fallback
│   │       └── price_data.py        ← OANDA API price fetcher
│   │
│   ├── db/
│   │   ├── supabase_client.py       ← Single Supabase client instance (service role key)
│   │   └── schema.sql               ← All table definitions. Run once in Supabase SQL editor.
│   │
│   ├── evals/
│   │   ├── signal_evaluator.py      ← Auto-resolve signal outcomes via OANDA 24h after signal
│   │   └── rag_evaluator.py         ← Weekly RAGAS batch evaluation
│   │
│   └── monitoring/
│       ├── health_check.py          ← Check all sources, log to pipeline_health table
│       └── alerts.py                ← Email alert when pipeline_health status = failed
│
└── frontend/                        ← Empty until Phase 3 (Month 6). Next.js goes here.
```

---

## The Five Agents — What Each Does

### 1. MacroAgent (`macro_agent.py`)

- **Model:** Gemini Flash 2.0 (free tier)
- **Input:** Currency pair
- **Process:** Queries Supabase pgvector for recent RBA/Fed/ECB statements → classifies sentiment
- **Output:** `{ sentiment: "hawkish"|"dovish"|"neutral", confidence: float 0-1, source_docs: list }`
- **Langfuse:** Traced with `@observe(name="macro_agent")`

### 2. TechnicalAgent (`technical_agent.py`)

- **Model:** Gemini Flash 2.0 (free tier)
- **Input:** Currency pair + macro_sentiment from state
- **Process:** Fetches OANDA H1 candles → detects setup (breakout/mean-reversion/trend)
- **Output:** `{ setup: str, direction: "BUY"|"SELL", quality: float 0-1 }`
- **Langfuse:** Traced with `@observe(name="technical_agent")`

### 3. JournalAgent (`journal_agent.py`)

- **Model:** GPT-4o Mini
- **Input:** Pair + setup type + user_id
- **Process:** Queries user's embedded trade history → calculates win rate → applies mode gate
- **Win-rate gate:**
  - < 30 trades → mode = "market_patterns"
  - ≥ 30 trades AND win rate < 52% → mode = "market_patterns"
  - ≥ 30 trades AND win rate ≥ 52% → mode = "personal_edge"
- **Output:** `{ mode: str, win_rate: float, pattern_notes: str, trade_count: int }`
- **Langfuse:** Traced with `@observe(name="journal_agent")`

### 4. CoachAgent (`coach_agent.py`)

- **Model:** Claude Sonnet (best reasoning — worth the cost)
- **Input:** Full state with all three previous agent outputs
- **3-condition gate (all must pass to generate signal):**
  1. `macro_sentiment.confidence > 0.5`
  2. `technical_setup.quality > 0.6`
  3. No `error` field in current state
- **Output:** `{ coaching_note: str, should_trade: bool }`
- **Langfuse:** Traced with `@observe(name="coach_agent")`

### 5. SignalAgent (`signal_agent.py`)

- **Model:** GPT-4o Mini (structured output)
- **Only runs if** `should_trade = True`
- **Output (saved to signal_outcomes table):**

```json
{
  "pair": "AUD/USD",
  "direction": "BUY",
  "entry_price": 0.6482,
  "take_profit": 0.6528,
  "stop_loss": 0.6459,
  "risk_reward": 2.0,
  "confidence_pct": 73,
  "reasoning": "...",
  "mode": "market_patterns",
  "generated_at": "2026-02-25T09:14:00Z"
}
```

- **Langfuse:** Traced with `@observe(name="signal_agent")`

---

## LangGraph State

```python
class ForexState(TypedDict):
    pair:             str
    macro_sentiment:  Optional[dict]
    technical_setup:  Optional[dict]
    user_patterns:    Optional[dict]
    coach_advice:     Optional[str]
    final_signal:     Optional[dict]
    should_trade:     bool
    error:            Optional[str]
```

**Pipeline flow:**

```
macro → technical → journal → coach → [gate] → signal → END
                                             ↘ END (if should_trade = False)
```

---

## Database Tables (Supabase pgvector)

| Table             | Purpose                                                                       |
| ----------------- | ----------------------------------------------------------------------------- |
| `forex_documents` | All embedded RAG content. Has `source`, `is_stale`, `embedding` (vector 1536) |
| `agent_cache`     | Cached agent results keyed by pair + time window. Reduces LLM costs 60-70%    |
| `user_trades`     | MT4/MT5 imported trade history per user. Powers JournalAgent                  |
| `pipeline_health` | Every scraper/agent run logs here. Status = ok/failed/stale                   |
| `signal_outcomes` | Every generated signal. Auto-resolved 24h later by signal_evaluator.py        |
| `eval_results`    | Weekly RAGAS scores stored for trend tracking                                 |

---

## Data Sources & Fallback Chains

Every source has 3 layers. Never fail silently — always log to `pipeline_health`.

| Source            | Primary              | Fallback 1      | Fallback 2                           |
| ----------------- | -------------------- | --------------- | ------------------------------------ |
| RBA data          | rba.gov.au scraper   | RBA RSS feed    | NewsAPI search                       |
| Economic calendar | ForexFactory scraper | FF API endpoint | Manual major events                  |
| Price data        | OANDA v20 API        | —               | Raise error (no fallback for prices) |
| News              | NewsAPI              | Google News RSS | —                                    |

---

## Deployment URLs

| Env   | Backend API                                      |
| ----- | ------------------------------------------------- |
| dev   | `http://localhost:8000`                           |
| prod  | `https://forexmind-production.up.railway.app`     |

Use `config.get_api_base_url()` or set `API_BASE_URL` in `.env` to switch.

---

## Environment Variables Required

```
# API (clients: Streamlit, scripts)
# API_BASE_URL=   # unset = dev; set to prod URL when needed

# Supabase
SUPABASE_URL=
SUPABASE_ANON_KEY=
SUPABASE_SERVICE_ROLE_KEY=

# OANDA (Demo account)
OANDA_API_KEY=
OANDA_ACCOUNT_ID=
OANDA_ENVIRONMENT=practice

# LLMs
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
GEMINI_API_KEY=

# Observability
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=https://cloud.langfuse.com

# Data
NEWSAPI_KEY=
```

---

## Observability Stack

| Tool                      | What it tracks                                                  | When                  |
| ------------------------- | --------------------------------------------------------------- | --------------------- |
| **Langfuse**              | Every agent call — input, output, latency, cost, model          | Real-time, every run  |
| **RAGAS**                 | RAG quality — context relevance, faithfulness, answer relevance | Weekly Sunday batch   |
| **signal_outcomes table** | Real signal win rate, auto-resolved via OANDA                   | 24h after each signal |
| **pipeline_health table** | Scraper + agent status, failure detection                       | Every pipeline run    |
| **Myfxbook**              | External verified track record (connected to broker)            | Phase 2 Month 2       |

### Langfuse target metrics

- Pipeline latency P95: **< 8 seconds**
- Cost per signal: **< $0.05 AUD**
- Agent error rate: **< 5%**

### RAGAS target scores

- Context relevance: **> 0.75**
- Faithfulness: **> 0.80**
- Answer relevance: **> 0.70**

### Signal accuracy target

- Rolling 30-day win rate: **> 55%**

---

## Intelligence Modes (JournalAgent Gate)

| Mode              | Condition                      | Behaviour                                              |
| ----------------- | ------------------------------ | ------------------------------------------------------ |
| `market_patterns` | < 30 trades OR win rate < 52%  | Uses statistically validated universal setups from RAG |
| `personal_edge`   | ≥ 30 trades AND win rate ≥ 52% | Signals personalised to user's proven patterns         |

---

## LLM Cost Strategy

| Agent          | Model            | Reason                         | Approx cost |
| -------------- | ---------------- | ------------------------------ | ----------- |
| MacroAgent     | Gemini Flash 2.0 | Classification task, free tier | $0.000      |
| TechnicalAgent | Gemini Flash 2.0 | Structured data, free tier     | $0.000      |
| JournalAgent   | GPT-4o Mini      | Needs reasoning, cheap         | ~$0.001     |
| CoachAgent     | Claude Sonnet    | Best synthesis quality         | ~$0.012     |
| SignalAgent    | GPT-4o Mini      | Structured JSON output         | ~$0.003     |

**Caching strategy:** MacroAgent results cached 6h, TechnicalAgent 1h, JournalAgent 24h. Same analysis not regenerated per user within cache window. Target: < $0.016/signal at scale.

---

## UI Reference

The UI reference for Streamlit (Phase 1-2) is in `/forexmind_ui_reference_v2.html`.

**Five pages:**

1. **Signals** — Signal Output tab, Agent Breakdown tab, Signal History tab (tabs only visible on this page)
2. **Monitoring** — Pipeline health + Langfuse metrics + RAGAS scores only. No signal accuracy here.
3. **Accuracy** — Signal win rates by pair and session. Single source of truth for performance.
4. **Journal** — CSV import + weekly AI coaching report only. No trade table (that's Signal History).
5. **Settings** — Agent toggles, pair/session config, API keys, notifications.

**API calls per page load:**

- Signals: 1 call (generate signal pipeline, on demand)
- Monitoring: 1 call (health + Langfuse + RAGAS — one endpoint)
- Accuracy: 1 call (signal_outcomes aggregate query)
- Journal: 0 new calls (coaching report cached from Sunday, stats from Accuracy query)
- Settings: 0 calls (local state only)
- Sidebar stats: 1 cached call at app load

---

## Current Phase

**Phase 1 — Week 1**

What is done:

- Repository structure created
- `.env` file configured
- OANDA demo account created (practice environment)
- OANDA API key and Account ID in `.env`

What is next:

- Supabase pgvector setup (run schema.sql)
- LlamaIndex ingestion pipeline
- RBA scraper with fallback
- ForexFactory scraper with fallback
- Langfuse account + @observe test

---

## What NOT to Do

- Do not use `WidthType.PERCENTAGE` anywhere
- Do not store secrets in code
- Do not create a new Supabase client per request — use the singleton in `db/supabase_client.py`
- Do not call OANDA API for historical RAG data — it is only called at signal generation time for live prices
- Do not add Redis yet — caching uses the `agent_cache` Supabase table until Phase 3
- Do not build the Next.js frontend yet — that is Phase 3 Month 6
- Do not remove `@observe` decorators from agents
- Do not skip the 3-condition gate in CoachAgent
- Do not generate a signal when `should_trade = False`
- Do not use `print()` for logging — use Python `logging` module

---

## How to Run Locally

```bash
# Backend
cd backend
uvicorn main:app --reload --port 8000

# Streamlit UI
streamlit run streamlit_app.py
```

---

_ForexMind CURSOR.md v1.0 · February 2026_
_Update the "Current Phase" section after completing each week._
