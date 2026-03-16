"""
Scoring Engine v11.0 — Unified scoring module for both live and backtest modes.

This module exports the core scoring functions used by both siphon_strategy.py (live)
and win_server_fixed.py (backtest). Ensures strategy consistency between backtest
and live recommendation.
"""

import numpy as np
import pandas as pd


# ─── Market regime detection ───

DEFAULT_WEIGHTS = {
    'inst_burst': 40,
    'micro_mom': 25,
    'antigravity': 20,
    'vcp': 15,
}

REGIME_WEIGHT_ADJUSTMENTS = {
    'bull':    {'inst_burst': 0, 'micro_mom': +10, 'antigravity': -10, 'vcp': 0},
    'bear':    {'inst_burst': -10, 'micro_mom': 0, 'antigravity': +10, 'vcp': 0},
    'neutral': {'inst_burst': 0, 'micro_mom': 0, 'antigravity': 0, 'vcp': 0},
}


def detect_market_regime(index_hist):
    """Detect market regime from recent index performance.

    Args:
        index_hist: DataFrame with 'close' column, or array-like of close prices.

    Returns: (regime, index_5d_change)
        regime: 'bull' / 'bear' / 'neutral'
        index_5d_change: 5-day cumulative change %
    """
    if index_hist is None:
        return 'neutral', 0.0

    if isinstance(index_hist, pd.DataFrame):
        closes = index_hist['close']
    else:
        closes = pd.Series(index_hist)

    if len(closes) < 6:
        return 'neutral', 0.0

    change_5d = (closes.iloc[-1] / closes.iloc[-6] - 1) * 100

    if change_5d >= 3.0:
        return 'bull', round(change_5d, 2)
    elif change_5d <= -3.0:
        return 'bear', round(change_5d, 2)
    else:
        return 'neutral', round(change_5d, 2)


def get_regime_weights(regime='neutral'):
    """Return adjusted weight caps based on market regime."""
    adj = REGIME_WEIGHT_ADJUSTMENTS.get(regime, REGIME_WEIGHT_ADJUSTMENTS['neutral'])
    return {k: DEFAULT_WEIGHTS[k] + adj[k] for k in DEFAULT_WEIGHTS}


# ─── Core scoring functions (shared between live and backtest) ───

def calc_antigravity_score(stock_closes, index_changes, lookback=10):
    """Calculate antigravity score from close prices and index daily changes.

    Works with both DataFrames and numpy arrays for backtest compatibility.

    Returns: (score, detail_count)
    """
    if len(stock_closes) < lookback + 1 or len(index_changes) < lookback:
        return 0.0, 0

    score = 0.0
    consecutive = 0
    detail_count = 0

    for i in range(-lookback, 0):
        try:
            idx_chg = float(index_changes.iloc[i] if hasattr(index_changes, 'iloc') else index_changes[i])
            stk_chg_i = i
            stk_prev = float(stock_closes.iloc[stk_chg_i - 1] if hasattr(stock_closes, 'iloc') else stock_closes[stk_chg_i - 1])
            stk_curr = float(stock_closes.iloc[stk_chg_i] if hasattr(stock_closes, 'iloc') else stock_closes[stk_chg_i])
            if stk_prev == 0:
                continue
            stk_chg = (stk_curr / stk_prev - 1) * 100
        except (IndexError, KeyError):
            continue

        if idx_chg < -0.3:  # Index dropped > 0.3%
            if stk_chg > 0:
                score += 2.0
                consecutive += 1
                detail_count += 1
            else:
                consecutive = 0
            if stk_chg - idx_chg > 1.5:
                score += 1.0

    if consecutive >= 2:
        score += 1.0

    return score, detail_count


def calc_micro_momentum(stock_closes, index_closes):
    """Micro Momentum (0-25): 3-day alpha + 5-day alpha vs index.

    Works with both Series and arrays.
    Returns: (score, is_accelerating)
    """
    if len(stock_closes) < 6 or len(index_closes) < 6:
        return 0.0, False

    def _get(arr, idx):
        return float(arr.iloc[idx]) if hasattr(arr, 'iloc') else float(arr[idx])

    stock_3d = (_get(stock_closes, -1) / _get(stock_closes, -4) - 1) * 100
    stock_5d = (_get(stock_closes, -1) / _get(stock_closes, -6) - 1) * 100
    idx_3d = (_get(index_closes, -1) / _get(index_closes, -4) - 1) * 100
    idx_5d = (_get(index_closes, -1) / _get(index_closes, -6) - 1) * 100

    alpha_3d = stock_3d - idx_3d
    alpha_5d = stock_5d - idx_5d

    score_3d = min(max(alpha_3d * 2.0, 0), 15.0)
    score_5d = min(max(alpha_5d * 1.5, 0), 10.0)

    score = score_3d + score_5d
    is_accelerating = alpha_3d > alpha_5d > 0
    return round(score, 1), is_accelerating


def calc_volume_burst(today_vol, ma5_vol, close_position, is_hot_sector=False):
    """Institutional Burst sub-scoring for volume/price action (0-40).

    Args:
        today_vol: today's volume
        ma5_vol: 5-day MA volume
        close_position: (close - low) / (high - low), 0 to 1
        is_hot_sector: whether the stock is in a hot sector
    Returns: (score, vol_ratio, is_closing_high)
    """
    vol_ratio = today_vol / ma5_vol if ma5_vol > 0 else 1.0
    score = 0.0

    if close_position > 0.85 and vol_ratio >= 2.0:
        score += 15.0
    elif close_position > 0.70 and vol_ratio >= 1.5:
        score += 8.0

    if is_hot_sector:
        score += 10.0

    return min(score, 40.0), round(vol_ratio, 2), close_position > 0.85


def calc_vcp_breakout_from_values(yesterday_vol, today_vol, ma5_vol_prev, today_change_pct):
    """VCP & Squeeze Breakout (0-15) from scalar values.

    Compatible with both live DataFrame access and backtest numpy access.
    """
    score = 0.0
    is_vcp = False

    if yesterday_vol < ma5_vol_prev * 0.6:
        if today_vol > yesterday_vol * 2.0 and today_change_pct > 2.0:
            score = 15.0
            is_vcp = True
        elif today_vol > yesterday_vol * 1.5 and today_change_pct > 0:
            score = 8.0

    return score, is_vcp


def calc_composite_score(ag_score, micro_mom_score, inst_score, vcp_score, regime='neutral'):
    """Composite score (0-100) with market-adaptive weights.

    This is the single source of truth for scoring, shared between live and backtest.
    """
    w = get_regime_weights(regime)

    score = 0.0
    score += min(inst_score, w['inst_burst'])
    score += min(micro_mom_score, w['micro_mom'])
    score += min(ag_score * 2.0, float(w['antigravity']))
    score += min(vcp_score, w['vcp'])

    return round(min(score, 100.0), 1)


# ─── Confidence grading ───

def get_confidence_grade(composite_score):
    """Map composite score to S/A/B/C confidence grade.

    Returns: (grade, label, color)
    """
    if composite_score >= 80:
        return 'S', '强烈推荐', '#ef4444'
    elif composite_score >= 60:
        return 'A', '推荐', '#f59e0b'
    elif composite_score >= 40:
        return 'B', '观察', '#3b82f6'
    else:
        return 'C', '弱', '#94a3b8'


# ─── Backtest-compatible static factor computation ───

def precompute_static_factors_unified(df_daily, index_daily=None):
    """Compute static factors for backtest, using the same scoring as live.

    This replaces the old `precompute_static_factors` in win_server_fixed.py
    to ensure scoring consistency.

    Args:
        df_daily: DataFrame with columns [date, close, high, low, volume, change_pct]
        index_daily: Optional DataFrame with [date, close, Index_Change] for AG scoring

    Returns: DataFrame with per-day factors
    """
    if len(df_daily) < 10:
        return None

    close = df_daily['close'].values
    high = df_daily['high'].values
    low = df_daily['low'].values
    volume = df_daily['volume'].values
    dates = df_daily['date'].values
    n = len(close)

    pct_3d = np.zeros(n)
    vol_ratio = np.ones(n)
    is_vcp = np.zeros(n, dtype=bool)
    avg_vol = np.zeros(n)
    ag_scores = np.zeros(n)
    micro_mom = np.zeros(n)
    vcp_scores = np.zeros(n)
    close_position = np.zeros(n)

    # Pre-fetch index closes if available
    idx_closes = None
    idx_changes = None
    if index_daily is not None and len(index_daily) > 0:
        idx_closes = index_daily['close'].values
        if 'Index_Change' in index_daily.columns:
            idx_changes = index_daily['Index_Change'].values

    for i in range(10, n):
        # 3-day momentum
        pct_3d[i] = (close[i] / close[i - 3] - 1) * 100 if close[i - 3] != 0 else 0

        # Volume ratio
        v3 = np.mean(volume[i - 2:i + 1])
        v5 = np.mean(volume[i - 7:i - 2])
        vol_ratio[i] = v3 / (v5 + 1e-9)

        # Average daily volume
        avg_vol[i] = np.mean(volume[i - 4:i + 1])

        # Close position in range
        hl_range = high[i] - low[i]
        close_position[i] = (close[i] - low[i]) / hl_range if hl_range > 0 else 1.0

        # VCP detection using shared function
        if i >= 7:
            ma5_prev = np.mean(volume[i - 7:i - 2])
            change_pct_i = (close[i] / close[i - 1] - 1) * 100 if close[i - 1] != 0 else 0
            vcp_scores[i], is_vcp[i] = calc_vcp_breakout_from_values(
                volume[i - 1], volume[i], ma5_prev, change_pct_i
            )

        # Micro momentum (needs index data)
        if idx_closes is not None and i >= 6 and len(idx_closes) > i:
            micro_mom[i], _ = calc_micro_momentum(
                close[i - 6:i + 1], idx_closes[max(0, i - 6):i + 1]
            )

        # Antigravity score (needs index change data)
        if idx_changes is not None and i >= 11 and len(idx_changes) > i:
            ag_scores[i], _ = calc_antigravity_score(
                close[i - 11:i + 1], idx_changes[i - 10:i + 1]
            )

    df_f = pd.DataFrame({
        'date': dates,
        'last_close': close,
        'pct_3d': pct_3d,
        'vol_ratio': vol_ratio,
        'is_vcp': is_vcp,
        'avg_daily_vol': avg_vol,
        'close_position': close_position,
        'ag_score': ag_scores,
        'micro_mom': micro_mom,
        'vcp_score': vcp_scores,
    })

    # Composite score using unified formula
    df_f['ag_score_static'] = df_f.apply(
        lambda row: calc_composite_score(
            row['ag_score'], row['micro_mom'],
            calc_volume_burst(0, 1, row['close_position'])[0],
            row['vcp_score']
        ), axis=1
    )

    return df_f
