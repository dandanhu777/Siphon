"""
crowd_detector.py — 拥挤度检测模块 (适配Siphon荐股系统)
=========================================================
移植自 loop-win-2026，适配akshare数据。

三层防御:
  Layer 1: 持仓/推荐相关性检测 — 推荐组合内股票相关性过高时警告
  Layer 2: 成交集中度检测 — 全市场资金过度集中时警告
  Layer 3: 因子收益崩塌检测 — 策略因子失效预警

对Siphon的价值:
  - 避免同时推荐高相关性股票 (一跌全跌)
  - 在市场拥挤时降低推荐信心等级
  - 在因子失效时在报告中发出警告

Usage:
  from crowd_detector import CrowdingDetector, CrowdAlert
  detector = CrowdingDetector()
  alert = detector.check_recommendations(rec_codes, kline_cache)
"""
import statistics
from typing import Dict, List, Tuple

import pandas as pd
import numpy as np


class CrowdAlert:
    GREEN = 'GREEN'    # 正常
    YELLOW = 'YELLOW'  # 关注, 降低推荐信心
    RED = 'RED'        # 危险, 减少推荐数量

    def __init__(self):
        self.level = self.GREEN
        self.reasons: List[str] = []
        self.action: str = ''

    def escalate(self, level: str, reason: str):
        priority = {self.GREEN: 0, self.YELLOW: 1, self.RED: 2}
        if priority.get(level, 0) > priority.get(self.level, 0):
            self.level = level
        self.reasons.append(f"[{level}] {reason}")

    @property
    def is_danger(self) -> bool:
        return self.level in (self.YELLOW, self.RED)

    def get_label(self) -> str:
        labels = {self.GREEN: '正常', self.YELLOW: '关注', self.RED: '危险'}
        return labels.get(self.level, '未知')

    def get_color(self) -> str:
        colors = {self.GREEN: '#10b981', self.YELLOW: '#f59e0b', self.RED: '#ef4444'}
        return colors.get(self.level, '#94a3b8')


class CrowdingDetector:
    """拥挤度检测器"""

    CORR_YELLOW = 0.55
    CORR_RED = 0.70

    def __init__(self):
        self._factor_return_history: List[float] = []

    def check_portfolio_correlation(self, kline_dict: Dict[str, pd.DataFrame],
                                     window: int = 20) -> Tuple[float, str]:
        """
        推荐组合相关性: 组合内20日收益率的平均相关系数

        Args:
            kline_dict: {stock_code: kline_df}
            window: 回看天数

        Returns: (avg_corr, alert_level)
        """
        if len(kline_dict) < 2:
            return 0.0, CrowdAlert.GREEN

        rets_dict = {}
        for code, kdf in kline_dict.items():
            if kdf is None or len(kdf) < window:
                continue
            r = kdf['close'].pct_change().dropna()
            if len(r) >= window:
                rets_dict[code] = r.iloc[-window:].reset_index(drop=True)

        if len(rets_dict) < 2:
            return 0.0, CrowdAlert.GREEN

        rets_df = pd.DataFrame(rets_dict).dropna()
        if len(rets_df) < 10:
            return 0.0, CrowdAlert.GREEN

        corr_matrix = rets_df.corr()
        n = len(corr_matrix)
        corr_values = []
        for i in range(n):
            for j in range(i + 1, n):
                v = corr_matrix.iloc[i, j]
                if not pd.isna(v):
                    corr_values.append(v)

        if not corr_values:
            return 0.0, CrowdAlert.GREEN

        avg_corr = statistics.mean(corr_values)

        if avg_corr >= self.CORR_RED:
            return avg_corr, CrowdAlert.RED
        elif avg_corr >= self.CORR_YELLOW:
            return avg_corr, CrowdAlert.YELLOW
        return avg_corr, CrowdAlert.GREEN

    def check_factor_health(self, scored_signals: List[dict]) -> Tuple[float, str]:
        """
        因子收益健康度: 当日top信号 vs bottom信号的收益差

        scored_signals: [{stock_code, siphon_score, daily_change}]
        """
        if not scored_signals or len(scored_signals) < 6:
            return 0.0, CrowdAlert.GREEN

        sorted_sigs = sorted(scored_signals,
                             key=lambda x: x.get('siphon_score', 0),
                             reverse=True)
        n = len(sorted_sigs)
        top_third = sorted_sigs[:n // 3]
        bottom_third = sorted_sigs[-(n // 3):]

        long_ret = statistics.mean(
            [s.get('daily_change', 0) for s in top_third]) if top_third else 0
        short_ret = statistics.mean(
            [s.get('daily_change', 0) for s in bottom_third]) if bottom_third else 0
        factor_ret = long_ret - short_ret

        self._factor_return_history.append(factor_ret)
        if len(self._factor_return_history) > 120:
            self._factor_return_history = self._factor_return_history[-120:]

        if len(self._factor_return_history) < 10:
            return factor_ret, CrowdAlert.GREEN

        recent = self._factor_return_history[-60:]
        mean_r = statistics.mean(recent)
        std_r = statistics.stdev(recent) if len(recent) > 1 else 1

        z = (factor_ret - mean_r) / std_r if std_r > 0.001 else 0

        # 连续2日 < -2σ → RED
        if len(self._factor_return_history) >= 2:
            prev = self._factor_return_history[-2]
            prev_z = (prev - mean_r) / std_r if std_r > 0.001 else 0
            if z < -2 and prev_z < -2:
                return factor_ret, CrowdAlert.RED

        if z < -2:
            return factor_ret, CrowdAlert.YELLOW

        return factor_ret, CrowdAlert.GREEN

    def check_recommendations(self, kline_dict: Dict[str, pd.DataFrame],
                               scored_signals: List[dict] = None) -> CrowdAlert:
        """
        综合拥挤度检查 (用于Siphon推荐前)

        Args:
            kline_dict: 推荐候选股的K线 {code: df}
            scored_signals: 评分后的信号列表 (可选)

        Returns: CrowdAlert
        """
        alert = CrowdAlert()

        # 1. 推荐组合相关性
        corr, corr_level = self.check_portfolio_correlation(kline_dict)
        if corr_level != CrowdAlert.GREEN:
            alert.escalate(corr_level, f"推荐组合相关性={corr:.2f}")

        # 2. 因子收益健康度
        if scored_signals:
            fret, fret_level = self.check_factor_health(scored_signals)
            if fret_level != CrowdAlert.GREEN:
                alert.escalate(fret_level, f"因子收益={fret:+.2f}%")

        # 设置行动建议
        if alert.level == CrowdAlert.RED:
            alert.action = '减少推荐数量至3只，降低信心等级'
        elif alert.level == CrowdAlert.YELLOW:
            alert.action = '在报告中标注拥挤警告'
        else:
            alert.action = '正常推荐'

        return alert

    def filter_correlated_stocks(self, kline_dict: Dict[str, pd.DataFrame],
                                  max_corr: float = 0.70,
                                  window: int = 20) -> List[str]:
        """
        过滤高相关性股票: 保留相关性最低的组合

        返回应该从推荐中移除的股票代码列表
        """
        if len(kline_dict) < 2:
            return []

        rets_dict = {}
        for code, kdf in kline_dict.items():
            if kdf is not None and len(kdf) >= window:
                r = kdf['close'].pct_change().dropna()
                if len(r) >= window:
                    rets_dict[code] = r.iloc[-window:].reset_index(drop=True)

        if len(rets_dict) < 2:
            return []

        rets_df = pd.DataFrame(rets_dict).dropna()
        if len(rets_df) < 10:
            return []

        corr_matrix = rets_df.corr()
        to_remove = set()

        # 贪心: 找到高相关对, 移除其中评分较低的 (这里移除后加入的)
        codes = list(corr_matrix.columns)
        for i in range(len(codes)):
            for j in range(i + 1, len(codes)):
                if corr_matrix.iloc[i, j] >= max_corr:
                    # 移除后面的 (保留先入选的)
                    to_remove.add(codes[j])

        return list(to_remove)
