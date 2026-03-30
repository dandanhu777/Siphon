"""
regime_sensor.py — 市场状态感知模块 (适配Siphon荐股系统)
=========================================================
移植自 loop-win-2026, 用akshare替代xtdata

三档市场状态:
  CALM     (平静) ATR < 1.5% → 正常阈值, 权重不调整
  VOLATILE (波动) ATR 1.5%~3% → 收紧阈值 1.3x, 提高反重力权重
  PANIC    (恐慌) ATR > 3%  → 大幅收紧 1.6x, 防御优先

Usage:
  from regime_sensor import RegimeSensor, Regime
  sensor = RegimeSensor()
  regime = sensor.detect(index_df)  # 传入指数K线
  mult = sensor.get_threshold_mult()
  weights = sensor.get_weight_adjustments()
"""
from enum import Enum
from typing import Optional, Dict, Tuple

import numpy as np
import pandas as pd


class Regime(Enum):
    CALM = "CALM"          # ATR < 1.5%
    VOLATILE = "VOLATILE"  # ATR 1.5%~3%
    PANIC = "PANIC"        # ATR > 3%


class RegimeSensor:
    """市场状态感知器 — 基于ATR的自适应市场分类"""

    THRESHOLD_MULTIPLIER = {
        Regime.CALM: 1.0,
        Regime.VOLATILE: 1.3,
        Regime.PANIC: 1.6,
    }

    # 评分权重调整 (相对默认权重的增减)
    WEIGHT_ADJUSTMENTS = {
        Regime.CALM: {
            'inst_burst': 0, 'micro_mom': 0, 'antigravity': 0, 'vcp': 0,
            'deep_factor': 0,
        },
        Regime.VOLATILE: {
            'inst_burst': -5, 'micro_mom': -5, 'antigravity': +10, 'vcp': 0,
            'deep_factor': +5,
        },
        Regime.PANIC: {
            'inst_burst': -10, 'micro_mom': -10, 'antigravity': +15, 'vcp': -5,
            'deep_factor': +10,
        },
    }

    # 退出建议松紧度
    EXIT_TIGHTNESS = {
        Regime.CALM: {
            'trailing_stop_mult': 1.0,      # 标准止盈回撤
            'atr_stop_mult': 1.0,            # 标准ATR止损
            'stagnant_days': 10,             # 僵滞天数阈值
            'timeout_days': 5,               # 超时天数阈值
        },
        Regime.VOLATILE: {
            'trailing_stop_mult': 0.85,      # 收紧15%
            'atr_stop_mult': 1.3,            # 放宽ATR (波动大不过早止损)
            'stagnant_days': 8,
            'timeout_days': 4,
        },
        Regime.PANIC: {
            'trailing_stop_mult': 0.70,      # 收紧30% (快速锁利)
            'atr_stop_mult': 1.6,            # 大幅放宽 (避免被震出)
            'stagnant_days': 5,
            'timeout_days': 3,
        },
    }

    ATR_WINDOW = 5  # 5日ATR

    def __init__(self):
        self._regime = Regime.CALM
        self._last_atr_pct = 0.0
        self._index_5d_change = 0.0

    def detect(self, index_df: pd.DataFrame = None) -> Regime:
        """
        基于指数K线检测市场状态

        Args:
            index_df: 指数K线 DataFrame, 需要 high/low/close 列

        Returns: Regime枚举
        """
        if index_df is None or len(index_df) < self.ATR_WINDOW + 1:
            self._regime = Regime.CALM
            return self._regime

        high = index_df['high'].astype(float).values
        low = index_df['low'].astype(float).values
        close = index_df['close'].astype(float).values

        # True Range (百分比)
        n = len(close)
        tr_pcts = []
        for i in range(1, n):
            tr = max(
                high[i] - low[i],
                abs(high[i] - close[i - 1]),
                abs(low[i] - close[i - 1])
            )
            tr_pct = tr / close[i - 1] if close[i - 1] > 0 else 0
            tr_pcts.append(tr_pct)

        if not tr_pcts:
            self._regime = Regime.CALM
            return self._regime

        # 取最近ATR_WINDOW天的平均
        recent_tr = tr_pcts[-self.ATR_WINDOW:]
        atr_pct = float(np.mean(recent_tr))
        self._last_atr_pct = atr_pct

        # 5日涨跌幅
        if len(close) >= 6:
            self._index_5d_change = (close[-1] / close[-6] - 1) * 100

        self._regime = self._classify(atr_pct)
        return self._regime

    def _classify(self, atr_pct: float) -> Regime:
        if atr_pct < 0.015:
            return Regime.CALM
        elif atr_pct < 0.030:
            return Regime.VOLATILE
        else:
            return Regime.PANIC

    def get_regime(self) -> Regime:
        return self._regime

    def get_threshold_mult(self) -> float:
        """入选阈值倍数: CALM=1.0, VOLATILE=1.3, PANIC=1.6"""
        return self.THRESHOLD_MULTIPLIER[self._regime]

    def get_weight_adjustments(self) -> Dict[str, int]:
        """获取当前状态下的评分权重调整"""
        return self.WEIGHT_ADJUSTMENTS[self._regime]

    def get_exit_params(self) -> Dict[str, float]:
        """获取当前状态下的退出参数"""
        return self.EXIT_TIGHTNESS[self._regime]

    def get_atr_pct(self) -> float:
        """最近的指数ATR百分比"""
        return self._last_atr_pct

    def get_index_5d_change(self) -> float:
        """指数5日涨跌幅"""
        return self._index_5d_change

    def get_regime_label(self) -> str:
        """中文标签"""
        labels = {
            Regime.CALM: '平静',
            Regime.VOLATILE: '波动',
            Regime.PANIC: '恐慌',
        }
        return labels.get(self._regime, '未知')

    def get_summary(self) -> str:
        """状态摘要 (用于报告)"""
        return (f"市场状态: {self.get_regime_label()} "
                f"(ATR={self._last_atr_pct * 100:.2f}%, "
                f"5日涨跌={self._index_5d_change:+.1f}%)")

    def calc_stock_atr_pct(self, stock_df: pd.DataFrame, window: int = 14) -> float:
        """计算个股ATR百分比 (用于退出引擎)"""
        if stock_df is None or len(stock_df) < window + 1:
            return 0.02  # 默认2%

        high = stock_df['high'].astype(float).values
        low = stock_df['low'].astype(float).values
        close = stock_df['close'].astype(float).values

        tr_vals = []
        for i in range(1, len(close)):
            tr = max(
                high[i] - low[i],
                abs(high[i] - close[i - 1]),
                abs(low[i] - close[i - 1])
            )
            tr_vals.append(tr)

        if not tr_vals:
            return 0.02

        recent = tr_vals[-window:]
        atr = float(np.mean(recent))
        last_price = float(close[-1])
        return atr / last_price if last_price > 0 else 0.02
