# Capula Risk — CTD Basis Monitor: Graduate Notes

---

## 1. Problem Statement

### Background

Fixed income relative value (FIRV) desks at funds like Capula Investment Management
(~$31.8B AUM, "the largest player in futures basis trades") run one of the most
analytically intensive morning workflows in systematic trading:

> Every trading day before the open, an analyst must determine:
> - Which Treasury bond is cheapest-to-deliver (CTD) against the active futures contract?
> - How far is the CTD from switching to the runner-up?
> - How does the basis behave across a range of yield scenarios?
> - Is today's carry positive after overnight financing?

This morning brief — assembling basket rankings, basis percentiles, CTD proximity
signals, carry decomposition, and scenario analysis — takes a junior analyst 20–30
minutes of manual work across Bloomberg screens and spreadsheets.

### Root Pain Points

| Pain Point | Impact |
|---|---|
| Fragmented data sources | Analyst manually tabs between Bloomberg basket screens, repo sheets, and scenario models |
| No memory / percentile context | Hard to know if today's 4bps spread is tight or normal without pulling history |
| Slow scenario turnaround | Running a ±100bps yield grid manually is error-prone and time-consuming |
| No synthesis layer | Even when the numbers are assembled, translating them into a PM-ready brief requires interpretation |
| Latency | Decisions can't wait 20–30 min; if CTD is close to switching, the desk needs to know at 7:45am |

### Opportunity

LLMs in 2025 are becoming workflow agents, not just chatbots. Bloomberg, FactSet, and
LSEG are all building MCP integrations — giving models access to structured market data.
The missing piece is not a better chatbot; it is a model that can *act* on structured
financial data and synthesize it into actionable narrative in seconds.

**The specific opportunity**: Give Claude direct, structured access to the daily CTD
basis analytics — not as a static RAG document, but via callable tools that query a
live database — and let it replace the manual morning brief entirely.

---

## 2. Solution Overview

**CTD Basis Monitor** is a morning workflow system for US Treasury futures basis desks.
Its core component is an MCP (Model Context Protocol) server that exposes eight
structured tools. When a portfolio manager asks *"What's the TY basis this morning?"*,
Claude calls these tools in parallel, queries the historical basis database, and returns
a PM-ready brief in ~10 seconds:

> *"Net basis on the 4% Feb-33 is 2.3 ticks — 7.9th percentile of the last 90 days
> (historically tight). CTD transition risk is LOW: the implied repo spread to the
> 4.5% Aug-34 is 426bps and widening, with no switch risk in a ±100bp move.
> At a 5.3% repo rate, 3-month carry on the CTD is −22bps — negative carry, typical
> for this rate environment."*

The system has four layers:

```
┌─────────────────────────────────────────────────────────┐
│  Claude (via MCP client)   ←→   MCP Server (8 tools)    │  Synthesis layer
├─────────────────────────────────────────────────────────┤
│  Streamlit Dashboard (4 pages, dark theme)               │  Visual monitoring
├─────────────────────────────────────────────────────────┤
│  SQLite DB (basis_snapshots + ctd_log)                   │  Persistence layer
├─────────────────────────────────────────────────────────┤
│  Core Analytics (pricing, carry, CTD, scenarios)         │  Quant engine
└─────────────────────────────────────────────────────────┘
```

---

## 3. Architecture: Component-by-Component

### 3.1 Quant Analytics Engine — `core/`

Pure Python library. No I/O, no database, no external dependencies beyond numpy/scipy/pandas.
This is the computational foundation for all downstream layers.

| Module | Purpose | Key Output |
|---|---|---|
| `core/basket.py` | Enumerate TY delivery basket (12 bonds, coupons 3.625–4.625%, maturities Dec 2032–Jun 2036) from Treasury Direct API or hardcoded fallback | `get_basket()` → list[dict]; `conversion_factor()` per CME formula |
| `core/pricing.py` | Vectorized bond pricing (DCF, semi-annual, numpy dot product) | `price_bond()`, `dv01()`, `modified_duration()`, `convexity()`, `ytm()` (Brent's method) |
| `core/carry.py` | Cash-futures carry analytics with US Treasury conventions | `carry()` ACT/365 coupon / ACT/360 repo; `implied_repo()`; `net_basis()`; `gross_basis()` |
| `core/ctd.py` | CTD ranking + analytical transition threshold | `rank_basket()` → DataFrame; `ctd_transition_threshold()` → exact F* in closed form; `basis_dv01()` |
| `core/scenario.py` | Parallel yield shock repricing | `scenario_grid()` → (summary_df, heatmap_df); `shocked_basket()` per shift |

**The CTD transition threshold formula** is the analytically most important function:

```
F* = (CA_B·P_A − CA_A·P_B) / (CF_A·P_B − CF_B·P_A)

where CA_x = P_x · coupon_x · (days/365)   [ACT/365 coupon accrual]

This is an exact closed-form solution derived by setting IR_A(F*) = IR_B(F*)
and solving for F. Not an approximation.
```

---

### 3.2 Data Layer — `data/`

Persistence and ingestion. Wraps SQLite with a structured read/write API.

**Database schema** (`basis_monitor.db`, currently 268K, 1080 rows):

```sql
-- One row per bond per day per contract
CREATE TABLE basis_snapshots (
    snapshot_dt      TEXT,      -- ISO date "YYYY-MM-DD"
    contract         TEXT,      -- e.g. "TYM26"
    cusip            TEXT,
    coupon           REAL,      -- decimal 0.04375
    maturity         TEXT,
    cash_price       REAL,
    futures_price    REAL,
    conv_factor      REAL,
    gross_basis      REAL,      -- price points
    net_basis        REAL,      -- price points
    implied_repo     REAL,      -- decimal 0.0505
    is_ctd           INTEGER,
    repo_rate        REAL,
    days_to_delivery INTEGER,
    UNIQUE(snapshot_dt, contract, cusip)
);

-- One row per CTD identity switch
CREATE TABLE ctd_log (
    change_dt               TEXT,
    contract                TEXT,
    prev_ctd_cusip          TEXT,
    new_ctd_cusip           TEXT,
    implied_repo_spread_bps REAL   -- how tight was the spread at time of switch
);
```

**BasisDB class** (`data/db.py`) provides the write API:
- `write_snapshot()` — accepts a `rank_basket()` DataFrame, writes all bonds, auto-detects CTD transitions and logs them
- `get_current_basket()` — latest snapshot ranked by implied_repo DESC
- `get_basis_history()` — 90-day history with rolling 20d MA and percentile rank

**Seed script** (`data/seed.py`): generates 90 days of synthetic TYM26 history using
a seeded random walk (RNG seed=42, base 10Y yield 4.50%, repo 5.30%, daily σ 7bps).
Produces realistic implied_repo values 3.5–5.5% and 1–2 CTD transitions.

**Live ingest script** (`data/ingest.py`): fetches live FRED yield curve, prices basket,
writes snapshot to DB.

**FRED client** (`data/fred_client.py`): fetches 6 US Treasury yield series from FRED
(DGS3MO, DGS2, DGS5, DGS7, DGS10, DGS30), 5-minute cache, returns:
```python
{"3M": 0.045, "2Y": 0.032, "5Y": 0.035, "7Y": 0.039, "10Y": 0.044, "30Y": 0.049}
```

---

### 3.3 MCP Server — `mcp_server/` — THE MAIN PRODUCT

This is the primary selling point. It is a FastMCP server exposing 8 callable tools
so Claude can query the basis database and synthesize morning briefs.

**Why MCP is the right pattern here:**
- The LLM cannot access the SQLite database without the tools — data is opaque to the model
- The LLM's value is synthesis: connecting percentile rank + trend + scenario crossover
  into a narrative, not doing the arithmetic
- This directly mirrors what Bloomberg Terminal's AI integrations (2025) are building:
  structured data → tool call → LLM synthesis

**Server entry point:** `python -m mcp_server.server` (stdio transport, compatible with
Claude Desktop's MCP config)

**Read-only SQL layer** (`mcp_server/db_client.py`): all SQL with window functions
lives here. Tools never issue raw SQL. Key queries use SQLite ≥ 3.25.0 window functions
(`PERCENT_RANK()`, `ROW_NUMBER()` in CTEs, `AVG() OVER ... ROWS BETWEEN`).

**Critical SQL fix implemented** — the original `BasisDB.get_transition_proximity()`
used `NTH_VALUE(implied_repo, 2) OVER ... GROUP BY` which always returns NULL
(window runs post-grouping on a 1-row partition). Rewritten in `db_client.py` with
a `ROW_NUMBER()` CTE that correctly identifies the 2nd-ranked bond per day.

#### The 8 MCP Tools

| # | Tool | Input | Core Signal | DB? | FRED? |
|---|---|---|---|---|---|
| 1 | `get_current_basket` | contract | Full basket ranked by implied_repo; CTD flagged; net_basis in pts + ticks | ✓ | — |
| 2 | `get_basis_history` | cusip, contract, days | 90-day net basis series + 20d MA + percentile rank | ✓ | — |
| 3 | `get_basis_percentile` | contract, days | Where today's CTD net basis sits in its 90-day distribution | ✓ | — |
| 4 | `get_ctd_transitions` | contract | Historical CTD switch log + spread at time of switch | ✓ | — |
| 5 | `get_transition_proximity` | contract | Implied repo spread (CTD vs runner-up), trend NARROWING/WIDENING/STABLE, risk flag LOW/ELEVATED/CRITICAL | ✓ | — |
| 6 | `run_scenario_grid` | contract, shifts_bps | Basket re-ranked under parallel yield shifts; CTD identity + spread per scenario; `ctd_changed` bool | ✓ | ✓ |
| 7 | `get_ctd_transition_threshold` | contract | Exact F* (futures price at which CTD switches) derived in closed form; distance from current | ✓ | — |
| 8 | `get_carry_roll` | cusip, contract, repo_rate | 3M/6M: coupon accrual (ACT/365), financing (ACT/360), net carry, roll-down, total; forward breakeven YTM | ✓ | ✓ |

**Risk flag logic (Tool 5 `get_transition_proximity`):**
- CRITICAL: implied repo spread < 5 bps → CTD switch imminent
- ELEVATED: 5–15 bps → heightened monitoring
- LOW: > 15 bps → no near-term risk

**Trend logic:** compare current spread to 5 days ago; NARROWING if delta < −2bps, WIDENING if > +2bps, STABLE otherwise.

**FRED dependency:** Tools 6 and 8 require live FRED data. If unavailable (network/proxy), both return a structured `{"error": "FRED data unavailable..."}` — graceful degradation. The 6 DB-only tools always work offline.

**Unit conventions (explicit throughout):**
- `implied_repo_pct` — percentage (e.g., 5.052 = 5.052%)
- `net_basis_pts` — price points (TY: 1 point = 32 ticks)
- `net_basis_ticks` — 32nds (= net_basis_pts × 32)
- `spread_bps` — basis points (1 bps = 0.01%)
- Day-count: ACT/365 for coupon accrual, ACT/360 for repo (US Treasury market convention)

---

### 3.4 Frontend Dashboard — `dashboard/` (Streamlit)

4-page Streamlit app with dark theme (GitHub Dark palette). No HTML/CSS/JS files —
all styling is Python-generated inline CSS injected via `st.markdown()`.

**Run:** `streamlit run dashboard/app.py` → http://localhost:8501

**Color palette:**
```python
C_BLUE   = "#58a6ff"   # primary accent (CTD highlight, links)
C_RED    = "#f85149"   # risk / negative carry
C_GREEN  = "#3fb950"   # safe / positive carry
C_AMBER  = "#d29922"   # warning / elevated risk
C_PURPLE = "#bc8cff"   # secondary accent
```

| Page | Route | Content |
|---|---|---|
| **Landing** | `/` (`app.py`) | Hero header; DB status bar; 4 KPI cards (CTD bond, implied repo, spread to runner, net basis); delivery basket table with inline bar chart; 4 navigation cards |
| **Basis Monitor** | `01_basis_monitor.py` | Risk banner (spread-based); metric cards; 2-column layout: basket table (left) + 90-day net basis chart with 20d MA overlay (right) |
| **Delivery Basket** | `02_delivery_basket.py` | Full analytics table (rank, price, CF, carry, net basis, implied repo); CTD transition risk gauge; F* threshold display with distance |
| **CTD History** | `03_ctd_history.py` | Gantt-style timeline of CTD ownership; transitions table; 20-day implied repo spread chart |
| **Scenario Grid** | `04_scenario_grid.py` | Heatmap (bonds × yield shifts, color = implied repo %); CTD change summary table; range toggle |

**Shared sidebar inputs** (all pages): futures price, repo rate, days to delivery, flat yield override.

**Shared helpers** (`shared.py`): `inject_css()`, `sidebar_inputs()`, `get_db()`, `fresh_basket()`, `banner()`, `sh()`, `page_header()`, `mc()` (metric card HTML).

---

### 3.5 External APIs

| API | Purpose | Auth | Caching | Fallback |
|---|---|---|---|---|
| FRED (St. Louis Fed) | Live US Treasury yield curve (DGS3MO, DGS2, DGS5, DGS7, DGS10, DGS30) | `FRED_API_KEY` env var | 5 minutes in-process | Hardcoded curve; FRED-dependent MCP tools return structured error |
| US Treasury Direct API | Delivery basket enumeration (bond metadata) | None (public) | `get_basket(use_api=False)` hardcoded fallback | 12-bond hardcoded snapshot |

---

## 4. Technology Stack

| Layer | Technology | Rationale |
|---|---|---|
| Language | Python 3.11 | Required for `float | None` syntax; sqlite3 ships with SQLite ≥ 3.39 (window functions) |
| Analytics | numpy, scipy, pandas | Vectorized pricing (10–50x speedup in scenario loops); Brent's method for YTM solver |
| Database | SQLite (stdlib) | Zero-dependency, file-based; WAL mode for concurrent reads; sufficient for 90-day rolling window (~1080 rows) |
| MCP framework | `mcp` (FastMCP) | Anthropic's open standard; stdio transport; compatible with Claude Desktop |
| Dashboard | Streamlit ≥ 1.32 | Multi-page support; rapid iteration; dark theme via injected CSS |
| Charting | Plotly ≥ 5.20 | Interactive Gantt, heatmaps, time series with overlays |
| HTTP | requests | FRED API calls; `python-dotenv` for key loading |
| Testing | pytest | 8 test files covering all analytics, DB, and pipeline |

---

## 5. Workflow: How It All Fits Together

### Morning Brief Workflow (MCP path)

```
PM: "What's the TY basis this morning?"
       │
       ▼
Claude (via MCP client)
  ├── Tool 1: get_current_basket("TYM26")        ─── parallel ──┐
  ├── Tool 5: get_transition_proximity("TYM26")  ─── parallel ──┤ ← all 3 at once
  └── Tool 6: run_scenario_grid("TYM26")         ─── parallel ──┘
       │
       ▼  [if transition proximity is ELEVATED or CRITICAL]
  └── Tool 2: get_basis_history(ctd_cusip, "TYM26", 90)
       │
       ▼
Claude synthesizes:
  "Net basis on the 4% Feb-33 is 2.3 ticks — 7.9th pctile (90d, historically
   tight). CTD transition risk is LOW: spread to runner-up is 426bps and widening.
   No CTD switch in a ±100bp move. At repo 5.3%, 3M carry is −22bps."

Total: ~10 seconds vs 20–30 minutes manually.
```

### Data Pipeline (ingest path)

```
FRED API → fred_client.get_yield_curve()
         → price_bond() per bond per yield
         → rank_basket() → ranked DataFrame
         → BasisDB.write_snapshot() → SQLite
         → auto-detect CTD transition → ctd_log
```

### Dashboard Path

```
Streamlit → BasisDB.get_current_basket() → rank display
          → BasisDB.get_basis_history() → 90d chart
          → scenario_grid() (live, from sidebar inputs) → heatmap
          → ctd_transition_threshold() → F* display
```

---

## 6. Assumed Impact

### Analyst Productivity

| Task | Manual (current) | With CTD Monitor |
|---|---|---|
| Morning CTD brief | 20–30 min | ~10 sec (Claude + MCP) |
| Scenario grid (±100bp) | 5–15 min in Bloomberg | ~3 sec (Tool 6) |
| CTD switch risk check | 5–10 min | ~2 sec (Tool 5) |
| Carry decomposition | 5–10 min | ~2 sec (Tool 8) |
| **Total morning setup** | **~50 min** | **~15 sec** |

### Strategic Value

- **Analyst leverage:** One analyst can monitor 3–5 futures contracts (TY, TU, FV, US)
  with the same effort previously required for one
- **PM responsiveness:** Risk signals (CRITICAL proximity flag) surface in real-time
  rather than at the end of the morning setup
- **Reproducibility:** All signals are computed from the same formulas every day —
  no manual errors, no formula drift across analyst handoffs
- **MCP as workflow primitive:** As Bloomberg and FactSet ship MCP integrations,
  this architecture is directly composable with live market data feeds, replacing the
  FRED proxy with real-time pricing

### Positioning

Capula is described as "the largest player in futures basis trades." This tool is
designed for exactly their morning workflow. More broadly, any FIRV desk running
Treasury, Bund, Gilt, or JGB basis trades faces the same morning brief problem —
the architecture generalises to any deliverable basket.

---

## 7. Challenges and Limitations

### Technical Challenges

| Challenge | Current Status | Production Resolution |
|---|---|---|
| **FRED yield proxy** | Tools 6 and 8 use FRED 10Y linearly interpolated to bond maturity — first-order approx | Replace with full Treasury curve (2s/5s/7s/10s/30s) and bond-specific market yields from Bloomberg BDS |
| **Static basket** | 12-bond TYM26 basket is hardcoded; no auto-update on rolls | Fetch from CME or Treasury Direct on contract roll (quarterly); add contract rollover logic |
| **Synthetic history** | DB seeded from random walk, not real prices | Backfill from Bloomberg historical data; ongoing live ingest via `data/ingest.py` |
| **Futures price input** | Hardcoded in seed; sidebar input in dashboard | Connect to live futures feed (e.g., CME DataMine or Bloomberg tick data) |
| **FRED API rate limits** | 5-minute cache insufficient for intraday | Enterprise FRED or replace with Bloomberg `USGG10YR Index` query |
| **CTD transition threshold sign** | F* can be < current price (CTD stays dominant on rally); requires sign awareness | Compute both the upward and downward thresholds; UI should clearly flag which direction |

### Modelling Limitations

| Limitation | Note |
|---|---|
| **Delivery option not priced** | Net basis ≠ 0 even at fair value; the residual is the delivery option value (wildcard + quality options). Not modelled. |
| **No accrued interest in cash price** | `price_bond()` returns clean price; accrued interest treated separately. Consistent internally but must be explicit in documentation. |
| **Implied repo is a proxy** | Assumes no interim coupon during the carry period (ACT/365 approximation). For bonds with coupons between trade date and delivery, this introduces error. |
| **Convexity in scenarios** | Scenario grid uses price_bond (full DCF repricing), not duration + convexity approximation. This is correct, but holds the yield curve shape constant — parallel shifts only. Curve steepening/flattening scenarios not modelled. |
| **Single contract only** | Currently built for TYM26 only. TU (2Y), FV (5Y), US (30Y) have different basket structures and day-count conventions. |

### Operational Challenges

| Challenge | Mitigation |
|---|---|
| **MCP server startup latency** | Server initialises BasisDB on startup; if DB doesn't exist, tools return structured errors rather than crashing |
| **FRED network unavailability** | `_try_get_fred_curve()` wrapper catches all exceptions; FRED-dependent tools return `{"error": "FRED data unavailable"}` |
| **SQLite concurrency** | WAL mode enabled; read queries from dashboard and MCP server can run concurrently with ingest writes |
| **Data freshness** | DB shows last snapshot date on landing page; Claude reads `snapshot_dt` from tool output and can flag stale data |

---

## 8. Future Roadmap

### Phase 1 (current — MVP)
✓ TYM26 delivery basket analytics
✓ 90-day synthetic history in SQLite
✓ 8-tool MCP server (CTD, basis, carry, scenarios)
✓ 4-page Streamlit dashboard
✓ Exact CTD transition threshold (closed form)

### Phase 2 (production hardening)
- Live FRED ingest scheduled daily (cron or Prefect)
- Bloomberg BDS integration replacing FRED (production-grade yields)
- Contract roll logic (TYM26 → TYU26 at expiry)
- Backtested CTD accuracy metrics vs actual CME deliveries
- Add TU (2Y) and US (30Y) contracts with their basket logic

### Phase 3 (desk integration)
- MCP tool: `get_morning_brief(contract)` — single-shot call returning full narrative
- MCP tool: `compare_contracts(contracts)` — cross-contract basis comparison
- MCP tool: `check_repo_richness(cusip)` — compare implied repo to GC repo rate
- Alert system: push notification when risk_flag upgrades to CRITICAL
- Historical backtesting view: replay any day's basket and compare to delivery outcome

### Phase 4 (expand asset class)
- Bund futures (FGBL): German Bund delivery basket
- Gilt futures (L): UK Gilt delivery basket
- JGB futures: Japanese Government Bond basket
- Unified FIRV morning brief across all four contracts

---

## 9. File Reference

```
fi_risk_dashboard/
├── core/
│   ├── basket.py          TY basket enumeration, conversion_factor(), bond_label()
│   ├── pricing.py         price_bond(), dv01(), ytm(), modified_duration()
│   ├── carry.py           carry(), implied_repo(), net_basis(), gross_basis()
│   ├── ctd.py             rank_basket(), ctd_transition_threshold(), basis_dv01()
│   └── scenario.py        scenario_grid(), shocked_basket()
├── data/
│   ├── db.py              BasisDB class, SQLite schema, write_snapshot()
│   ├── seed.py            Synthetic 90-day history seeder (RNG seed=42)
│   ├── ingest.py          Live FRED ingest CLI
│   └── fred_client.py     FRED API client (6 series, 5-min cache)
├── dashboard/
│   ├── app.py             Landing page (KPI cards, basket table, nav)
│   ├── shared.py          CSS, colors, helpers, sidebar_inputs()
│   └── pages/
│       ├── 01_basis_monitor.py     Live basket + 90d chart
│       ├── 02_delivery_basket.py   Full analytics + F* threshold
│       ├── 03_ctd_history.py       Gantt + transitions
│       └── 04_scenario_grid.py     Heatmap ±100bps
├── mcp_server/
│   ├── server.py          8 MCP tools (FastMCP)
│   ├── db_client.py       SQL query layer (window functions, ROW_NUMBER CTE)
│   └── fred_client.py     FRED wrapper (server-side)
├── tests/
│   └── test_*.py          8 test files (basket, carry, CTD, DB, ingest, pricing, scenario)
├── basis_monitor.db       SQLite DB (1080 rows, 90-day TYM26 history)
├── requirements.txt
└── README.md
```

---

## 10. Quick Verification

```bash
# 1. Re-seed with corrected futures price (if needed)
python -m data.seed --reset --days 90

# 2. Smoke-test all 8 MCP tools
python -c "
from mcp_server.server import (
    get_current_basket, get_basis_history, get_basis_percentile,
    get_ctd_transitions, get_transition_proximity,
    get_ctd_transition_threshold
)
ctd = next(x for x in get_current_basket('TYM26') if x['is_ctd'])
print(f'CTD: {ctd[\"label\"]}  IR={ctd[\"implied_repo_pct\"]}%  nb_ticks={ctd.get(\"net_basis\",0)*32:.2f}t')
prox = get_transition_proximity('TYM26')
print(f'Proximity: {prox[\"current_spread_bps\"]:.1f}bps  {prox[\"risk_flag\"]}  {prox[\"trend\"]}')
thresh = get_ctd_transition_threshold('TYM26')
print(f'Threshold: F*={thresh[\"transition_threshold_futures_price\"]}  dist={thresh[\"distance_to_threshold_pts\"]}pts')
"

# 3. Run dashboard
streamlit run dashboard/app.py

# 4. Run MCP server
python -m mcp_server.server

# 5. Run tests
pytest tests/ -v
```
