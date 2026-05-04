# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common commands

```powershell
# Install
python -m pip install -r requirements.txt
python -m playwright install chromium

# Run offline smoke test (no LLM, no network)
python main.py --symbol 600519.SH --data-source mock --no-llm --no-pdf

# Run with QMT as primary data source
python main.py --symbol 600519.SH --data-source qmt

# Run with AKShare
python main.py --symbol 600519.SH --data-source akshare --no-llm

# Run tests
python -m pytest

# Streamlit dashboard
streamlit run apps/dashboard/Home.py
```

## Architecture

This is a quantitative research agent for Chinese A-shares (沪深京) and ETFs. Outputs a scored report with multi-role LLM debate, constrained by a local decision guard, rendered as JSON → Markdown → HTML → PDF.

### Pipeline (`services/orchestrator/single_asset_research.py`)

```
_run_load_asset_data()          # fetch raw data via provider
  → ResearchDataAggregator.enrich()   # resolve symbol, gather fundamentals/valuation/events, quality checks, evidence bundle
  → score_asset()                # 6-dimension quantitative scoring (stock or ETF path)
  → generate_debate_result()     # LLM bull/bear/risk/committee debate (optional)
  → apply_decision_guard()       # clamp LLM action to what local score allows
  → validate_protocol("final_decision", …)  # jsonschema validation
```

### Provider hierarchy (`services/data/`)

Three tiers, selected by `--data-source`:

| Tier | Provider | Role |
|------|----------|------|
| QMT/xtquant | `qmt_provider.py` | Primary — local Windows, reads XTData kline + financial tables |
| AKShare | `akshare_provider.py` | Fallback — 3 redundant sources (东方财富→腾讯→新浪) |
| Mock | `mock_provider.py` | Offline test — synthetic price data, low-confidence placeholders |

QMT failure automatically falls back to AKShare. Every provider returns a `ProviderResult` dataclass with `ProviderMetadata` (source, latency, errors) as defined in `provider_contracts.py`.

Specialized providers under `services/data/providers/` supply fundamentals (QMT financial tables), valuation (AKShare/东方财富), and events (AKShare announcements). Each has a corresponding normalizer in `services/data/normalizers/`.

### Scoring engine (`services/research/scoring_engine.py`)

Two code paths: `score_stock()` and `score_etf()`. Stock uses 6 weighted dimensions (config in `configs/scoring.yaml`): trend_momentum 20, liquidity 15, fundamental_quality 20, valuation 15, risk_control 20, event_policy 10. ETF reinterprets "fundamental" as fund size and "valuation" as premium/discount. Output is always 0–100 with rating tiers A/B+/B/C/D.

### Decision guard (`services/research/decision_guard.py`)

Determines `max_allowed_action` from local score: <55→avoid, 55–64→cautious watch, 65–74→watch, 75–84→accumulate, ≥85→buy. Risk officer constraints and data quality issues (missing sections, placeholders, severe events) further downgrade the cap. The LLM's `action` is clamped to this cap.

### Schema validation (`services/protocols/`)

Six JSON Schemas in `protocols/` validate pipeline outputs at multiple checkpoints via `jsonschema.Draft202012Validator`. Key constraint: `allow_trading` is hardcoded to `false` — this system never places orders.

## Important quirks

- **Proxy policy**: Market data providers run with proxy disabled (`disable_proxy_for_current_process()` called before importing AKShare in `akshare_provider.py`). DeepSeek API calls can optionally use a proxy. Never mix these — the proxy state is global to the process.

- **QMT column matching**: `_find_column()` uses case-insensitive matching because QMT column names vary across versions (`close` vs `收盘`).

- **QMT percentage ambiguity**: `_to_qmt_percent_ratio()` in the fundamental normalizer handles the case where some QMT financial fields return decimal ratios (0.18) while others return percentages (18.2). Values ≤0.2 are assumed to be decimal ratios and left as-is; larger values are divided by 100.

- **AKShare price column normalization**: AKShare returns Chinese column names (e.g. `收盘`). These are normalized to English keys (`close`, `open`, `high`, `low`, `volume`) in `akshare_provider.py`.

- **Event classification**: `EventNormalizer` uses Chinese keyword matching on announcement titles to categorize events (`"问询函"` → `regulatory_inquiry`, dividend keywords → `dividend`). New event types need keyword patterns added there.

- **Empty stub files**: `bull_analyst.py`, `bear_analyst.py`, `risk_officer.py`, `committee_secretary.py`, `factor_engine.py`, `risk_engine.py`, `json_guard.py` are empty files — placeholders for future decomposition. The current debate logic lives entirely in `debate_agent.py`.

- **Streamlit + Windows**: The Streamlit app sets `WindowsProactorEventLoopPolicy` before importing anything else, because Playwright's subprocess spawning fails with the default event loop on Windows.

- **No build system**: No `pyproject.toml`, `setup.py`, or `Makefile`. Dependencies are only in `requirements.txt`. The project runs directly via `python main.py`, not as an installed package.

- **`.env` is accidentally committed**: The `.gitignore` lists `.env`, but the actual `.env` was committed and contains a live `DEEPSEEK_API_KEY`. Do not add new secrets to `.env` — use `.env.example` as a template instead.
