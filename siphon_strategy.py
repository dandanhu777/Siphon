
import akshare as ak
import pandas as pd
import time
import datetime
import os
import functools
import warnings
import pickle
import random


# Suppress warnings
warnings.filterwarnings('ignore')

# --- Configuration ---
CACHE_DIR = "data_cache"
if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR)

TARGET_INDUSTRIES = [
    '半导体', '电子元件', '光学光电子', 
    '通信设备', '计算机设备', '软件开发', '互联网服务',
    '光伏设备', '风电设备', '电网设备', '电池' 
]

MIN_MARKET_CAP = 200 * 10000 * 10000 # 20 Billion CNY

from dataclasses import dataclass

@dataclass
class StrategyConfig:
    """v6.0: Aggressive short-term momentum arbitrage config."""
    # Filtering thresholds (relaxed for momentum)
    max_drop_pct: float = -3.0
    max_gain_5d: float = 25.0         # Relaxed from 15.0
    max_rsi: float = 80.0             # Relaxed from 75.0
    limit_up_threshold: float = 8.5
    max_swing_3d: float = 15.0        # Relaxed from 10.0
    # Fundamental filters
    min_growth: float = 10.0
    high_growth: float = 30.0
    max_peg: float = 1.5
    # Technical filters
    ma_period: int = 50
    min_avg_volume: int = 1_000_000
    vcp_vol_ratio: float = 0.6
    vcp_steady_ratio: float = 1.5
    # Scoring
    min_ag_score: float = 2.0         # Lowered from 5.0
    min_composite_score: float = 30.0 # Lowered from 40.0
    sector_momentum_pct: float = 0.4
    # v6.0: Momentum params
    vol_explosion_multiplier: float = 2.0  # Volume explosion threshold
    # Processing
    max_process: int = 300

CONFIG = StrategyConfig()

# --- Utilities ---
def retry(times=3, initial_delay=2):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            delay = initial_delay
            for i in range(times):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if i < times - 1:
                        sleep_time = delay * (2 ** i)
                        print(f"[Warning] {func.__name__} failed (Attempt {i+1}/{times}). Retrying in {sleep_time}s... Error: {e}")
                        time.sleep(sleep_time + random.random())
                    else:
                        print(f"[Error] {func.__name__} failed after {times} retries.")
            return None
        return wrapper
    return decorator


# --- Data Fetching ---


def fetch_basic_pool():
    print("Fetching Spot Data (Market Cap & Industry)...")
    spot_df = None
    source = None
    
    # 1. Try Tencent/Sina FIRST (Primary) — works during market hours
    try:
        print("📡 Trying Tencent/Sina source (Primary)...")
        spot_df = ak.stock_zh_a_spot()
        if spot_df is not None and not spot_df.empty:
            source = "tencent"
            # Strip market prefix from code (e.g. "sh600000" -> "600000")
            spot_df['代码'] = spot_df['代码'].str.replace(r'^(sh|sz|bj)', '', regex=True)
            # Fill missing columns
            spot_df['量比'] = 1.0
            spot_df['换手率'] = 0.0
            spot_df['市盈率-动态'] = 0.0
            spot_df['总市值'] = 0
            print(f"✅ Tencent source success: {len(spot_df)} stocks")
    except Exception as e:
        print(f"⚠️ Tencent failed: {e}")
    
    # 2. Fallback to EastMoney — works during market hours
    if spot_df is None or spot_df.empty:
        try:
            print("🔄 Trying EastMoney fallback...")
            spot_df = ak.stock_zh_a_spot_em()
            if spot_df is not None and not spot_df.empty:
                source = "eastmoney"
                print(f"✅ EastMoney fallback success: {len(spot_df)} stocks")
        except Exception as e2:
            print(f"❌ EastMoney also failed: {e2}")
    
    # 3. Ultimate Fallback: Build pool from Industry data + Sina Daily bars
    #    Uses stock_zh_a_daily (Sina source), ALWAYS works even pre-market
    if spot_df is None or spot_df.empty:
        print("🔄 Trying Sina Daily Bars fallback (always available)...")
        try:
            # Get industry/growth data first to know which stocks to fetch
            growth_df = ak.stock_yjbb_em(date="20250930")
            if growth_df.empty:
                growth_df = ak.stock_yjbb_em(date="20241231")
            
            if '所处行业' not in growth_df.columns:
                print("❌ No industry data available")
                return pd.DataFrame()
            
            target_stocks = growth_df[growth_df['所处行业'].apply(
                lambda x: isinstance(x, str) and any(t in x for t in TARGET_INDUSTRIES)
            )].copy()
            
            # Shuffle to avoid always hitting same stocks on retry
            target_stocks = target_stocks.sample(frac=1).reset_index(drop=True)
            
            print(f"📊 Building pool from {len(target_stocks)} industry-matched stocks via Sina...")
            
            end_date = datetime.datetime.now().strftime("%Y%m%d")
            start_date = (datetime.datetime.now() - datetime.timedelta(days=10)).strftime("%Y%m%d")
            
            rows = []
            attempts = 0
            max_attempts = min(len(target_stocks), 500)  # Scan up to 500 stocks
            
            for _, row in target_stocks.iterrows():
                if len(rows) >= 200:
                    break
                if attempts >= max_attempts:
                    break
                attempts += 1
                
                code = str(row['股票代码']).zfill(6)
                # Sina needs sh/sz prefix
                if code.startswith('6'):
                    prefix = 'sh'
                elif code.startswith('0') or code.startswith('3'):
                    prefix = 'sz'
                elif code.startswith('8') or code.startswith('4') or code.startswith('9'):
                    prefix = 'bj'
                else:
                    continue
                
                try:
                    hist = ak.stock_zh_a_daily(symbol=f"{prefix}{code}",
                                               start_date=start_date, end_date=end_date, adjust="qfq")
                    if hist is not None and not hist.empty and len(hist) >= 2:
                        latest = hist.iloc[-1]
                        prev = hist.iloc[-2]
                        chg = ((float(latest['close']) - float(prev['close'])) / float(prev['close'])) * 100
                        rows.append({
                            '代码': code,
                            '名称': row.get('股票简称', code),
                            '最新价': float(latest['close']),
                            '涨跌幅': round(chg, 3),
                            '量比': 1.0,
                            '换手率': 0.0,
                            '市盈率-动态': 0.0,
                            '总市值': 0
                        })
                        if len(rows) % 50 == 0:
                            print(f"   ... fetched {len(rows)} stocks so far")
                except:
                    pass
                time.sleep(0.05)
            
            if rows:
                spot_df = pd.DataFrame(rows)
                source = "hist_fallback"
                print(f"✅ Sina fallback success: {len(spot_df)} stocks built")
            else:
                print("❌ Historical fallback: no data retrieved")
                return pd.DataFrame()
        except Exception as e3:
            print(f"❌ Historical fallback failed: {e3}")
            return pd.DataFrame()
    
    if spot_df is None or spot_df.empty:
        print("Error fetching A-share pool: All sources failed")
        return pd.DataFrame()
    
    try:
        col_map = {
            '代码': 'Symbol', '名称': 'Name', '最新价': 'Price', 
            '涨跌幅': 'Change_Pct', '量比': 'Volume_Ratio', 
            '换手率': 'Turnover_Rate', '市盈率-动态': 'PE_TTM',
            '总市值': 'Market_Cap'
        }
        
        print("Fetching Industry & Growth Data...")
        growth_df = ak.stock_yjbb_em(date="20250930") 
        if growth_df.empty: 
             growth_df = ak.stock_yjbb_em(date="20241231")
             
        if '所处行业' in growth_df.columns:
            growth_df = growth_df[['股票代码', '所处行业', '净利润-同比增长']]
            growth_df.columns = ['Symbol', 'Industry', 'Growth_Rate']
        else:
            return pd.DataFrame()

        spot_df = spot_df.rename(columns=col_map)
        merged = pd.merge(spot_df, growth_df, on='Symbol', how='inner')
        
        # For non-EastMoney sources: try to enrich Market Cap
        if source in ("tencent", "hist_fallback"):
            print(f"📊 Fetching Market Cap data...")
            try:
                em_spot = ak.stock_zh_a_spot_em()
                if em_spot is not None and not em_spot.empty:
                    cap_map = dict(zip(em_spot['代码'].astype(str), em_spot['总市值']))
                    merged['Market_Cap'] = merged['Symbol'].map(cap_map)
                    print(f"✅ Market Cap enriched from EastMoney")
            except Exception as e_cap:
                print(f"⚠️ Market Cap fetch failed: {e_cap}, using permissive filter")
                merged['Market_Cap'] = MIN_MARKET_CAP + 1
        
        merged['Market_Cap'] = pd.to_numeric(merged['Market_Cap'], errors='coerce')
        merged = merged[merged['Market_Cap'] >= MIN_MARKET_CAP]
        
        def is_target_industry(ind_name):
            if not isinstance(ind_name, str): return False
            return any(target in ind_name for target in TARGET_INDUSTRIES)
            
        merged = merged[merged['Industry'].apply(is_target_industry)]
        print(f"✅ Final pool: {len(merged)} stocks (source: {source})")
        return merged
    except Exception as e:
        print(f"Error processing A-share pool: {e}")
        return pd.DataFrame()


def fetch_hk_pool():
    print("Fetching HK Spot Data (Market Cap > 10B HKD)...")
    try:
        # stock_hk_spot_em iterates but is comprehensive
        raw_df = ak.stock_hk_spot_em()
        
        # Expected columns: 序号, 代码, 名称, 最新价, 涨跌额, 涨跌幅, ..., 总市值, ...
        # Standardize
        df = raw_df.rename(columns={
            '代码': 'Symbol', '名称': 'Name', '最新价': 'Price',
            '涨跌幅': 'Change_Pct', '总市值': 'Market_Cap'
        })
        
        # Clean numeric
        df['Market_Cap'] = pd.to_numeric(df['Market_Cap'], errors='coerce')
        df['Price'] = pd.to_numeric(df['Price'], errors='coerce')
        df['Change_Pct'] = pd.to_numeric(df['Change_Pct'], errors='coerce')
        
        # Add placeholder Industry (since spot_em doesn't provide it easily)
        df['Industry'] = "-"
        
        # Filter: Market Cap > 10 Billion HKD
        # Note: If Market_Cap unit varies, this might need adjustment. 
        # Usually akshare returns raw float.
        min_cap = 100 * 10000 * 10000 # 100亿
        
        filtered_df = df[df['Market_Cap'] > min_cap].copy()
        print(f"HK Pool: Filtered {len(df)} -> {len(filtered_df)} (Cap > 10B)")
        
        return filtered_df
    except Exception as e:
        print(f"Error fetching HK pool: {e}")
        # Fallback to Hardcoded Blue Chips if API fails
        print("⚠️ Using Hardcoded HK Blue Chip Pool...")
        data = [
            {'Symbol': '00700', 'Name': '腾讯控股', 'Price': 300, 'Change_Pct': 1.0, 'Market_Cap': 3000000000000, 'Industry': '互联网'},
            {'Symbol': '09988', 'Name': '阿里巴巴', 'Price': 80, 'Change_Pct': 0.5, 'Market_Cap': 1500000000000, 'Industry': '互联网'},
            {'Symbol': '03690', 'Name': '美团', 'Price': 90, 'Change_Pct': -1.2, 'Market_Cap': 500000000000, 'Industry': '互联网'},
            {'Symbol': '01810', 'Name': '小米集团', 'Price': 15, 'Change_Pct': 2.3, 'Market_Cap': 400000000000, 'Industry': '电子'},
            {'Symbol': '00981', 'Name': '中芯国际', 'Price': 20, 'Change_Pct': 1.5, 'Market_Cap': 200000000000, 'Industry': '半导体'},
            {'Symbol': '00941', 'Name': '中国移动', 'Price': 65, 'Change_Pct': 0.0, 'Market_Cap': 1200000000000, 'Industry': '电信'},
            {'Symbol': '00005', 'Name': '汇丰控股', 'Price': 60, 'Change_Pct': 0.2, 'Market_Cap': 1000000000000, 'Industry': '银行'},
            {'Symbol': '01211', 'Name': '比亚迪股份', 'Price': 200, 'Change_Pct': 1.8, 'Market_Cap': 600000000000, 'Industry': '汽车'},
            {'Symbol': '02020', 'Name': '安踏体育', 'Price': 80, 'Change_Pct': -0.5, 'Market_Cap': 200000000000, 'Industry': '消费'},
            {'Symbol': '00883', 'Name': '中国海洋石油', 'Price': 18, 'Change_Pct': 1.1, 'Market_Cap': 800000000000, 'Industry': '能源'},
        ]
        return pd.DataFrame(data)


def fetch_index_data(symbol="sh000300", days=60):
    print(f"Fetching Index Data ({symbol})...")
    try:
         df = ak.stock_zh_index_daily(symbol=symbol)
         df = df.sort_values(by="date").tail(days)
         df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
         df['close'] = pd.to_numeric(df['close'])
         df['Index_Change'] = df['close'].pct_change() * 100
         return df[['date', 'close', 'Index_Change']].reset_index(drop=True)
    except Exception as e:
        print(f"Error fetching index: {e}")
        return pd.DataFrame()


@retry(times=3, initial_delay=2)
def fetch_stock_history_cn(symbol, days=60):
    end_date = datetime.datetime.now().strftime("%Y%m%d")
    start_date = (datetime.datetime.now() - datetime.timedelta(days=days*2)).strftime("%Y%m%d")
    
    if symbol.startswith('6'): prefix = 'sh'
    elif symbol.startswith('0') or symbol.startswith('3'): prefix = 'sz'
    elif symbol.startswith('8') or symbol.startswith('4'): prefix = 'bj'
    else: prefix = ''
    
    full_symbol = f"{prefix}{symbol}"
    
    try:
        df = ak.stock_zh_a_daily(symbol=full_symbol, start_date=start_date, end_date=end_date)
        if df.empty: return None
        
        df = df.sort_values('date')
        df['change_pct'] = df['close'].pct_change() * 100
        df['change_pct'] = df['change_pct'].fillna(0)
        df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
        # v5.1 Fix: Return full OHLC for advanced technicals (ATR/Safety Margin)
        return df[['date', 'open', 'high', 'low', 'close', 'volume', 'change_pct']]
        
    except Exception as e:
        raise e


@retry(times=3, initial_delay=2)
def fetch_stock_history_hk(symbol, days=60):
    # AKShare stock_hk_daily: symbol="00700", adjust="qfq"
    # Returns: date, open, high, low, close, volume...
    try:
        # Note: akshare might handle HK symbols as "00700" directly.
        df = ak.stock_hk_daily(symbol=symbol, adjust="qfq")
        if df.empty: return None
        
        # Filter last N days (API returns full history usually)
        df = df.sort_values('date').tail(days)
        
        df['change_pct'] = df['close'].pct_change() * 100
        df['change_pct'] = df['change_pct'].fillna(0)
        df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
        return df[['date', 'open', 'high', 'low', 'close', 'volume', 'change_pct']]
        
    except Exception as e:
        # print(f"HK History Error {symbol}: {e}") # Reduce noise
        return None

# --- Analysis Logic ---

def calculate_antigravity_score(stock_hist, index_hist):
    """v3.5: Enhanced scoring with consecutive resilience bonus"""
    merged = pd.merge(stock_hist, index_hist, on='date', how='inner')
    if merged.empty: return 0.0, []
    
    recent_days = merged.tail(10)
    down_days = recent_days[recent_days['Index_Change'] < -0.3]  # v3.5: Relaxed from -0.5
    
    score = 0.0
    details = []
    consecutive_resilience = 0
    
    for _, row in down_days.iterrows():
        idx_chg = row['Index_Change']
        stk_chg = row['change_pct']
        
        if stk_chg > 0:
            score += 2.0
            consecutive_resilience += 1
            details.append(f"{row['date']}:逆势(Idx{idx_chg:.2f}%)")
        elif stk_chg > (idx_chg + 1.5):  # v3.5: Relaxed from +2.0
            score += 1.0
            consecutive_resilience += 1
            details.append(f"{row['date']}:抗跌(Idx{idx_chg:.2f}%)")
        else:
            consecutive_resilience = 0  # Reset if not resilient
    
    # v3.5: Consecutive Resilience Bonus
    if consecutive_resilience >= 2:
        score += 1.0
        details.append("连续抗跌")
            
    return score, details

def calculate_beta(stock_hist, index_hist, days=5):
    # Calculate Beta of Stock vs Index over last N days
    merged = pd.merge(stock_hist, index_hist, on='date', how='inner')
    if len(merged) < days: return 1.0 # Default to high correlation if no data
    
    recent = merged.tail(days)
    if recent.empty: return 1.0
    
    # Simple correlation proxy for Beta efficiency
    correlation = recent['change_pct'].corr(recent['Index_Change'])
    return correlation if not pd.isna(correlation) else 1.0

def analyze_structure_v2(stock_hist):
    if len(stock_hist) < 20: return False, 0
    
    closes = stock_hist['close']
    ma10 = closes.rolling(10).mean().iloc[-1]
    ma20 = closes.rolling(20).mean().iloc[-1]
    price = closes.iloc[-1]
    
    # 1. Price > MA10 (Strong Trend)
    # 2. Bias (Price-MA20)/MA20 in [5%, 15%] (Refusal to pullback deep, but not overheated)
    bias = (price - ma20) / ma20
    
    structure_ok = (price > ma10) and (0.05 <= bias <= 0.15)
    return structure_ok, bias

def analyze_volume_anomaly(stock_hist):
    if len(stock_hist) < 5: return False, "None"
    
    today = stock_hist.iloc[-1]
    yesterday = stock_hist.iloc[-2]
    ma5_vol = stock_hist['volume'].rolling(5).mean().iloc[-1]
    
    is_red = today['change_pct'] > 0
    vol_shrink = today['volume'] < yesterday['volume']
    vol_explode = today['volume'] > 1.5 * ma5_vol
    
    if is_red and vol_shrink:
        return True, "Lock-up"
    if is_red and vol_explode:
        return True, "Explosion"
        
    return False, "None"

# --- v5.0 Enhanced Analysis ---

def calc_relative_strength(stock_hist, index_hist):
    """v6.0: Short-term relative strength (3/5/10 day alpha).
    Weighted: 3d=40%, 5d=35%, 10d=25%. Shorter windows for momentum capture.
    """
    merged = pd.merge(stock_hist, index_hist, on='date', how='inner', suffixes=('', '_idx'))
    if len(merged) < 11:
        return 0.0, False

    closes = merged['close']
    idx_closes = merged['close_idx']

    stock_3d = (closes.iloc[-1] / closes.iloc[-4] - 1) * 100 if len(closes) > 3 else 0
    stock_5d = (closes.iloc[-1] / closes.iloc[-6] - 1) * 100 if len(closes) > 5 else 0
    stock_10d = (closes.iloc[-1] / closes.iloc[-11] - 1) * 100 if len(closes) > 10 else 0

    idx_3d = (idx_closes.iloc[-1] / idx_closes.iloc[-4] - 1) * 100 if len(idx_closes) > 3 else 0
    idx_5d = (idx_closes.iloc[-1] / idx_closes.iloc[-6] - 1) * 100 if len(idx_closes) > 5 else 0
    idx_10d = (idx_closes.iloc[-1] / idx_closes.iloc[-11] - 1) * 100 if len(idx_closes) > 10 else 0

    alpha_3d = stock_3d - idx_3d
    alpha_5d = stock_5d - idx_5d
    alpha_10d = stock_10d - idx_10d

    # Acceleration: short > mid > long and all positive
    is_accelerating = alpha_3d > alpha_5d > alpha_10d > 0

    # v6.0: Weighted RS (shorter windows weighted more)
    rs = alpha_3d * 0.4 + alpha_5d * 0.35 + alpha_10d * 0.25
    return round(rs, 2), is_accelerating

def detect_institutional_flow(stock_hist, lookback=10):
    """v5.0: Detect institutional accumulation patterns."""
    if len(stock_hist) < lookback:
        return {'flow_ratio': 1.0, 'rising_floor': False, 'vol_divergence': False, 'score': 0}
    
    recent = stock_hist.tail(lookback)
    
    # Feature 1: Up-volume vs Down-volume ratio
    up_days = recent[recent['change_pct'] > 0]
    dn_days = recent[recent['change_pct'] <= 0]
    avg_up_vol = up_days['volume'].mean() if not up_days.empty else 0
    avg_dn_vol = dn_days['volume'].mean() if not dn_days.empty else 1
    flow_ratio = avg_up_vol / max(avg_dn_vol, 1)
    
    # Feature 2: Rising floor (lows trending up)
    lows_3d = recent['close'].rolling(3).min()
    rising_floor = False
    if len(lows_3d.dropna()) >= 7:
        rising_floor = (lows_3d.iloc[-1] > lows_3d.iloc[-4]) and (lows_3d.iloc[-4] > lows_3d.iloc[-7])
    
    # Feature 3: Volume-price divergence (price flat, volume declining = selling exhaustion)
    price_flat = abs(recent['close'].iloc[-1] / recent['close'].iloc[0] - 1) < 0.03
    vol_early = recent['volume'].iloc[:3].mean()
    vol_late = recent['volume'].iloc[-3:].mean()
    vol_divergence = price_flat and (vol_late < vol_early * 0.7) if vol_early > 0 else False
    
    # Composite flow score (0-5)
    fscore = 0
    if flow_ratio > 1.5: fscore += 2
    elif flow_ratio > 1.2: fscore += 1
    if rising_floor: fscore += 2
    if vol_divergence: fscore += 1
    
    return {
        'flow_ratio': round(flow_ratio, 2),
        'rising_floor': rising_floor,
        'vol_divergence': vol_divergence,
        'score': fscore
    }

def calc_safety_margin(stock_hist):
    """v5.1: ATR-based dynamic safety margin grading using High/Low (True Range)."""
    if len(stock_hist) < 15:
        return 'C', 99.0  # Not enough data = conservative
    
    # Check if High/Low exist (legacy cache might not have them)
    if 'high' not in stock_hist.columns or 'low' not in stock_hist.columns:
        # Fallback to Close-based simplified ATR
        daily_range = stock_hist['close'].diff().abs()
    else:
        # True Range Calculation
        high = stock_hist['high']
        low = stock_hist['low']
        close_prev = stock_hist['close'].shift(1)
        
        tr1 = high - low
        tr2 = (high - close_prev).abs()
        tr3 = (low - close_prev).abs()
        
        daily_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr14 = daily_range.rolling(14).mean().iloc[-1]
    
    current_price = stock_hist['close'].iloc[-1]
    if current_price <= 0:
        return 'D', 99.0
    
    atr_pct = (atr14 / current_price) * 100
    
    if atr_pct < 2.0:   return 'A', round(atr_pct, 2)  # Low volatility = high safety
    elif atr_pct < 4.0: return 'B', round(atr_pct, 2)  # Medium
    elif atr_pct < 6.0: return 'C', round(atr_pct, 2)  # High
    else:               return 'D', round(atr_pct, 2)  # Dangerous

def calc_volume_explosion(stock_hist):
    """v6.0: Volume explosion scoring (0-20).
    Measures today's volume vs 5-day average.
    Core signal for short-term momentum ignition.
    """
    if len(stock_hist) < 6:
        return 0.0, 1.0

    today_vol = stock_hist['volume'].iloc[-1]
    ma5_vol = stock_hist['volume'].iloc[-6:-1].mean()

    if ma5_vol <= 0:
        return 0.0, 1.0

    vol_ratio = today_vol / ma5_vol

    # Scoring: higher ratio = higher score
    if vol_ratio >= 4.0:
        score = 20.0   # Extreme explosion
    elif vol_ratio >= 3.0:
        score = 16.0
    elif vol_ratio >= 2.0:
        score = 12.0
    elif vol_ratio >= 1.5:
        score = 8.0
    elif vol_ratio >= 1.2:
        score = 4.0
    else:
        score = 0.0

    # Bonus: volume explosion on a green candle is stronger
    if stock_hist['change_pct'].iloc[-1] > 0 and vol_ratio >= 2.0:
        score = min(score + 2.0, 20.0)

    return score, round(vol_ratio, 2)

def calc_momentum_acceleration(stock_hist, index_hist):
    """v6.0: Momentum acceleration scoring (0-15).
    Detects daily alpha increasing pattern:
    today's alpha > yesterday's > day before.
    Accelerating stocks have highest short-term burst probability.
    """
    merged = pd.merge(stock_hist, index_hist, on='date', how='inner', suffixes=('', '_idx'))
    if len(merged) < 6:
        return 0.0, False

    # Calculate daily alpha (stock return - index return)
    merged['daily_alpha'] = merged['change_pct'] - merged['Index_Change']
    recent = merged.tail(5)
    alphas = recent['daily_alpha'].values

    score = 0.0

    # Pattern 1: Consecutive alpha increase (last 3 days)
    if len(alphas) >= 3:
        a1, a2, a3 = alphas[-3], alphas[-2], alphas[-1]
        if a3 > a2 > a1:
            score += 8.0  # Strong acceleration
        elif a3 > a2 and a3 > 0:
            score += 5.0  # Moderate acceleration
        elif a3 > 0:
            score += 2.0  # At least positive alpha today

    # Pattern 2: 3-day cumulative alpha positive and growing
    if len(alphas) >= 5:
        alpha_3d = alphas[-3:].sum()
        alpha_5d = alphas.sum()
        if alpha_3d > 0 and alpha_3d > alpha_5d * 0.7:
            score += 4.0  # Recent alpha concentrated in last 3 days

    # Pattern 3: Today's alpha is the strongest in 5 days
    if alphas[-1] == max(alphas) and alphas[-1] > 1.0:
        score += 3.0

    is_accelerating = score >= 8.0
    return min(score, 15.0), is_accelerating

def calc_sector_momentum(pool_df, industry_col='Industry'):
    """v6.0: Sector momentum with per-stock ranking within sector.
    Returns hot_sectors list AND a dict mapping industry -> stock rankings.
    """
    try:
        sector_stats = pool_df.groupby(industry_col).agg(
            avg_change=('Change_Pct', lambda x: pd.to_numeric(x, errors='coerce').mean()),
            count=('Symbol', 'count')
        ).reset_index()

        sector_stats = sector_stats[sector_stats['count'] >= 3]
        if sector_stats.empty:
            return [], sector_stats, {}

        sector_stats['momentum_rank'] = sector_stats['avg_change'].rank(pct=True)
        hot_sectors = sector_stats[sector_stats['momentum_rank'] > 0.4][industry_col].tolist()

        # v6.0: Build per-sector stock ranking
        sector_rankings = {}
        for industry in hot_sectors:
            sector_stocks = pool_df[pool_df[industry_col] == industry].copy()
            sector_stocks['Change_Pct_num'] = pd.to_numeric(sector_stocks['Change_Pct'], errors='coerce')
            sector_stocks['rank_in_sector'] = sector_stocks['Change_Pct_num'].rank(pct=True)
            for _, srow in sector_stocks.iterrows():
                sector_rankings[str(srow['Symbol']).zfill(6)] = srow['rank_in_sector']

        return hot_sectors, sector_stats, sector_rankings
    except Exception as e:
        print(f"⚠️ Sector momentum calc error: {e}")
        return [], pd.DataFrame(), {}

def calc_sector_leader_score(symbol, is_hot_sector, sector_rankings):
    """v6.0: Sector leader scoring (0-10).
    Rewards stocks that lead their hot sector.
    """
    if not is_hot_sector:
        return 0.0

    rank_pct = sector_rankings.get(symbol, 0.5)

    if rank_pct >= 0.9:
        return 10.0  # Top 10% in hot sector
    elif rank_pct >= 0.7:
        return 7.0   # Top 30%
    elif rank_pct >= 0.5:
        return 4.0   # Above median
    else:
        return 2.0   # In hot sector but not leading

def calc_composite_score(ag_score, rs_score, flow_info, is_hot_sector,
                         vcp_signal, vol_explosion_score, momentum_accel_score,
                         sector_leader_score):
    """v6.0: Aggressive momentum composite scoring (0-100).

    Weight allocation:
    1. Relative Strength Alpha   — 30pts (core)
    2. Volume Explosion          — 20pts (ignition signal)
    3. Institutional Flow        — 20pts (smart money)
    4. Momentum Acceleration     — 15pts (burst probability)
    5. Sector Leader             — 10pts (leading hot sector)
    6. Antigravity (resilience)  —  5pts (minor reference)
    """
    score = 0.0

    # 1. Relative Strength (0-30): multi-timeframe outperformance
    score += max(min(rs_score * 3.0, 30.0), 0.0)

    # 2. Volume Explosion (0-20): today's volume vs 5d avg
    score += min(vol_explosion_score, 20.0)

    # 3. Institutional Flow (0-20): accumulation patterns
    score += flow_info['score'] * 4.0  # max 5 * 4 = 20

    # 4. Momentum Acceleration (0-15): daily alpha increasing
    score += min(momentum_accel_score, 15.0)

    # 5. Sector Leader (0-10): rank within hot sector
    score += min(sector_leader_score, 10.0)

    # 6. Antigravity (0-5): minor resilience reference
    score += min(ag_score * 0.5, 5.0)

    # Bonus: VCP pattern still gets a small nudge (not scored independently)
    if vcp_signal:
        score += 2.0

    return round(min(score, 100.0), 1)


def fetch_hk_index_data(symbol="HSI", days=60):
    print(f"Fetching HK Index Data ({symbol})...")
    try:
         # HSI for Hang Seng Index
         df = ak.stock_hk_index_daily_sina(symbol=symbol)
         df = df.sort_values(by="date").tail(days)
         df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
         df['close'] = pd.to_numeric(df['close'])
         df['Index_Change'] = df['close'].pct_change() * 100
         return df[['date', 'close', 'Index_Change']].reset_index(drop=True)
    except Exception as e:
        print(f"Error fetching HK index: {e}")
        return pd.DataFrame()

# --- Filtering Sub-functions ---

def _filter_fundamentals(row, market, cfg=CONFIG):
    """Check fundamental filters. Returns (pass, change_pct)."""
    try:
        change_pct = float(row['Change_Pct'])
    except (ValueError, TypeError):
        change_pct = 0.0

    if change_pct < cfg.max_drop_pct:
        return False, change_pct

    industry = str(row['Industry'])
    if '光伏' in industry and change_pct <= 0:
        return False, change_pct

    if market == 'CN':
        pe_ttm = pd.to_numeric(row.get('PE_TTM', 0), errors='coerce')
        growth = pd.to_numeric(row.get('Growth_Rate', 0), errors='coerce')
        if pd.isna(growth): return False, change_pct
        if pd.isna(pe_ttm): pe_ttm = 0
        peg = pe_ttm / growth if growth > 0 else 999
        fund_ok = (growth > cfg.high_growth) or (peg < cfg.max_peg and growth > cfg.min_growth)
        if not fund_ok: return False, change_pct

    return True, change_pct

def _filter_technicals(hist, change_pct, realtime_change_pct, cfg=CONFIG):
    """Apply technical filters. Returns (pass, rsi, stock_3d, vcp_signal)."""
    current_price = hist.iloc[-1]['close']

    # Anti-FOMO: 5-day cumulative gain
    if len(hist) > 5:
        close_5d_ago = hist.iloc[-6]['close']
        gain_5d = (current_price - close_5d_ago) / close_5d_ago * 100
        if gain_5d > cfg.max_gain_5d: return False, 0, 0, False

    # RSI filter
    delta = hist['close'].diff()
    u = delta.where(delta > 0, 0)
    d = -delta.where(delta < 0, 0)
    rs = u.rolling(14).mean() / d.rolling(14).mean()
    rsi = 100 - (100 / (1 + rs)).iloc[-1]
    if not pd.isna(rsi) and rsi > cfg.max_rsi: return False, rsi, 0, False

    # Limit-up filter
    if realtime_change_pct > cfg.limit_up_threshold:
        return False, rsi, 0, False

    # 3-day stock change
    stock_3d = 0.0
    if len(hist) > 3:
        stock_3d = (current_price - hist.iloc[-4]['close']) / hist.iloc[-4]['close'] * 100

    # MA trend filter
    if len(hist) >= cfg.ma_period:
        ma = hist['close'].rolling(cfg.ma_period).mean().iloc[-1]
        if current_price < ma: return False, rsi, stock_3d, False

    # Liquidity gate
    avg_volume_20 = hist['volume'].tail(20).mean()
    if pd.notna(avg_volume_20) and avg_volume_20 < cfg.min_avg_volume:
        return False, rsi, stock_3d, False

    # Wild swing filter
    if abs(stock_3d) > cfg.max_swing_3d: return False, rsi, stock_3d, False

    # VCP detection
    ma5_vol = hist['volume'].tail(5).mean()
    recent_drops = hist.tail(3)[hist.tail(3)['change_pct'] < 0]
    vcp_signal = False
    if not recent_drops.empty:
        for _, d_row in recent_drops.iterrows():
            if d_row['volume'] < cfg.vcp_vol_ratio * ma5_vol:
                vcp_signal = True
                break
    else:
        if hist.iloc[-1]['volume'] < cfg.vcp_steady_ratio * ma5_vol:
            vcp_signal = True

    return True, rsi, stock_3d, vcp_signal

def _save_and_report(results, csv_path, last_trading_date):
    """Save results to CSV, track in Boomerang, call Commander."""
    if not results:
        print("No stocks matched v3.0 criteria.")
        return

    final_df = pd.DataFrame(results)
    final_df = final_df.sort_values(by=['AG_Score'], ascending=False)

    # Save CSV (Append/Merge mode)
    if os.path.exists(csv_path):
        try:
            existing_df = pd.read_csv(csv_path)
            combined_df = pd.concat([existing_df, final_df], ignore_index=True)
            combined_df = combined_df.drop_duplicates(subset=['Symbol'], keep='last')
            combined_df = combined_df.sort_values(by=['AG_Score'], ascending=False)
            final_df = combined_df
        except Exception as e:
            print(f"Error merging CSV: {e}")

    final_df.to_csv(csv_path, index=False)
    print(f"Results saved to {csv_path} (Count: {len(final_df)})")

    # Project Boomerang: track top 3
    try:
        import boomerang_tracker as bt
        print("\n📊 Boomerang Tracking...")
        for i, row in final_df.head(3).iterrows():
            bt.add_recommendation(
                stock_code=row['Symbol'],
                stock_name=row['Name'],
                rec_price=row['Price'],
                strategy_tag=row['AG_Details'],
                siphon_score=row['AG_Score'],
                custom_date=last_trading_date,
                industry=row['Industry']
            )
    except Exception as e:
        print(f"⚠️ Boomerang tracking skipped: {e}")

# --- Runner ---

def run_siphoner_strategy(market='CN', cfg=CONFIG):
    print(f"=== Starting 'Siphon Strategy v6.0 — Aggressive Momentum' (Market: {market}) ===")
    
    if market == 'CN':
        pool = fetch_basic_pool()
        index_df = fetch_index_data()
    else:
        pool = fetch_hk_pool()
        index_df = fetch_hk_index_data()

    if pool.empty:
        print("❌ FATAL: No stock pool data. Cannot generate recommendations.")
        import sys; sys.exit(1)
    print(f"Candidates In Pool: {len(pool)}")
    
    if index_df.empty:
        print("❌ FATAL: No index data. Cannot generate recommendations.")
        import sys; sys.exit(1)

    last_trading_date = index_df['date'].iloc[-1]
    print(f"📅 Effective Analysis Date: {last_trading_date}")

    # v6.0: Sector momentum pre-filter with per-stock rankings
    hot_sectors, sector_stats, sector_rankings = calc_sector_momentum(pool)
    if hot_sectors:
        print(f"🔥 Hot Sectors ({len(hot_sectors)}): {', '.join(hot_sectors[:8])}")
    else:
        print("⚠️ No hot sectors found, skipping sector filter")
        
    results = []
    processed_count = 0
    
    pool = pool.sample(frac=1).reset_index(drop=True)
    
    for idx, row in pool.iterrows():
        if processed_count >= cfg.max_process: break
        processed_count += 1
        
        symbol = str(row['Symbol']).zfill(6)
        name = row['Name']
        industry = row['Industry']
        
        # Step 1: Fundamental filtering
        fund_ok, change_pct = _filter_fundamentals(row, market, cfg)
        if not fund_ok: continue

        # v5.0: Sector momentum filter (soft — skip only if sectors available)
        is_hot_sector = True
        if hot_sectors:
            is_hot_sector = industry in hot_sectors
            # Allow through if AG score is very high (handled later)
            
        time.sleep(0.5)
        
        try:
            if market == 'CN':
                hist = fetch_stock_history_cn(symbol)
            else:
                hist = fetch_stock_history_hk(symbol)
        except Exception as e:
            print(f"Skip {name}: History fetch error: {e}")
            continue
        if hist is None: continue
        
        realtime_change_pct = change_pct
        # Use real-time spot price from pool when available (more accurate during market hours)
        spot_price = pd.to_numeric(row.get('Price', 0), errors='coerce')
        hist_close = hist.iloc[-1]['close']
        current_price = spot_price if (pd.notna(spot_price) and spot_price > 0) else hist_close
        change_pct = hist.iloc[-1]['change_pct']
        
        # Step 2: Technical filtering
        tech_ok, rsi, stock_3d, vcp_signal = _filter_technicals(hist, change_pct, realtime_change_pct, cfg)
        if not tech_ok: continue

        # Limit-up check
        if realtime_change_pct > cfg.limit_up_threshold:
            print(f"Skip {name}: Daily Limit Up/Surge (+{realtime_change_pct:.2f}%)")
            continue

        # Step 3: v6.0 Enhanced Scoring
        ag_score, ag_details = calculate_antigravity_score(hist, index_df)
        if ag_score < cfg.min_ag_score:
            continue

        # v6.0: Relative Strength
        rs_score, is_accelerating = calc_relative_strength(hist, index_df)

        # v6.0: Institutional Flow
        flow_info = detect_institutional_flow(hist)

        # v6.0: Volume Explosion
        vol_explosion_score, vol_ratio = calc_volume_explosion(hist)

        # v6.0: Momentum Acceleration
        momentum_accel_score, _ = calc_momentum_acceleration(hist, index_df)

        # v6.0: Sector Leader Score
        sector_leader_score = calc_sector_leader_score(symbol, is_hot_sector, sector_rankings)

        # v6.0: Composite Score (0-100) with aggressive momentum weights
        composite = calc_composite_score(
            ag_score, rs_score, flow_info, is_hot_sector,
            vcp_signal, vol_explosion_score, momentum_accel_score,
            sector_leader_score
        )
        
        if composite < cfg.min_composite_score:
            continue
        
        # Build signal tags
        signal_tags = []
        if vol_explosion_score >= 12: signal_tags.append(f"爆量{vol_ratio:.1f}x")
        if momentum_accel_score >= 8.0: signal_tags.append("加速🚀")
        if is_accelerating: signal_tags.append("RS加速")
        if flow_info['rising_floor']: signal_tags.append("底升")
        if flow_info['flow_ratio'] > 1.5: signal_tags.append("吸筹")
        if vcp_signal: signal_tags.append("VCP")
        if sector_leader_score >= 7: signal_tags.append("领涨")
        if rsi < 50: signal_tags.append("LowRSI")
        signal_str = " ".join(signal_tags) if signal_tags else "Momentum"

        vol_note = f"VolR:{vol_ratio:.1f}x Flow:{flow_info['flow_ratio']:.1f}"

        symbol_str = str(symbol).zfill(6)

        results.append({
            'Symbol': symbol_str,
            'Name': name,
            'Industry': industry,
            'Price': float(current_price),
            'Change_Pct': change_pct,
            'AG_Score': composite,
            'AG_Details': signal_str,
            'Volume_Note': vol_note,
            'RS_Score': rs_score,
            'Vol_Explosion': vol_explosion_score,
            'Momentum_Accel': momentum_accel_score,
            'Sector_Leader': sector_leader_score,
            'Flow_Ratio': flow_info['flow_ratio'],
            'Composite': composite
        })
        print(f"MATCH {name}: C={composite} RS={rs_score:.1f} Vol={vol_explosion_score:.0f} Accel={momentum_accel_score:.0f} Flow={flow_info['flow_ratio']:.1f} Sector={sector_leader_score:.0f}")
    
    # Step 4: Save and report
    _save_and_report(results, "siphon_strategy_results.csv", last_trading_date)

if __name__ == "__main__":
    run_siphoner_strategy()
