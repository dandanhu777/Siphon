"""
KlineCache — Batch K-line pre-fetch and caching for tracked stocks.
Extracted from fallback_email_sender.py for modularity.
"""

import datetime
import time
import logging
import akshare as ak

logger = logging.getLogger("SiphonSystem")


class KlineCache:
    """
    Pre-fetches and caches 60-day K-line data for all tracked stocks.
    Reduces API calls from 3N to N (where N = number of tracked stocks).
    """
    def __init__(self):
        self.cache = {}
        self.today = datetime.date.today().strftime("%Y%m%d")
        self.start = (datetime.date.today() - datetime.timedelta(days=60)).strftime("%Y%m%d")
    
    def prefetch(self, symbols: list, shield_service=None):
        """Batch fetch K-line data for all symbols."""
        logger.info(f"📊 Pre-fetching K-line data for {len(symbols)} stocks...")
        success_count = 0
        for symbol in symbols:
            if symbol in self.cache:
                continue
            try:
                prefix = "sz" if symbol.startswith("0") or symbol.startswith("3") else "sh"
                df = ak.stock_zh_a_daily(symbol=prefix+symbol, start_date=self.start, end_date=self.today, adjust="qfq")
                if not df.empty and len(df) >= 30:
                    # Pre-calculate indicators if ShieldService available
                    if shield_service:
                        shield_service.calc_macd(df)
                        shield_service.calc_kdj(df)
                        shield_service.calc_ma(df, 20)
                    self.cache[symbol] = df
                    success_count += 1
            except Exception as e:
                logger.warning(f"KlineCache: Failed {symbol}: {e}")
            time.sleep(0.1)  # Rate limiting
        logger.info(f"✅ Pre-fetched {success_count}/{len(symbols)} stocks successfully.")
    
    def get(self, symbol):
        """Get cached K-line DataFrame for a symbol."""
        return self.cache.get(symbol)
    
    def get_max_high(self, symbol, start_date_str):
        """Get max high price since start_date."""
        df = self.cache.get(symbol)
        if df is None:
            return None
        try:
            df_filtered = df[df['date'] >= start_date_str]
            if df_filtered.empty:
                return df['high'].max()
            return df_filtered['high'].max()
        except Exception:
            return df['high'].max() if not df.empty else None
    
    def get_verified_price(self, symbol, date_str):
        """Get close price on a specific date for verification."""
        df = self.cache.get(symbol)
        if df is None:
            return None
        try:
            df['date_str'] = df['date'].astype(str)
            match = df[df['date_str'] == date_str]
            if not match.empty:
                return float(match.iloc[0]['close'])
            df_before = df[df['date_str'] <= date_str]
            if not df_before.empty:
                return float(df_before.iloc[-1]['close'])
        except Exception:
            pass
        return None
