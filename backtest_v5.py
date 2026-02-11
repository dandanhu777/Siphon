"""
Backtest: Siphon Strategy v2.0 (old) vs v5.0 (new)
===================================================
Fetches 90-day history for tracked stocks, then replays both scoring
systems on each historical trading day and compares forward returns.

This is a REALISTIC backtest using actual historical data from AkShare.
"""

import pandas as pd
import numpy as np
import akshare as ak
import datetime
import time
import sqlite3
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

# Import strategy functions
from siphon_strategy import (
    calculate_antigravity_score,
    calc_relative_strength,
    detect_institutional_flow,
    calc_safety_margin,
    calc_composite_score,
    StrategyConfig,
)

CONFIG = StrategyConfig()


# ──────────────────────────────────────────────
# 1. DATA LOADING
# ──────────────────────────────────────────────

def fetch_index_history(days=90):
    """Fetch CSI 300 index history with multiple fallbacks."""
    print("📊 Fetching index history (CSI 300)...")
    df = pd.DataFrame()
    
    # Try EM first
    try:
        df = ak.stock_zh_index_daily_em(symbol="000300")
    except Exception as e:
        print(f"   ⚠️ EM failed: {e}")
    
    # Fallback: Sina
    if df.empty:
        try:
            df = ak.index_zh_a_hist(symbol="000300", period="daily")
        except Exception as e:
            print(f"   ⚠️ index_zh_a_hist failed: {e}")
    
    # Fallback: Sina daily
    if df.empty:
        try:
            df = ak.stock_zh_index_daily(symbol="sh000300")
        except Exception as e:
            print(f"   ⚠️ stock_zh_index_daily failed: {e}")
    
    if df.empty:
        print("   ❌ All index sources failed")
        return pd.DataFrame()
    
    df = df.sort_values('date').tail(days)
    df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
    df['close'] = pd.to_numeric(df['close'])
    df['Index_Change'] = df['close'].pct_change() * 100
    df['Index_Change'] = df['Index_Change'].fillna(0)
    print(f"   ✅ Index: {len(df)} days ({df['date'].iloc[0]} → {df['date'].iloc[-1]})")
    return df[['date', 'close', 'Index_Change']].reset_index(drop=True)


def fetch_stock_history(symbol, days=90):
    """Fetch single stock history with volume."""
    end_date = datetime.datetime.now().strftime("%Y%m%d")
    start_date = (datetime.datetime.now() - datetime.timedelta(days=days * 2)).strftime("%Y%m%d")

    if symbol.startswith('6'):
        prefix = 'sh'
    elif symbol.startswith('0') or symbol.startswith('3'):
        prefix = 'sz'
    else:
        return None

    try:
        df = ak.stock_zh_a_daily(symbol=f"{prefix}{symbol}", start_date=start_date, end_date=end_date, adjust="qfq")
        if df.empty or len(df) < 30:
            return None
        df = df.sort_values('date')
        df['change_pct'] = df['close'].pct_change() * 100
        df['change_pct'] = df['change_pct'].fillna(0)
        df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
        return df[['date', 'close', 'volume', 'change_pct']]
    except Exception:
        return None


def get_tracked_stocks():
    """Get stock list from Boomerang tracker DB."""
    db_path = os.path.join(os.path.dirname(__file__), "boomerang_tracker.db")
    if not os.path.exists(db_path):
        print("❌ boomerang_tracker.db not found")
        return []

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT DISTINCT stock_code, stock_name, industry FROM recommendations"
    ).fetchall()
    conn.close()
    return [(r[0], r[1], r[2] or '') for r in rows]


# ──────────────────────────────────────────────
# 2. SCORING FUNCTIONS
# ──────────────────────────────────────────────

def score_old_v2(hist_slice, index_slice, vol_ratio=1.0):
    """Old v2.0 scoring: siphon_ratio = vol_ratio * 10 / (|change| + 0.5)"""
    ag_score, _ = calculate_antigravity_score(hist_slice, index_slice)
    if ag_score < CONFIG.min_ag_score:
        return None

    change_pct = hist_slice.iloc[-1]['change_pct']
    siphon_ratio = round((vol_ratio * 10) / (abs(change_pct) + 0.5), 1)
    return {
        'score': siphon_ratio,
        'ag': ag_score,
        'method': 'v2.0',
    }


def score_new_v5(hist_slice, index_slice, vol_ratio=1.0):
    """New v5.0 scoring: composite (0-100)"""
    ag_score, _ = calculate_antigravity_score(hist_slice, index_slice)
    if ag_score < CONFIG.min_ag_score:
        return None

    rs_score, is_acc = calc_relative_strength(hist_slice, index_slice)
    flow_info = detect_institutional_flow(hist_slice)
    safety_grade, atr_pct = calc_safety_margin(hist_slice)

    if atr_pct > CONFIG.max_atr_pct:
        return None

    composite = calc_composite_score(
        ag_score, rs_score, flow_info, safety_grade,
        is_hot_sector=True,  # neutral assumption for backtest
        vcp_signal=True       # stock already passed VCP in real run
    )

    if composite < CONFIG.min_composite_score:
        return None

    return {
        'score': composite,
        'ag': ag_score,
        'rs': rs_score,
        'flow': flow_info['flow_ratio'],
        'safety': safety_grade,
        'atr': atr_pct,
        'method': 'v5.0',
    }


# ──────────────────────────────────────────────
# 3. BACKTEST ENGINE
# ──────────────────────────────────────────────

def run_backtest(lookback_days=15, forward_days_list=[3, 5, 10]):
    """
    Main backtest:
    1. Fetch 90-day data for all tracked stocks (once)
    2. For each of the last `lookback_days` trading days:
       a. Slice history up to that day
       b. Score with old v2.0 and new v5.0
       c. Pick top N by each
    3. Measure forward returns
    4. Print comparison
    """
    max_forward = max(forward_days_list)

    # ── Load data ──
    stocks = get_tracked_stocks()
    if not stocks:
        print("❌ No tracked stocks found")
        return
    print(f"📋 Found {len(stocks)} tracked stocks")

    index_hist = fetch_index_history(days=120)
    if index_hist.empty:
        print("❌ Cannot fetch index data")
        return

    # Fetch all stock histories
    print(f"\n🔄 Fetching 90-day history for {len(stocks)} stocks...")
    all_data = {}
    for i, (code, name, industry) in enumerate(stocks):
        code = str(code).zfill(6)
        df = fetch_stock_history(code, days=120)
        if df is not None and len(df) >= 40:
            all_data[code] = {'name': name, 'industry': industry, 'hist': df}
        if (i + 1) % 20 == 0:
            print(f"   ... fetched {i + 1}/{len(stocks)} ({len(all_data)} valid)")
        time.sleep(0.15)

    print(f"✅ Loaded {len(all_data)} stocks with valid history\n")

    if len(all_data) < 10:
        print("❌ Not enough valid stocks for backtest")
        return

    # ── Get trading days ──
    trading_days = sorted(index_hist['date'].tolist())
    # We need at least lookback_days + max_forward days
    if len(trading_days) < lookback_days + max_forward + 20:
        print(f"⚠️ Not enough trading days ({len(trading_days)}), reducing lookback")
        lookback_days = len(trading_days) - max_forward - 20

    # Simulation window: from day -(lookback+max_forward) to day -max_forward
    sim_end_idx = len(trading_days) - max_forward - 1
    sim_start_idx = sim_end_idx - lookback_days

    if sim_start_idx < 20:
        sim_start_idx = 20

    sim_dates = trading_days[sim_start_idx:sim_end_idx + 1]
    print(f"📅 Backtesting {len(sim_dates)} trading days: {sim_dates[0]} → {sim_dates[-1]}")
    print(f"   Forward return window: {forward_days_list} days")
    print("=" * 80)

    # ── Run simulation ──
    results_old = []
    results_new = []

    for sim_date in sim_dates:
        # Slice index up to sim_date
        idx_slice = index_hist[index_hist['date'] <= sim_date].tail(30)
        if len(idx_slice) < 10:
            continue

        # Score all stocks
        day_scores_old = []
        day_scores_new = []

        for code, info in all_data.items():
            hist = info['hist']
            hist_slice = hist[hist['date'] <= sim_date].tail(30)
            if len(hist_slice) < 20:
                continue

            # Old scoring
            old = score_old_v2(hist_slice, idx_slice)
            if old:
                old['code'] = code
                old['name'] = info['name']
                old['date'] = sim_date
                old['entry_price'] = hist_slice.iloc[-1]['close']
                day_scores_old.append(old)

            # New scoring
            new = score_new_v5(hist_slice, idx_slice)
            if new:
                new['code'] = code
                new['name'] = info['name']
                new['date'] = sim_date
                new['entry_price'] = hist_slice.iloc[-1]['close']
                day_scores_new.append(new)

        # Pick top 3 by each method
        day_scores_old.sort(key=lambda x: x['score'], reverse=True)
        day_scores_new.sort(key=lambda x: x['score'], reverse=True)

        top_old = day_scores_old[:3]
        top_new = day_scores_new[:3]

        # Calculate forward returns
        for pick in top_old + top_new:
            code = pick['code']
            hist = all_data[code]['hist']
            future_dates = [d for d in trading_days if d > sim_date]

            for fd in forward_days_list:
                if fd <= len(future_dates):
                    target_date = future_dates[fd - 1]
                    future_row = hist[hist['date'] == target_date]
                    if not future_row.empty:
                        exit_price = future_row.iloc[0]['close']
                        ret = (exit_price / pick['entry_price'] - 1) * 100
                        pick[f'ret_{fd}d'] = round(ret, 2)
                    else:
                        pick[f'ret_{fd}d'] = None
                else:
                    pick[f'ret_{fd}d'] = None

            # Max drawdown in forward window
            future_hist = hist[(hist['date'] > sim_date)]
            future_hist = future_hist.head(max_forward)
            if not future_hist.empty:
                max_high = future_hist['close'].max()
                min_low = future_hist['close'].min()
                pick['max_up'] = round((max_high / pick['entry_price'] - 1) * 100, 2)
                pick['max_down'] = round((min_low / pick['entry_price'] - 1) * 100, 2)
            else:
                pick['max_up'] = None
                pick['max_down'] = None

        results_old.extend(top_old)
        results_new.extend(top_new)

        # Daily log
        old_names = [p['name'] for p in top_old]
        new_names = [p['name'] for p in top_new]
        overlap = set(old_names) & set(new_names)
        print(f"  {sim_date} | v2({len(day_scores_old)} pass) Top: {', '.join(old_names[:3])}")
        print(f"  {' ' * 10} | v5({len(day_scores_new)} pass) Top: {', '.join(new_names[:3])}")
        if overlap:
            print(f"  {' ' * 10} | 🔄 Overlap: {', '.join(overlap)}")
        print()

    # ── Aggregate Results ──
    print("\n" + "=" * 80)
    print("📊 BACKTEST RESULTS")
    print("=" * 80)

    for label, results in [("v2.0 (Old Siphon Ratio)", results_old),
                            ("v5.0 (New Composite)", results_new)]:
        print(f"\n{'─' * 40}")
        print(f"  Strategy: {label}")
        print(f"  Total picks: {len(results)}")
        print(f"{'─' * 40}")

        for fd in forward_days_list:
            col = f'ret_{fd}d'
            valid = [r[col] for r in results if r.get(col) is not None]
            if not valid:
                print(f"  {fd}-Day Return: No data")
                continue

            avg_ret = np.mean(valid)
            median_ret = np.median(valid)
            win_rate = len([r for r in valid if r > 0]) / len(valid) * 100
            avg_win = np.mean([r for r in valid if r > 0]) if any(r > 0 for r in valid) else 0
            avg_loss = np.mean([r for r in valid if r <= 0]) if any(r <= 0 for r in valid) else 0
            profit_factor = abs(avg_win / avg_loss) if avg_loss != 0 else float('inf')
            
            print(f"\n  📈 {fd}-Day Forward Return:")
            print(f"     Avg Return:    {avg_ret:+.2f}%")
            print(f"     Median Return: {median_ret:+.2f}%")
            print(f"     Win Rate:      {win_rate:.1f}%")
            print(f"     Avg Win:       {avg_win:+.2f}%")
            print(f"     Avg Loss:      {avg_loss:+.2f}%")
            print(f"     Profit Factor: {profit_factor:.2f}")

        # Max drawdown stats
        max_ups = [r['max_up'] for r in results if r.get('max_up') is not None]
        max_downs = [r['max_down'] for r in results if r.get('max_down') is not None]
        if max_ups and max_downs:
            print(f"\n  🎯 Risk Metrics ({max_forward}-day window):")
            print(f"     Avg Max Up:    {np.mean(max_ups):+.2f}%")
            print(f"     Avg Max Down:  {np.mean(max_downs):+.2f}%")
            print(f"     Worst DD:      {min(max_downs):+.2f}%")

    # ── Side-by-side comparison ──
    print(f"\n{'=' * 80}")
    print("📊 HEAD-TO-HEAD COMPARISON")
    print(f"{'=' * 80}")

    header = f"{'Metric':<25}"
    for fd in forward_days_list:
        header += f"  {'v2.0':>8}  {'v5.0':>8}  {'Δ':>6}"
    print(header)
    print("-" * len(header))

    for metric_name, metric_fn in [
        ("Avg Return", lambda results, fd: np.mean([r[f'ret_{fd}d'] for r in results if r.get(f'ret_{fd}d') is not None])),
        ("Win Rate %", lambda results, fd: len([r[f'ret_{fd}d'] for r in results if r.get(f'ret_{fd}d') is not None and r[f'ret_{fd}d'] > 0]) / max(len([r[f'ret_{fd}d'] for r in results if r.get(f'ret_{fd}d') is not None]), 1) * 100),
        ("Median Return", lambda results, fd: np.median([r[f'ret_{fd}d'] for r in results if r.get(f'ret_{fd}d') is not None]) if [r[f'ret_{fd}d'] for r in results if r.get(f'ret_{fd}d') is not None] else 0),
    ]:
        row = f"{metric_name:<25}"
        for fd in forward_days_list:
            v2_val = metric_fn(results_old, fd)
            v5_val = metric_fn(results_new, fd)
            delta = v5_val - v2_val
            row += f"  {v2_val:>7.2f}%  {v5_val:>7.2f}%  {delta:>+5.2f}"
        print(row)

    # ── Detail Table ──
    print(f"\n{'=' * 80}")
    print("📋 DETAILED PICKS (v5.0 New Strategy)")
    print(f"{'=' * 80}")
    print(f"{'Date':<12} {'Name':<10} {'Score':>6} {'AG':>5} {'RS':>6} {'Flow':>5} {'Safe':>4} {'3d%':>7} {'5d%':>7} {'10d%':>7}")
    print("-" * 85)

    for r in sorted(results_new, key=lambda x: x['date']):
        ret3 = f"{r.get('ret_3d', 'N/A'):>+.2f}" if r.get('ret_3d') is not None else "  N/A"
        ret5 = f"{r.get('ret_5d', 'N/A'):>+.2f}" if r.get('ret_5d') is not None else "  N/A"
        ret10 = f"{r.get('ret_10d', 'N/A'):>+.2f}" if r.get('ret_10d') is not None else "  N/A"
        print(f"{r['date']:<12} {r['name']:<10} {r['score']:>6.1f} {r.get('ag', 0):>5.1f} {r.get('rs', 0):>6.1f} {r.get('flow', 0):>5.1f} {r.get('safety', '-'):>4} {ret3:>7} {ret5:>7} {ret10:>7}")

    print(f"\n{'=' * 80}")
    print("✅ Backtest Complete")
    print(f"{'=' * 80}")


if __name__ == "__main__":
    run_backtest(lookback_days=15, forward_days_list=[3, 5, 10])
