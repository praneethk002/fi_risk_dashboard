# Fixed Income Risk Dashboard

A first-principles fixed income risk analytics tool with live yield curve 
data via MCP server integration.

## Modules
- `core/` — Bond pricing, DV01, duration, convexity, scenario engine, basis
- `mcp_server/` — Live US Treasury yield curve via FRED API
- `dashboard/` — Streamlit UI

## Setup
```bash
pip install -r requirements.txt
python mcp_server/server.py   # Start MCP server
streamlit run dashboard/app.py
```

## Status
🚧 In development
