# CTD Basis Monitor

A daily monitoring tool for the US Treasury cash-futures basis on the TY (10-year) contract. For each bond in the delivery basket, it computes net basis and implied repo, stores daily snapshots in SQLite, and identifies when the CTD is close to switching. The scenario grid shows how CTD identity changes under parallel yield shifts — the key question before a rate move.

## Architecture

```
core/           Pure analytics — CTD ranking, carry, scenario repricing
data/           SQLite schema + BasisDB query class, FRED price feed, ingest CLI
dashboard/      4-page Streamlit monitor (dark theme)
mcp_server/     FastMCP server — 6 tools for Claude morning-brief synthesis
tests/          Unit tests for CTD ranking, transition threshold, carry
```

**Key analytic depth:**
- CTD transition threshold F\* — the exact futures price at which bond B overtakes bond A (closed-form derivation from setting implied repo equations equal)
- DV01 of the basis position: `DV01_cash − DV01_futures_CTD / CF_CTD`
- 90-day rolling net basis percentile rank via SQLite window functions

## Setup

```bash
pip install -e .
cp .env.example .env          # add FRED_API_KEY
```

**Seed the database** (one run per day):
```bash
python -m data.ingest --contract TYM26 --futures-price 108.50 --repo-rate 0.053
```

**Run the dashboard:**
```bash
streamlit run dashboard/app.py
```

**MCP server** (connect Claude to the basis database):
```bash
python -m mcp_server.server
```

## Dashboard pages

| Page | Content |
|------|---------|
| 01 Basis Monitor | Basket table + 90-day net basis chart with rolling mean |
| 02 Delivery Basket | Full ranking table + CTD transition risk gauge |
| 03 CTD History | Gantt-style CTD timeline + implied repo spread proximity |
| 04 Scenario Grid | Heatmap: implied repo × parallel yield shift |

## Reference

Burghardt, Belton, Lane, Papa — *The Treasury Bond Basis* (the standard practitioner text on cash-futures basis trading).
