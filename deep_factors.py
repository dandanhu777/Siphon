"""
深度因子计算模块 — 超越简单价量的Alpha来源 (适配Siphon荐股系统)
=================================================================
移植自 loop-win-2026，适配akshare数据源。

因子列表:
  1. RESID_MOM (残差动量) — 去除市场beta后的个股alpha残差
  2. IVOL (特质波动率) — 残差收益标准差, 低IVOL溢价
  3. LU_STRENGTH (封板强度) — 涨停封板次数和封板坚定度
  4. TAIL_ANOMALY (尾盘异动) — 尾盘成交量占比z-score (需5min数据，可选)
  5. OFI (订单流不平衡) — 买卖压力方向推断 (需5min数据，可选)

所有因子严格 point-in-time，不使用未来数据。

Usage:
  from deep_factors import DeepFactorEngine
  engine = DeepFactorEngine(kline_cache)
  factors = engine.compute_for_stock(stock_code, kline_df, index_df)
  deep_score = engine.compute_cross_section(candidates_dict, index_df)
"""
import statistics
from typing import Dict, List, Optional

import pandas as pd
import numpy as np


class DeepFactorEngine:
    """深度因子计算引擎 — 适配Siphon的akshare K线数据"""

    def __init__(self, kline_cache=None):
        """
        Args:
            kline_cache: KlineCache实例，用于获取历史K线
        """
        self.kline_cache = kline_cache

    def calc_residual_momentum(self, stock_df: pd.DataFrame,
                                index_df: pd.DataFrame = None,
                                window: int = 60) -> Optional[float]:
        """
        残差动量: 去除市场beta后的个股alpha

        步骤:
          1. 取过去window日的个股日收益率
          2. 减去市场指数日收益率
          3. 最近20日加权残差累积 = residual momentum

        经济学: 捕捉个股独立于大盘的alpha动量
        """
        if stock_df is None or len(stock_df) < window:
            return None

        stock_rets = stock_df['close'].pct_change().dropna()
        if len(stock_rets) < window:
            return None
        stock_rets = stock_rets.iloc[-window:]

        if index_df is not None and len(index_df) >= window:
            idx_rets = index_df['close'].pct_change().dropna()
            idx_rets = idx_rets.iloc[-window:]
            # 对齐长度
            min_len = min(len(stock_rets), len(idx_rets))
            residuals = stock_rets.values[-min_len:] - idx_rets.values[-min_len:]
        else:
            residuals = stock_rets.values

        if len(residuals) < 20:
            return None

        # 最近20日加权残差动量
        recent = residuals[-20:]
        weights = np.linspace(0.5, 1.5, len(recent))
        weighted_resid = (recent * weights).sum() / weights.sum()

        return float(weighted_resid)

    def calc_ivol(self, stock_df: pd.DataFrame,
                  index_df: pd.DataFrame = None,
                  window: int = 60) -> Optional[float]:
        """
        特质波动率 (Idiosyncratic Volatility)

        低IVOL溢价: IVOL低的股票未来收益更高 (Ang-Hodrick-Xing 2006)
        返回负IVOL (低IVOL = 高分)
        """
        if stock_df is None or len(stock_df) < window:
            return None

        stock_rets = stock_df['close'].pct_change().dropna()
        if len(stock_rets) < window:
            return None
        stock_rets = stock_rets.iloc[-window:]

        if index_df is not None and len(index_df) >= window:
            mkt_rets = index_df['close'].pct_change().dropna().iloc[-window:]
            min_len = min(len(stock_rets), len(mkt_rets))
            sr = stock_rets.values[-min_len:]
            mr = mkt_rets.values[-min_len:]

            if len(sr) < 30:
                return None

            # OLS: stock_ret = alpha + beta * market_ret + epsilon
            mr_mean = np.mean(mr)
            sr_mean = np.mean(sr)
            cov = np.sum((mr - mr_mean) * (sr - sr_mean))
            var = np.sum((mr - mr_mean) ** 2)
            beta = cov / var if var > 0 else 0
            alpha = sr_mean - beta * mr_mean
            residuals = sr - alpha - beta * mr
            ivol = float(np.std(residuals))
        else:
            ivol = float(np.std(stock_rets.values))

        # 返回负IVOL (低IVOL = 高分)
        return -ivol

    def calc_lu_strength(self, stock_df: pd.DataFrame,
                         stock_code: str = '',
                         lookback: int = 20) -> Optional[float]:
        """
        封板强度: 过去lookback日内涨停封板的次数和封板坚定度

        计算:
          1. 扫描过去lookback日, 找到涨停日 (close >= limit_up)
          2. 涨停当日的成交量越低 → 封板越坚定 (惜售)
          3. lu_strength = sum(1/vol_ratio) for 涨停日 / lookback
        """
        if stock_df is None or len(stock_df) < lookback + 1:
            return None

        recent = stock_df.iloc[-(lookback + 1):].copy()
        prev_closes = recent['close'].shift(1)

        # 涨跌停幅度：科创板/创业板20%，其他10%
        is_20pct = stock_code.startswith(('688', '300', '301'))
        limit_pct = 0.195 if is_20pct else 0.095

        lu_score = 0.0
        for i in range(1, len(recent)):
            row = recent.iloc[i]
            prev_c = prev_closes.iloc[i]
            if pd.isna(prev_c) or prev_c <= 0:
                continue
            change = (row['close'] - prev_c) / prev_c
            if change >= limit_pct:
                vol = row.get('volume', 0)
                avg_vol = recent.iloc[max(0, i - 5):i]['volume'].mean()
                if avg_vol > 0 and vol > 0:
                    vol_ratio = vol / avg_vol
                    lu_score += min(2.0, 1.0 / max(vol_ratio, 0.5))

        return lu_score / lookback if lookback > 0 else 0

    def calc_tail_anomaly_from_daily(self, stock_df: pd.DataFrame,
                                      lookback: int = 10) -> Optional[float]:
        """
        尾盘异动近似 (用日线数据): 用收盘位置(close-low)/(high-low)的z-score近似

        经济学: 收盘强势(高收盘位置) = 机构尾盘买入信号
        无5min数据时的合理近似
        """
        if stock_df is None or len(stock_df) < lookback + 1:
            return None

        recent = stock_df.iloc[-(lookback + 1):]
        close_positions = []
        for _, row in recent.iterrows():
            hl_range = row['high'] - row['low']
            if hl_range > 0:
                cp = (row['close'] - row['low']) / hl_range
                close_positions.append(cp)

        if len(close_positions) < 3:
            return None

        mean_cp = statistics.mean(close_positions)
        std_cp = statistics.stdev(close_positions) if len(close_positions) > 1 else 0.01

        if std_cp < 0.001:
            return 0.0
        latest_cp = close_positions[-1]
        z = (latest_cp - mean_cp) / std_cp

        return float(z)

    def compute_for_stock(self, stock_code: str,
                          stock_df: pd.DataFrame,
                          index_df: pd.DataFrame = None) -> Dict[str, Optional[float]]:
        """计算单只股票的所有深度因子"""
        return {
            'resid_mom': self.calc_residual_momentum(stock_df, index_df),
            'ivol': self.calc_ivol(stock_df, index_df),
            'lu_strength': self.calc_lu_strength(stock_df, stock_code),
            'tail_anomaly': self.calc_tail_anomaly_from_daily(stock_df),
        }

    def compute_cross_section(self, candidates: Dict[str, pd.DataFrame],
                               index_df: pd.DataFrame = None) -> pd.DataFrame:
        """
        批量计算深度因子横截面, 返回 DataFrame

        Args:
            candidates: {stock_code: kline_df}
            index_df: 指数K线 DataFrame

        Returns:
            DataFrame with columns: stock_code, resid_mom, ivol, lu_strength,
            tail_anomaly, deep_score (0-100)
        """
        rows = []
        for code, kdf in candidates.items():
            factors = self.compute_for_stock(code, kdf, index_df)
            factors['stock_code'] = code
            rows.append(factors)

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)

        # Z-score 标准化 + 等权合成
        factor_cols = ['resid_mom', 'ivol', 'lu_strength', 'tail_anomaly']
        for col in factor_cols:
            if col in df.columns:
                vals = pd.to_numeric(df[col], errors='coerce')
                mean_v = vals.mean()
                std_v = vals.std()
                if std_v and std_v > 0:
                    df[f'{col}_z'] = ((vals - mean_v) / std_v).clip(-3, 3)
                else:
                    df[f'{col}_z'] = 0.0
            else:
                df[f'{col}_z'] = 0.0

        z_cols = [f'{c}_z' for c in factor_cols]
        df['deep_score'] = df[z_cols].mean(axis=1) * 20 + 50  # 映射到 ~30-70
        df['deep_score'] = df['deep_score'].clip(0, 100)

        return df
