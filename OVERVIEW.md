# Fixed Income Risk Dashboard — Overview

A fixed income analytics platform for US Treasury bonds, built from first principles.
Live yield curve data is fetched from FRED and exposed through an MCP server, feeding
both a Streamlit dashboard and an LLM-callable tool interface.

---

## Concepts

### Bond Pricing

A fixed-coupon bond is priced by discounting each cash flow (coupon + principal at
maturity) at the yield to maturity (YTM):

```
P = Σ [ C / (1 + y/f)^t ]  +  F / (1 + y/f)^n
```

where `C` is the periodic coupon, `F` is face value, `y` is the annual yield,
`f` is payment frequency, and `n` is total periods. This is the standard DCF
formula; on a coupon date, clean price equals dirty price (no accrued interest).

### Duration and Convexity

**Modified duration** measures the percentage price change for a 1-unit parallel
yield move. It is computed numerically via a central finite difference over ±1bp,
which keeps it consistent with any underlying pricing model:

```
ModDur = (P(y - 1bp) - P(y + 1bp)) / (2 * 1bp * P(y))
```

**DV01** (dollar value of a basis point) is the dollar price change for a +1bp
yield increase: `DV01 = P * ModDur * 0.0001`.

**Convexity** is the second-order price sensitivity. A bond with positive convexity
gains more than duration predicts when yields fall, and loses less when yields rise:

```
Convexity = (P(y+1bp) + P(y-1bp) - 2*P(y)) / (P(y) * (1bp)^2)
```

The full second-order price approximation is:
```
ΔP ≈ -ModDur * Δy * P  +  0.5 * Convexity * (Δy)^2 * P
```

### Nelson-Siegel Yield Curve

The Nelson-Siegel (1987) model fits the yield curve across maturities with four
parameters:

```
r(τ) = β₀ + β₁ * L(τ) + β₂ * C(τ)

L(τ) = (1 - e^{-τ/λ}) / (τ/λ)   # slope loading: decays from 1 to 0
C(τ) = L(τ) - e^{-τ/λ}           # curvature loading: hump, peak near τ=λ
```

- **β₀**: Long-run level — where all yields converge as maturity → ∞
- **β₁**: Slope — negative for a normal (upward-sloping) curve
- **β₂**: Curvature — positive means the 5Y belly is cheap relative to wings
- **λ**: Decay speed — the maturity (years) where slope/curvature loadings peak

Parameters are fitted by minimising the sum of squared errors (SSE) via L-BFGS-B
with economically motivated bounds. FRED data (3M, 2Y, 5Y, 10Y, 30Y) is used as
input. RMSE < 2bps indicates an excellent fit.

### Spot Rate Bootstrapping

Par yields embed coupon reinvestment assumptions that make cross-maturity comparison
imprecise. Bootstrapping strips these out to produce zero-coupon (spot) rates.

For each maturity pillar, given all previously bootstrapped spot rates, it solves
numerically for the unique spot rate `z_n` such that the corresponding par bond
prices at exactly par:

```
1 = Σ_{t<n} [ (c/f) / (1 + z_t/f)^t ]  +  (1 + c/f) / (1 + z_n/f)^n
```

The resulting spot rates are wrapped in a cubic spline (not-a-knot boundary
conditions) for continuous interpolation. Discount factors use continuous
compounding: `DF(τ) = e^{-z(τ)*τ}`.

### Carry and Roll-Down

Under the static curve assumption (the yield curve shape does not change over
the holding period), a bond generates two sources of return:

- **Carry**: coupon accrual minus repo financing cost
- **Roll-down**: price appreciation from the bond rolling to a shorter maturity
  on an upward-sloping curve (a 10Y bond becomes a 9.75Y bond after 3 months;
  if the 9.75Y yield is lower than the 10Y yield, the price rises)

The **forward breakeven yield** is the yield the bond must reach at the horizon
for the total carry + roll profit to be exactly zero. It is derived from the
spot curve forward rate: `f(t₁, t₂) = [z(t₂)*t₂ - z(t₁)*t₁] / (t₂ - t₁)`.

### Z-Spread

The Z-spread (zero-volatility spread) is the constant spread `s` added to every
point on the Treasury spot curve that makes the bond's present value equal its
market (dirty) price:

```
P_dirty = Σ CF_t * e^{-(z(t) + s) * t}
```

Unlike a simple yield spread (YTM minus a single benchmark), the Z-spread uses
the full spot curve as the risk-free baseline and accounts for cash flows at every
maturity. A positive Z-spread means the bond offers excess yield over Treasuries.
Solved via Brent's method on [−500bps, +5000bps].

### Cash-Futures Basis

For Treasury bond futures, the cost-of-carry relationship links the cash bond
price to the futures invoice price:

- **Gross basis** = cash price − (futures price × conversion factor)
- **Carry** = coupon accrual (ACT/365) − repo financing cost (ACT/360)
- **Net basis** = gross basis − carry
- **Implied repo** = the financing rate implicitly locked in by the cash-futures position

If implied repo > market repo, buying cash and selling futures earns above-market
financing — a basis trade. The cheapest-to-deliver (CTD) bond is identified as
the bond in the delivery basket with the highest implied repo rate.

### Scenario Analysis

Five yield curve shock patterns are implemented, each applied to the FRED curve:

| Scenario | Description |
|---|---|
| Parallel shift | All tenors shift equally |
| Bear steepening | Long end rises; short end unchanged |
| Bear flattening | Short end rises; long end unchanged |
| Bull steepening | Short end falls; long end unchanged |
| Bull flattening | Long end falls; short end unchanged |

Each scenario linearly interpolates the shift across maturities. Bond P&L is
attributed to duration (linear) and convexity (second-order) components.

---

## Project Structure

```
fi_risk_dashboard/
├── core/
│   ├── pricing.py      # DCF pricing, accrued interest, dirty price
│   ├── risk.py         # Modified duration, DV01, convexity (numerical)
│   ├── curves.py       # Nelson-Siegel fitting, spot curve, bootstrapping
│   ├── analytics.py    # Carry/roll, Z-spread, total return decomposition
│   ├── scenarios.py    # Yield curve scenario engine (5 patterns)
│   └── basis.py        # Cash-futures basis, implied repo, CTD
├── mcp_server/
│   ├── fred_client.py  # FRED API client with 5-minute caching
│   └── server.py       # MCP server exposing 10 analytics tools
├── dashboard/
│   └── app.py          # Streamlit UI (6 tabs)
└── tests/              # 100 unit tests across all core modules
```

The `core/` modules are pure Python with no UI dependencies — they can be imported
and tested independently of Streamlit. The MCP server wraps these modules and
exposes them as callable tools for LLM integration. The Streamlit dashboard
imports from `core/` and `mcp_server/fred_client` directly.

---

## MCP Server

The MCP (Model Context Protocol) server exposes 10 tools that an LLM (Claude, etc.)
can call programmatically during a conversation. This means you can ask Claude
questions like "what is the Z-spread on a 10Y 4.5% coupon bond at 4.0% yield?"
and it will call the `z_spread_analysis` tool with live FRED data.

**Tools:**

| Tool | What it does |
|---|---|
| `get_yield_curve` | Live US Treasury curve from FRED (3M, 2Y, 5Y, 10Y, 30Y) |
| `price_bond` | DCF bond price |
| `risk_metrics` | Modified duration, DV01, convexity |
| `scenario_analysis` | Yield curve scenario + bond P&L |
| `basis_analytics` | Gross basis, net basis, implied repo |
| `find_ctd` | Cheapest-to-deliver from a delivery basket |
| `nelson_siegel_fit` | Fit NS model to any yield curve data |
| `carry_roll_analysis` | Carry + roll-down for 3M, 6M, 1Y horizons |
| `z_spread_analysis` | Z-spread over live FRED spot curve |
| `curve_spread_metrics` | 2s10s, 5s30s, 2s5s10s butterfly from FRED |

All rate inputs/outputs use percentages (e.g. `4.5` for 4.5%). Spreads are in
basis points. The `_build_spot_curve()` helper in server.py fetches FRED data,
fits Nelson-Siegel, and returns a SpotCurve — the shared setup for tools 8–10.

FRED data is cached in-process for 5 minutes. If no `FRED_API_KEY` is set,
`fetch_latest_rate` returns `None` immediately without making a network call,
and the dashboard falls back to a hardcoded representative curve.

---

## Dashboard Tabs

**01 — Yield Curve**: Nelson-Siegel fit over live FRED data, NS parameter badges
(β₀, β₁, β₂, λ, RMSE), bootstrapped spot curve overlay, and live curve spreads.

**02 — Risk Metrics**: Bond price, modified duration, DV01, convexity, price/yield
convexity curve (actual vs. duration linear approximation), and a rate sensitivity
table for ±200bps parallel shifts.

**03 — Carry & Roll**: Waterfall charts for 3M, 6M, 1Y horizons showing net carry
and roll-down components. Summary table with forward breakeven YTM. Total return
decomposition bar chart (carry, roll, duration P&L, convexity P&L) with an
interactive yield change slider.

**04 — Scenarios**: Select scenario type, view current vs. shocked curve overlay,
per-tenor yield change table, bond P&L with duration/convexity attribution, and
an all-scenarios comparison table.

**05 — Z-Spread**: Z-spread vs. simple yield spread, spot curve + Z-adjusted
curve chart, interpretation (cheap/rich/fair relative to Treasuries). Optional
custom dirty price input.

**06 — Cash-Futures Basis**: Gross basis, net basis, implied repo, carry signal.
Sensitivity chart showing net basis vs. repo rate, with the implied repo marked
as the zero-crossing point.

---

## Running the Project

### Prerequisites

```bash
pip install -r requirements.txt
```

### Environment

Create a `.env` file in the project root:

```
FRED_API_KEY=your_key_here
```

A free API key is available at https://fred.stlouisfed.org/docs/api/api_key.html.
Without it the dashboard falls back to a hardcoded representative curve automatically.

### Dashboard

```bash
streamlit run dashboard/app.py
```

Opens at `http://localhost:8501`. The sidebar controls the bond parameters (face
value, coupon, YTM, maturity, frequency) and market inputs (repo rate, scenario
shift) that feed all six tabs.

### MCP Server (for LLM integration)

```bash
python -m mcp_server.server
```

Runs on stdio transport (the default for Claude Desktop / Claude Code). To wire it
into Claude Code, add to `.claude/settings.json`:

```json
{
  "mcpServers": {
    "fi-risk-dashboard": {
      "command": "python",
      "args": ["-m", "mcp_server.server"],
      "cwd": "/path/to/fi_risk_dashboard"
    }
  }
}
```

### Tests

```bash
pytest tests/ -v
```

100 tests across pricing, risk metrics, curve fitting, bootstrapping, analytics,
scenarios, and basis calculations. All tests use deterministic inputs with no
external network calls.
