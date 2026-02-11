"""
ShieldService v2.0 — Technical exit strategy and risk management.
Extracted from fallback_email_sender.py for modularity.
"""

import datetime
import logging
import akshare as ak

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
    def evaluate(symbol, current_price, days_held, return_pct, max_return_pct=0, kline_df=None, kline_cache=None):
        """
        Decision Logic for Shield v2.0
        Returns: (Action, Text, BgColor, FgColor)
        """
        # 1. Hard Rules (Priority 1)
        if return_pct <= -7.0:
            return "STOP LOSS", "⛔️ 止损 (-7%)", "#ef4444", "#ffffff"
        
        if return_pct >= 20.0:
            return "TAKE PROFIT", "💰 止盈 (>20%)", "#10b981", "#ffffff"
        
        # Trailing Stop
        if max_return_pct >= 15.0:
            drawdown = max_return_pct - return_pct
            if drawdown >= 5.0:
                return "TAKE PROFIT", f"💰 止盈 (回撤{drawdown:.1f}%)", "#059669", "#ffffff"
        
        if days_held > 10 and return_pct < 3.0:
            return "STAGNANT", "🌫 僵滞 (换股)", "#94a3b8", "#ffffff"
        if days_held > 5 and return_pct < 0:
            return "TIME OUT", "⏳ 超时 (负收益)", "#f97316", "#ffffff"

        # 2. Technical Rules (Priority 2)
        try:
            df = kline_df
            
            if df is None and kline_cache is not None:
                df = kline_cache.get(symbol)
            
            if df is None:
                logger.debug(f"Cache miss for {symbol}, fetching...")
                today = datetime.date.today().strftime("%Y%m%d")
                start = (datetime.date.today() - datetime.timedelta(days=60)).strftime("%Y%m%d")
                prefix = "sz" if symbol.startswith("0") or symbol.startswith("3") else "sh"
                df = ak.stock_zh_a_daily(symbol=prefix+symbol, start_date=start, end_date=today, adjust="qfq")
                if not df.empty:
                    ShieldService.calc_macd(df)
                    ShieldService.calc_kdj(df)
                    ShieldService.calc_ma(df, 20)
            
            if df is None or df.empty or len(df) < 30:
                return "HOLD", "🛡 持有 (数据少)", "#f1f5f9", "#475569"
            
            last = df.iloc[-1]
            prev = df.iloc[-2]
            
            score = 0
            reason = []
            
            # MACD Dead Cross
            if last['DIFF'] < last['DEA'] and prev['DIFF'] >= prev['DEA']:
                score += 30
                reason.append("MACD死叉")
            elif last['MACD'] < 0 and last['MACD'] < prev['MACD']:
                score += 10
            
            # KDJ High Dead Cross
            if last['K'] < last['D'] and prev['K'] >= prev['D']:
                if prev['K'] > 80:
                    score += 20
                    reason.append("KDJ高位死叉")
                else:
                    score += 10
            
            # Price VS MA20
            check_price = current_price if current_price > 0 else last['close']
            if check_price < last['MA20']:
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
