"""
strategy_reversal.py — 均值回归反转策略 (适配Siphon荐股系统)
=============================================================
移植自 loop-win-2026，用akshare替代xtdata。

反转信号条件:
  1. 3日跌幅 > 5% (超卖)
  2. 量比 < 1.5 (非恐慌抛售)
  3. 价格在MA20附近 (趋势基础存在)
  4. 板块相对强势 (板块未崩)

对Siphon的价值:
  - 补充动量策略，在超卖时捕捉反弹机会
  - strategy_tag='Reversal' 区分于动量信号
  - 在报告中单独展示反转推荐

Usage:
  from strategy_reversal import ReversalScanner
  scanner = ReversalScanner()
  signals = scanner.scan(kline_dict, hot_industries)
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Optional


# 参数配置
REVERSAL_3D_DROP = -5.0     # 3日最低跌幅阈值
MAX_VOL_RATIO = 1.5         # 最大量比 (超过则为恐慌抛售)
MA20_TOLERANCE = 0.03       # MA20容差 (3%以内算在MA20附近)
MIN_LOOKBACK = 25           # 最少K线天数


class ReversalScanner:
    """均值回归反转信号扫描器"""

    def scan(self, kline_dict: Dict[str, pd.DataFrame],
             hot_industries: List[str] = None,
             industry_map: Dict[str, str] = None) -> List[dict]:
        """
        扫描反转信号

        Args:
            kline_dict: {stock_code: kline_df} 候选股K线
            hot_industries: 当前热门行业列表 (加分用)
            industry_map: {stock_code: industry_name}

        Returns: 反转信号列表 [{stock_code, stock_name, reversal_score,
                              rec_price, strategy_tag, core_logic}]
        """
        if not kline_dict:
            return []

        candidates = []
        for code, kdf in kline_dict.items():
            result = self._evaluate_stock(code, kdf)
            if result is not None:
                candidates.append(result)

        if not candidates:
            return []

        # 排名打分
        cdf = pd.DataFrame(candidates)
        cdf['pct_rank'] = cdf['pct_3d'].rank(pct=True, ascending=True)  # 跌多的排前
        cdf['vol_rank'] = (1 - cdf['vol_ratio'].rank(pct=True))  # 缩量的排前
        cdf['reversal_score'] = (
            cdf['pct_rank'] * 0.60 +
            cdf['vol_rank'] * 0.40
        ) * 100
        cdf['reversal_score'] = cdf['reversal_score'].clip(0, 100)

        # 板块加分
        if hot_industries and industry_map:
            for idx, row in cdf.iterrows():
                ind = industry_map.get(row['stock_code'], '')
                if ind in hot_industries:
                    cdf.at[idx, 'reversal_score'] = min(100, row['reversal_score'] + 10)

        cdf = cdf.sort_values('reversal_score', ascending=False)
        top = cdf.head(5)  # 最多5个反转信号

        signals = []
        for _, row in top.iterrows():
            signals.append({
                'stock_code': row['stock_code'],
                'stock_name': row.get('stock_name', ''),
                'siphon_score': round(row['reversal_score'], 1),
                'rec_price': round(row['close'], 2),
                'strategy_tag': f"Reversal 3d={row['pct_3d']:.1f}% Vol={row['vol_ratio']:.1f}x",
                'core_logic': (f"超卖反弹: 3日跌{row['pct_3d']:.1f}%, "
                               f"量比{row['vol_ratio']:.1f}x(缩量), "
                               f"MA20支撑{'有效' if row['above_ma20'] else '待确认'}"),
            })

        return signals

    def _evaluate_stock(self, stock_code: str,
                        kdf: pd.DataFrame) -> Optional[dict]:
        """评估单只股票的反转条件"""
        if kdf is None or len(kdf) < MIN_LOOKBACK:
            return None

        close = kdf['close'].values
        volume = kdf['volume'].values
        high = kdf['high'].values
        low = kdf['low'].values

        # 3日跌幅
        if close[-4] <= 0:
            return None
        pct_3d = (close[-1] / close[-4] - 1) * 100

        # 条件1: 3日跌幅 > 阈值
        if pct_3d > REVERSAL_3D_DROP:
            return None

        # 条件2: 量比 < 阈值 (缩量 = 非恐慌)
        avg_vol5 = np.mean(volume[-6:-1])
        if avg_vol5 <= 0:
            return None
        vol_ratio = volume[-1] / avg_vol5
        if vol_ratio > MAX_VOL_RATIO:
            return None

        # 条件3: MA20支撑
        if len(close) < 20:
            return None
        ma20 = np.mean(close[-20:])
        above_ma20 = close[-1] >= ma20 * (1 - MA20_TOLERANCE)

        # 需要MA20支撑 (在MA20上方或3%以内)
        if not above_ma20:
            return None

        # 获取股票名称
        stock_name = ''
        if hasattr(kdf, 'attrs') and 'name' in kdf.attrs:
            stock_name = kdf.attrs['name']

        return {
            'stock_code': stock_code,
            'stock_name': stock_name,
            'pct_3d': pct_3d,
            'vol_ratio': vol_ratio,
            'ma20': ma20,
            'close': close[-1],
            'above_ma20': above_ma20,
        }
