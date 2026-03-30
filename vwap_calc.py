"""
vwap_calc.py — VWAP计算模块 (适配Siphon荐股系统)
===================================================
移植自 loop-win-2026

VWAP (Volume-Weighted Average Price) 用于:
  - 评分: 价格在VWAP上方 = 买入信号加分
  - 退出建议: 价格跌破VWAP = 弱势确认

Siphon使用日线数据近似VWAP (滚动N日成交额/成交量)

Usage:
  from vwap_calc import VWAPCalc
  vwap = VWAPCalc.calc_daily_vwap(kline_df, window=5)
  is_above = VWAPCalc.is_above_vwap(current_price, vwap)
"""
import pandas as pd
import numpy as np
from typing import Optional, Tuple


class VWAPCalc:
    """VWAP计算器 — 使用日线数据"""

    @staticmethod
    def calc_daily_vwap(df: pd.DataFrame, window: int = 5) -> Optional[float]:
        """
        滚动N日VWAP = Σ(成交额) / Σ(成交量)

        如果有amount列直接用; 否则用 (high+low+close)/3 * volume 近似
        """
        if df is None or len(df) < window:
            return None

        recent = df.iloc[-window:]

        if 'amount' in recent.columns:
            total_amount = recent['amount'].sum()
        else:
            # 典型价格近似
            typical_price = (recent['high'] + recent['low'] + recent['close']) / 3
            total_amount = (typical_price * recent['volume']).sum()

        total_volume = recent['volume'].sum()

        if total_volume <= 0:
            return None

        return float(total_amount / total_volume)

    @staticmethod
    def is_above_vwap(current_price: float, vwap: Optional[float],
                      tolerance: float = 0.005) -> Optional[bool]:
        """
        价格是否在VWAP上方 (允许0.5%容差)

        Returns: True=强势, False=弱势, None=无数据
        """
        if vwap is None or current_price <= 0:
            return None
        return current_price >= vwap * (1 - tolerance)

    @staticmethod
    def calc_vwap_score(current_price: float, vwap: Optional[float]) -> float:
        """
        VWAP评分 (0-10):
          价格 > VWAP + 2%: +10
          价格 > VWAP:      +6
          价格 ≈ VWAP:      +3
          价格 < VWAP:      +0
        """
        if vwap is None or vwap <= 0 or current_price <= 0:
            return 5.0  # 无数据时中性

        deviation = (current_price - vwap) / vwap

        if deviation >= 0.02:
            return 10.0
        elif deviation >= 0.0:
            return 6.0
        elif deviation >= -0.01:
            return 3.0
        else:
            return 0.0

    @staticmethod
    def calc_vwap_series(df: pd.DataFrame, window: int = 5) -> pd.Series:
        """计算VWAP时间序列 (用于图表/回测)"""
        if df is None or len(df) < window:
            return pd.Series(dtype=float)

        if 'amount' in df.columns:
            amount = df['amount']
        else:
            amount = (df['high'] + df['low'] + df['close']) / 3 * df['volume']

        rolling_amount = amount.rolling(window).sum()
        rolling_volume = df['volume'].rolling(window).sum()

        vwap = rolling_amount / rolling_volume.replace(0, np.nan)
        return vwap
