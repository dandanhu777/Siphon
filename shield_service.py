"""
ShieldService v3.0 — Technical exit strategy and risk management.
v3.0 improvements:
  - ATR-based dynamic stop-loss (volatility-adaptive)
  - Tiered trailing stop: +10% → 3% drawdown, +20% → 5% drawdown
  - Volume confirmation for death-cross signals
"""

import datetime
import logging
import akshare as ak
import pandas as pd

logger = logging.getLogger("SiphonSystem")


class ShieldService:
    """Technical analysis and exit decision logic."""

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
        """Calculate Average True Range for dynamic stop-loss."""
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
    def evaluate(symbol, current_price, days_held, return_pct, max_return_pct=0, kline_df=None, kline_cache=None):
        """
        Decision Logic for Shield v3.0
        Returns: (Action, Text, BgColor, FgColor)
        """
        # --- 1. Tiered Trailing Stop (Priority 1) ---
        # v3.0: Progressive trailing stop — tighter at lower gains, wider at higher
        if max_return_pct >= 20.0:
            drawdown = max_return_pct - return_pct
            if drawdown >= 5.0:
                return "TAKE PROFIT", f"💰 止盈 (峰值{max_return_pct:.0f}% 回撤{drawdown:.1f}%)", "#10b981", "#ffffff"
        elif max_return_pct >= 10.0:
            drawdown = max_return_pct - return_pct
            if drawdown >= 3.0:
                return "TAKE PROFIT", f"💰 移动止盈 (峰值{max_return_pct:.0f}% 回撤{drawdown:.1f}%)", "#059669", "#ffffff"

        # Stagnant and timeout rules
        if days_held > 10 and return_pct < 3.0:
            return "STAGNANT", "🌫 僵滞 (换股)", "#94a3b8", "#ffffff"
        if days_held > 5 and return_pct < 0:
            return "TIME OUT", "⏳ 超时 (负收益)", "#f97316", "#ffffff"

        # --- 2. Technical Rules with ATR + Volume Confirmation (Priority 2) ---
        try:
            df = kline_df

            if df is None and kline_cache is not None:
                df = kline_cache.get(symbol)

            if df is None:
                logger.debug(f"Cache miss for {symbol}, fetching...")
                today = datetime.date.today().strftime("%Y%m%d")
                start = (datetime.date.today() - datetime.timedelta(days=90)).strftime("%Y%m%d")
                prefix = "sz" if symbol.startswith("0") or symbol.startswith("3") else "sh"
                if symbol.startswith("4") or symbol.startswith("8"):
                    prefix = "bj"
                df = ak.stock_zh_a_daily(symbol=prefix+symbol, start_date=start, end_date=today, adjust="qfq")
                if not df.empty:
                    ShieldService.calc_macd(df)
                    ShieldService.calc_kdj(df)
                    ShieldService.calc_ma(df, 20)
                    ShieldService.calc_atr(df)

            if df is None or df.empty or len(df) < 30:
                return "HOLD", "🛡 持有 (数据少)", "#f1f5f9", "#475569"

            # Ensure ATR is calculated
            if 'ATR' not in df.columns:
                ShieldService.calc_atr(df)

            last = df.iloc[-1]
            prev = df.iloc[-2]

            # --- v3.0: ATR-based dynamic stop-loss ---
            atr = last.get('ATR', 0)
            if atr > 0 and current_price > 0:
                # Dynamic stop: 2x ATR from current price as percentage
                atr_stop_pct = -(atr * 2.0 / current_price * 100)
                # Clamp between -5% (tight) and -10% (loose)
                dynamic_stop = max(min(atr_stop_pct, -5.0), -10.0)
            else:
                dynamic_stop = -7.0  # Fallback to fixed stop

            if return_pct <= dynamic_stop:
                return "STOP LOSS", f"⛔️ 止损 (ATR止损线{dynamic_stop:.1f}%)", "#ef4444", "#ffffff"

            # --- Volume analysis for signal confirmation ---
            ma5_vol = df['volume'].iloc[-6:-1].mean() if len(df) >= 6 else df['volume'].mean()
            vol_ratio = last['volume'] / ma5_vol if ma5_vol > 0 else 1.0
            is_high_volume = vol_ratio >= 1.5  # Volume >= 1.5x MA5

            score = 0
            reason = []

            # MACD Dead Cross — with volume confirmation
            if last['DIFF'] < last['DEA'] and prev['DIFF'] >= prev['DEA']:
                if is_high_volume:
                    score += 35  # v3.0: Death cross + high volume = strong exit signal
                    reason.append(f"MACD死叉+放量{vol_ratio:.1f}x")
                else:
                    score += 15  # v3.0: Death cross + low volume = likely washout, weaker signal
                    reason.append("MACD死叉(缩量)")
            elif last['MACD'] < 0 and last['MACD'] < prev['MACD']:
                score += 10

            # KDJ High Dead Cross
            if last['K'] < last['D'] and prev['K'] >= prev['D']:
                if prev['K'] > 80:
                    if is_high_volume:
                        score += 25
                        reason.append("KDJ高位死叉+放量")
                    else:
                        score += 12  # Reduced: high KDJ cross but shrinking volume
                        reason.append("KDJ高位死叉(缩量)")
                else:
                    score += 10

            # Price VS MA20
            check_price = current_price if current_price > 0 else last['close']
            if 'MA20' in last.index and pd.notna(last['MA20']) and check_price < last['MA20']:
                score += 25
                reason.append("破生命线")

            # Final Decision
            if score >= 50:
                warning_text = "⚠️ 警示: " + ",".join(reason)
                if score >= 60: return "WARNING", warning_text, "#f59e0b", "#ffffff"
                return "WEAK", warning_text, "#fef3c7", "#92400e"

        except Exception as e:
            logger.warning(f"Shield Tech Error for {symbol}: {e}")

        return "HOLD", "🛡 持有 (趋势稳)", "#f1f5f9", "#475569"
