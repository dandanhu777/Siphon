# Daily Siphon System (DSS)

**Version**: 7.0.0
**Last Updates**: 2026-02-02

## 📖 Overview
The **Daily Siphon System** is a professional-grade quantitative trading assistant designed for the A-Share market. It autonomously identifies short-term opportunities using the proprietary **"Siphon"** strategy and manages risk through the **"Shield v2"** protocol.

## 🧠 Core Strategy Logic

### 1. Entry Mechanism (The Siphon)
The system identifies stocks where institutional capital is actively "siphoning" float against the trend.
-   **Siphon Score**: A composite metric (>3.0 indicates entry).
    *   **Capital Flow**: Net inflow during price consolidation.
    *   **VCP (Volatility Contraction)**: Price tightness + Volume Dry-up.
    *   **Relative Strength (RS)**: Outperforming 80% of the market.
-   **Selection Filter**:
    *   MA50 Trend > 0
    *   No ST/KC stocks
    *   Liquid (>100M turnover)

### 2. Exit Mechanism (The Shield: 4-Stage Defense)
The system employs a sophisticated 4-stage exit protocol to manage risk and maximize convexity:

**1. Defensive Baseline (Survival)**
-   **Goal**: Prevent "Ruins Problem" (non-linear loss spiral).
-   **Action**: **Hard Exit** if price hits **-7%**. (Unconditional).

**2. Velocity Optimization (Efficiency)**
-   **Goal**: Recycle stagnant capital ("Dead Money").
-   **Action**: **Soft Exit** if:
    -   Held > 5 Days & Return < 0% (Time Out).
    -   Held > 10 Days & Return < 3% (Stagnant).

**3. Convexity Generation (Smart Exit)**
-   **Goal**: Let profits run while locking in right-tail gains.
-   **Action**: **Smart Exit** if:
    -   **Trailing Stop**: Max Return > 15% AND Drawdown > 5%.
    -   **Take Profit**: Absolute Return > 20% (Secure High Odds).

**4. Contextual Awareness (De-risk)**
-   **Goal**: Active defense against market structure deterioration.
-   **Action**: **Technical Warning** if MACD Dead Cross or Price < MA20.

## 📊 Reporting Architecture

### Daily Email Report
-   **Top Picks**: Rank 1 candidate (The "Daily Core").
-   **Tracking History**: 
    -   Displays active holdings.
    -   **T+0 Limit**: Strict Top 3 limit per day to prevent info flood.
    -   **Action Column**: Color-coded badges (e.g., `STOP LOSS`, `TAKE PROFIT`) driven by Shield v2.

### Failover & Reliability
-   **Network**: Auto-detects network failure and switches API endpoints (Local Proxy -> Remote Proxy).
-   **Data**: Fallback from `ak.stock_zh_a_spot_em` -> `ak.stock_zh_a_spot` -> Soft Cache.
-   **LLM**: Fallback from OpenAI -> DeepSeek -> Deterministic (AkShare) Logic.

## � Usage

```bash
# Full Daily Run (Strategy + Enrichment + Email)
./run.sh
```

## 📂 Key Files
-   `siphon_strategy.py`: Entry Signal Generation.
-   `fallback_email_sender.py`: Report Engine & Shield v2 Implementation.
-   `gemini_enricher.py`: LLM Enrichment & Failover Logic.
-   `VERSION`: Semantic Version Tracking.

## ⚠️ Known Issues
-   **Local LLM Proxy**: The local `antigravity` middleware (port 8045) is deprecated. The system currently relies on the failover logic or deterministic fallback for text generation. 
-   **Performance**: Generating the "Shield v2" report requires pulling 60-day daily K-line data for every tracked stock. This adds ~30s to the execution time.

## 🔧 Optimization Roadmap (Claude Opus 4.5 Analysis)

Based on a comprehensive code review by Claude Opus 4.5, the following optimizations are planned:

| Priority | Item | Expected Gain |
| :---: | :--- | :--- |
| 🔴 | **K-line Data Batching**: Pre-fetch all 60-day K-lines in one pass | 4x faster report gen |
| 🔴 | **Fix `ag_score` Placeholder**: Restore actual Siphon Score calculation | Core logic integrity |
| 🟠 | **Parallel Processing**: Use ThreadPoolExecutor for API calls | 3x faster scanning |
| 🟠 | **Logging System**: Replace `except: pass` with proper logging | Debuggability |
| 🟢 | **Code Modularization**: Split 740-line file into modules | Maintainability |

> Full analysis: See `optimization_report.md` in the project artifacts.

# Siphon
