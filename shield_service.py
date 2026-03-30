"""
ShieldService v4.0 — 多层退出建议引擎 (移植loop-win-2026 P0-P5逻辑)
=====================================================================
v4.0 增强:
  - P0 动态利润保护 (峰值收益的40%-60%保护)
  - P0.5 自适应追踪止损 (ATR倍数随峰值动态调整)
  - P1 ATR+相对止损 (绝对+指数相对)
  - P2 T+1恢复陷阱 (次日冲高回落检测)
  - P3 脉冲破板检测 (日内高点>7%回落)
  - P4 高换手+MA5判决 (量价背离)
  - P5 僵尸股清理 (持有>7日无表现)
  - 市场状态自适应 (CALM/VOLATILE/PANIC参数调整)
  - VWAP弱势确认
"""

import datetime
import logging
import akshare as ak
import pandas as pd
import numpy as np

logger = logging.getLogger("SiphonSystem")


class ShieldService:
    """多层退出建议引擎 — 从loop-win-2026移植的P0-P5规则"""

    @staticmethod
    def calc_macd(df):
        ema12 = df['close'].ewm(span=12, adjust=False).mean()
        ema26 = df['close'].ewm(span=26, adjust=False).mean()
        df['DIFF'] = ema12 - ema26
        df['DEA'] = df['DIFF'].ewm(span=9, adjust=False).mean()
        df['MACD'] = 2 * (df['DIFF'] - df['DEA'])
        return df

    @staticmethod
    def calc_kdj(df):
        low_list = df['low'].rolling(9).min()
        high_list = df['high'].rolling(9).max()
        rsv = (df['close'] - low_list) / (high_list - low_list) * 100
        df['K'] = rsv.ewm(com=2, adjust=False).mean()
        df['D'] = df['K'].ewm(com=2, adjust=False).mean()
        df['J'] = 3 * df['K'] - 2 * df['D']
        return df

    @staticmethod
    def calc_ma(df, window=20):
        df[f'MA{window}'] = df['close'].rolling(window).mean()
        return df

    @staticmethod
    def calc_atr(df, period=14):
        """Calculate Average True Range."""
        high = df['high']
        low = df['low']
        prev_close = df['close'].shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs()
        ], axis=1).max(axis=1)
        df['ATR'] = tr.rolling(period).mean()
        return df

    @staticmethod
    def calc_vwap(df, window=5):
        """计算滚动VWAP"""
        if 'amount' in df.columns:
            amount = df['amount']
        else:
            amount = (df['high'] + df['low'] + df['close']) / 3 * df['volume']
        rolling_amount = amount.rolling(window).sum()
        rolling_vol = df['volume'].rolling(window).sum()
        df['VWAP'] = rolling_amount / rolling_vol.replace(0, np.nan)
        return df

    @staticmethod
    def evaluate(symbol, current_price, days_held, return_pct,
                 max_return_pct=0, kline_df=None, kline_cache=None,
                 regime_params=None, index_return=None):
        """
        多层退出决策引擎 v4.0

        新增参数:
            regime_params: 市场状态参数 (来自RegimeSensor.get_exit_params())
            index_return: 指数同期收益% (用于相对止损)

        Returns: (Action, Text, BgColor, FgColor)
        """
        # 默认regime参数 (CALM)
        if regime_params is None:
            regime_params = {
                'trailing_stop_mult': 1.0,
                'atr_stop_mult': 1.0,
                'stagnant_days': 10,
                'timeout_days': 5,
            }

        trail_mult = regime_params.get('trailing_stop_mult', 1.0)
        atr_mult = regime_params.get('atr_stop_mult', 1.0)
        stagnant_days = regime_params.get('stagnant_days', 10)
        timeout_days = regime_params.get('timeout_days', 5)

        # ═══ P0: 动态利润保护 (峰值保护) ═══
        if max_return_pct >= 20.0:
            floor = max(max_return_pct * 0.60, 10.0) * trail_mult
            if return_pct < floor:
                return ("TAKE PROFIT",
                        f"P0 止盈保护 (峰值{max_return_pct:.0f}% 保护线{floor:.0f}% 当前{return_pct:.1f}%)",
                        "#10b981", "#ffffff")
        elif max_return_pct >= 10.0:
            floor = max(max_return_pct * 0.50, 5.0) * trail_mult
            if return_pct < floor:
                return ("TAKE PROFIT",
                        f"P0 移动止盈 (峰值{max_return_pct:.0f}% 保护线{floor:.0f}% 当前{return_pct:.1f}%)",
                        "#059669", "#ffffff")
        elif max_return_pct >= 5.0:
            floor = max(max_return_pct * 0.40, 2.0) * trail_mult
            if return_pct < floor:
                return ("TAKE PROFIT",
                        f"P0 小利保护 (峰值{max_return_pct:.0f}% 保护线{floor:.0f}%)",
                        "#34d399", "#000000")

        # ═══ P0.5: 自适应追踪止损 (ATR倍数随峰值调整) ═══
        # 读取K线计算ATR
        try:
            df = kline_df
            if df is None and kline_cache is not None:
                df = kline_cache.get(symbol)
            if df is None:
                today = datetime.date.today().strftime("%Y%m%d")
                start = (datetime.date.today() - datetime.timedelta(days=90)).strftime("%Y%m%d")
                prefix = "sz" if symbol.startswith(("0", "3")) else "sh"
                if symbol.startswith(("4", "8")):
                    prefix = "bj"
                df = ak.stock_zh_a_daily(symbol=prefix + symbol,
                                         start_date=start, end_date=today, adjust="qfq")
                if df is not None and not df.empty:
                    ShieldService.calc_macd(df)
                    ShieldService.calc_kdj(df)
                    ShieldService.calc_ma(df, 5)
                    ShieldService.calc_ma(df, 20)
                    ShieldService.calc_atr(df)
                    ShieldService.calc_vwap(df)

            if df is None or df.empty or len(df) < 30:
                return "HOLD", "持有 (数据不足)", "#f1f5f9", "#475569"

            # 确保指标已计算
            if 'ATR' not in df.columns:
                ShieldService.calc_atr(df)
            if 'VWAP' not in df.columns:
                ShieldService.calc_vwap(df)
            if 'MA5' not in df.columns:
                ShieldService.calc_ma(df, 5)
            if 'MA20' not in df.columns:
                ShieldService.calc_ma(df, 20)

            last = df.iloc[-1]
            prev = df.iloc[-2]
            atr = last.get('ATR', 0)
            atr_pct = (atr / current_price * 100) if (atr > 0 and current_price > 0) else 3.0

            # P0.5: 追踪止损幅度随峰值动态调整
            if max_return_pct >= 30:
                trail_threshold = atr_pct * 0.8 * trail_mult  # 紧追
            elif max_return_pct >= 15:
                trail_threshold = atr_pct * 1.0 * trail_mult
            elif max_return_pct >= 3:
                trail_threshold = atr_pct * 1.5 * trail_mult
            else:
                trail_threshold = 999  # 不触发

            drawdown_from_peak = max_return_pct - return_pct
            vwap = last.get('VWAP', 0)
            is_below_vwap = current_price < vwap if vwap and vwap > 0 else False

            if drawdown_from_peak >= trail_threshold and max_return_pct >= 3:
                vwap_tag = "+VWAP弱势" if is_below_vwap else ""
                return ("TAKE PROFIT",
                        f"P0.5 追踪止盈 (回撤{drawdown_from_peak:.1f}% > {trail_threshold:.1f}%{vwap_tag})",
                        "#059669", "#ffffff")

            # ═══ P1: ATR + 相对止损 ═══
            atr_stop = min(8.0, max(3.0, atr_pct * 2.5 * atr_mult))
            relative_pnl = return_pct - (index_return or 0)

            if return_pct <= -atr_stop:
                if return_pct <= -7.5:
                    return ("STOP LOSS",
                            f"P1 紧急止损 (跌{return_pct:.1f}% > 极限-7.5%)",
                            "#ef4444", "#ffffff")
                if relative_pnl <= -3.0 and is_below_vwap:
                    return ("STOP LOSS",
                            f"P1 ATR止损 (跌{return_pct:.1f}% 相对指数{relative_pnl:+.1f}% ATR线-{atr_stop:.1f}%)",
                            "#ef4444", "#ffffff")

            # ═══ P2: T+1 恢复陷阱 ═══
            if days_held == 1:
                today_high_pct = 0
                if current_price > 0 and 'high' in last.index:
                    # 用最近价格估算
                    rec_price = current_price / (1 + return_pct / 100) if return_pct != -100 else current_price
                    if rec_price > 0:
                        today_high_pct = (float(last['high']) / rec_price - 1) * 100
                if today_high_pct < 3.0 and return_pct < -3.0 and is_below_vwap:
                    return ("WARNING",
                            f"P2 T+1陷阱 (日高{today_high_pct:.1f}%<3% 当前{return_pct:.1f}% VWAP下方)",
                            "#f59e0b", "#ffffff")

            # ═══ P3: 脉冲破板检测 ═══
            if days_held <= 2 and 'high' in last.index:
                rec_price = current_price / (1 + return_pct / 100) if return_pct != -100 else current_price
                if rec_price > 0:
                    today_high_pct = (float(last['high']) / rec_price - 1) * 100
                    if today_high_pct >= 7.0:
                        from_high_drop = today_high_pct - return_pct
                        if from_high_drop >= 3.0 and is_below_vwap:
                            return ("WARNING",
                                    f"P3 脉冲回落 (日高{today_high_pct:.0f}% 回落{from_high_drop:.1f}% VWAP下方)",
                                    "#f59e0b", "#ffffff")

            # ═══ P4: 高换手 + MA5判决 ═══
            if days_held >= 2:
                ma5_vol = df['volume'].iloc[-6:-1].mean() if len(df) >= 6 else df['volume'].mean()
                vol_ratio = last['volume'] / ma5_vol if ma5_vol > 0 else 1.0

                if vol_ratio > 1.5:
                    ma5 = last.get('MA5', 0)
                    if ma5 > 0 and current_price < ma5 * 1.01:
                        return ("WARNING",
                                f"P4 量价背离 (换手率{vol_ratio:.1f}x 破MA5)",
                                "#f59e0b", "#ffffff")

            # ═══ P5: 僵尸股清理 ═══
            if days_held > 7 and return_pct < -3.0:
                return ("STAGNANT",
                        f"P5 僵尸持仓 ({days_held}天 收益{return_pct:.1f}%)",
                        "#94a3b8", "#ffffff")

            # 僵滞和超时 (受regime影响)
            if days_held > stagnant_days and return_pct < 3.0:
                return ("STAGNANT",
                        f"僵滞 ({days_held}天 仅{return_pct:.1f}% 换股)",
                        "#94a3b8", "#ffffff")
            if days_held > timeout_days and return_pct < 0:
                return ("TIME OUT",
                        f"超时 ({days_held}天 负收益{return_pct:.1f}%)",
                        "#f97316", "#ffffff")

            # ═══ 技术信号评分 (保留v3.0逻辑 + 增强) ═══
            ma5_vol = df['volume'].iloc[-6:-1].mean() if len(df) >= 6 else df['volume'].mean()
            vol_ratio = last['volume'] / ma5_vol if ma5_vol > 0 else 1.0
            is_high_volume = vol_ratio >= 1.5

            score = 0
            reason = []

            # MACD死叉 + 量确认
            if last['DIFF'] < last['DEA'] and prev['DIFF'] >= prev['DEA']:
                if is_high_volume:
                    score += 35
                    reason.append(f"MACD死叉+放量{vol_ratio:.1f}x")
                else:
                    score += 15
                    reason.append("MACD死叉(缩量)")
            elif last['MACD'] < 0 and last['MACD'] < prev['MACD']:
                score += 10

            # KDJ高位死叉
            if last['K'] < last['D'] and prev['K'] >= prev['D']:
                if prev['K'] > 80:
                    if is_high_volume:
                        score += 25
                        reason.append("KDJ高位死叉+放量")
                    else:
                        score += 12
                        reason.append("KDJ高位死叉(缩量)")
                else:
                    score += 10

            # 破MA20
            check_price = current_price if current_price > 0 else last['close']
            if 'MA20' in last.index and pd.notna(last['MA20']) and check_price < last['MA20']:
                score += 25
                reason.append("破生命线")

            # VWAP下方加分
            if is_below_vwap:
                score += 10
                reason.append("VWAP下方")

            if score >= 50:
                warning_text = "技术警示: " + ",".join(reason)
                if score >= 60:
                    return "WARNING", warning_text, "#f59e0b", "#ffffff"
                return "WEAK", warning_text, "#fef3c7", "#92400e"

        except Exception as e:
            logger.warning(f"Shield Tech Error for {symbol}: {e}")

        return "HOLD", "持有 (趋势稳)", "#f1f5f9", "#475569"
