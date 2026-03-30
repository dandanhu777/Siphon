
import akshare as ak
import pandas as pd
import time
import datetime
import os
import functools
import warnings
import pickle
import random
import logging

# --- v11.0: Unified logging configuration ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger("SiphonSystem")


# --- Global Configuration & Patching ---
import requests_patch

# --- v12.0: Advanced modules (from loop-win-2026) ---
from deep_factors import DeepFactorEngine
from regime_sensor import RegimeSensor
from vwap_calc import VWAPCalc
from crowd_detector import CrowdingDetector
from strategy_reversal import ReversalScanner
from scoring_engine import calc_enhanced_composite, get_enhanced_confidence_grade

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

# --- v10.2: Market Holiday Check ---
def is_trading_day():
    """Check if today is a trading day in A-share market."""
    try:
        # Get trading dates from Sina (includes past and future)
        df_dates = ak.tool_trade_date_hist_sina()
        if df_dates.empty:
            return True # Fallback to continue if API fails
        
        # Current date in Beijing Time (approximate for GHA which is UTC)
        # GHA runs at 01:50 UTC (09:50 BEI) and 06:35 UTC (14:35 BEI)
        # In both cases, UTC date is the same as BEI date.
        today = datetime.date.today()
        
        # Check if today is in the trading calendar
        is_trade = today in df_dates['trade_date'].values
        return is_trade
    except Exception as e:
        print(f"⚠️ Holiday check error: {e}. Defaulting to TRADING DAY.")
        return True

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


def get_industry_data_robustly():
    """Robustly fetch industry and growth data with disk caching + retries."""
    CACHE_TTL_HOURS = 12

    for date_str in ["20250930", "20241231", "20250630"]:
        # --- Check disk cache first ---
        cache_path = os.path.join(CACHE_DIR, f"industry_data_{date_str}.pkl")
        if os.path.exists(cache_path):
            try:
                age_hours = (time.time() - os.path.getmtime(cache_path)) / 3600
                if age_hours < CACHE_TTL_HOURS:
                    df = pd.read_pickle(cache_path)
                    if df is not None and not df.empty:
                        print(f"   ✅ Using cached industry data ({date_str}, age={age_hours:.1f}h)")
                        return df
            except Exception:
                pass  # corrupt cache, re-fetch

        # --- Fetch with aggressive retry ---
        MAX_ATTEMPTS = 5
        BASE_DELAY = 5
        for attempt in range(MAX_ATTEMPTS):
            try:
                df = ak.stock_yjbb_em(date=date_str)
                if df is not None and not df.empty:
                    # Cache to disk on success
                    try:
                        df.to_pickle(cache_path)
                        print(f"   💾 Cached industry data ({date_str})")
                    except Exception:
                        pass
                    return df
            except Exception as e:
                sleep_time = BASE_DELAY * (2 ** attempt) + random.random() * 3
                print(f"   ⚠️ stock_yjbb_em({date_str}) attempt {attempt+1}/{MAX_ATTEMPTS} failed: {e}")
                if attempt < MAX_ATTEMPTS - 1:
                    print(f"      Retrying in {sleep_time:.0f}s...")
                    time.sleep(sleep_time)
        # Pause before trying the next date
        time.sleep(3)

    return pd.DataFrame()


def fetch_hot_industries_dynamic(top_n=5):
    """v11.0: Dynamically detect today's hottest industry sectors.

    Scans real-time industry board performance and returns the top N
    gaining industries as a bonus pool to supplement TARGET_INDUSTRIES.
    """
    try:
        df = ak.stock_board_industry_name_em()
        if df is None or df.empty:
            return []

        # Find change/gain column
        change_col = None
        for col in df.columns:
            if '涨跌' in str(col) and '幅' in str(col):
                change_col = col
                break
        if change_col is None:
            # Fallback: try numeric columns
            for col in df.columns:
                if df[col].dtype in ['float64', 'int64'] and col != '序号':
                    change_col = col
                    break

        if change_col is None:
            return []

        name_col = None
        for col in df.columns:
            if '板块' in str(col) or '名称' in str(col):
                name_col = col
                break
        if name_col is None:
            name_col = df.columns[1]  # fallback

        df[change_col] = pd.to_numeric(df[change_col], errors='coerce')
        top_industries = df.nlargest(top_n, change_col)[name_col].tolist()

        # Filter out already-included target industries
        bonus = [ind for ind in top_industries if ind not in TARGET_INDUSTRIES]
        return bonus
    except Exception as e:
        print(f"  ⚠️ 动态行业检测失败: {e}")
        return []


def fetch_target_industry_pool(include_dynamic=True):
    """v11.0: Fetch stocks from TARGET_INDUSTRIES (base) + dynamic hot industries (bonus).
    Returns a DataFrame with columns ['Symbol', 'Name', 'Industry'].
    Reliable: ~11+ requests total instead of 5000."""
    pool_dfs = []

    # v11.0: Merge base + dynamic hot industries
    all_industries = list(TARGET_INDUSTRIES)
    dynamic_industries = []
    if include_dynamic:
        dynamic_industries = fetch_hot_industries_dynamic(top_n=5)
        if dynamic_industries:
            all_industries.extend(dynamic_industries)
            print(f"🔥 动态热门行业 (bonus pool): {', '.join(dynamic_industries)}")

    print(f"🔍 Fetching component stocks for {len(all_industries)} industries (base {len(TARGET_INDUSTRIES)} + bonus {len(dynamic_industries)})...")

    for industry in all_industries:
        try:
            df = ak.stock_board_industry_cons_em(symbol=industry)
            if df is not None and not df.empty:
                df = df[['代码', '名称']].copy()
                df.columns = ['Symbol', 'Name']
                df['Symbol'] = df['Symbol'].astype(str).str.zfill(6)
                df['Industry'] = industry
                pool_dfs.append(df)
                tag = "🌟" if industry in dynamic_industries else "✅"
                print(f"   {tag} {industry}: {len(df)} stocks")
            else:
                print(f"   ⚠️ {industry}: No stocks found via EM")
        except Exception as e:
            print(f"   ❌ Error fetching {industry}: {e}")
        time.sleep(1.0)

    if not pool_dfs:
        return pd.DataFrame()

    full_pool = pd.concat(pool_dfs, ignore_index=True)
    full_pool = full_pool.drop_duplicates(subset=['Symbol'])
    print(f"📊 Total industry pool: {len(full_pool)} stocks")
    return full_pool


def fetch_industry_per_stock(symbols):
    """v10.1.2: Fetch industry for a list of stock codes using stock_individual_info_em.
    Returns a dict {code: industry}. Only used as ultimate fallback.
    Optimized for small batches (~500 stocks)."""
    CACHE_PATH = os.path.join(CACHE_DIR, "industry_map_cache.pkl")
    CACHE_TTL_HOURS = 24

    # Load existing cache
    industry_map = {}
    if os.path.exists(CACHE_PATH):
        try:
            age_hours = (time.time() - os.path.getmtime(CACHE_PATH)) / 3600
            if age_hours < CACHE_TTL_HOURS:
                industry_map = pd.read_pickle(CACHE_PATH)
        except Exception as e:
            print(f"  Cache load warning: {e}")

    # Fetch missing symbols
    missing = [s for s in symbols if s not in industry_map]
    if not missing:
        return industry_map

    print(f"   📋 Fetching industry for {len(missing)} stocks (Sequential)...")
    fetched = 0
    for code in missing:
        try:
            info = ak.stock_individual_info_em(symbol=code)
            row = dict(zip(info['item'], info['value']))
            industry_map[code] = row.get('行业', 'Unknown')
            fetched += 1
            if fetched % 50 == 0:
                print(f"   ... progress {fetched}/{len(missing)}")
        except Exception:
            industry_map[code] = 'Unknown'
        time.sleep(0.05) 

    # Save updated cache
    try:
        if not os.path.exists(CACHE_DIR): os.makedirs(CACHE_DIR)
        pd.to_pickle(industry_map, CACHE_PATH)
    except Exception as e:
        print(f"  Cache save warning: {e}")

    return industry_map


# --- Data Fetching ---


def fetch_basic_pool():
    print("Fetching Spot Data (Market Cap & Industry)...")
    # 0. Proxy Debug Check (GHA)
    proxy_env = os.environ.get("http_proxy") or os.environ.get("HTTP_PROXY")
    if proxy_env:
        # Mask password for logs: http://user:pass@ip:port -> http://***@ip:port
        import re
        masked = re.sub(r'//.*:.*@', '//***:***@', proxy_env)
        print(f"🌐 Proxy detected in environment: {masked}")
    else:
        print("⚠️ No proxy detected in environment.")

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
    # Pre-fetch industry data once (reused in fallback AND main path)
    growth_df_cached = None

    if spot_df is None or spot_df.empty:
        print("🔄 Trying Sina Daily Bars fallback (always available)...")
        try:
            # Get industry pool first to know which stocks to fetch
            target_stocks = fetch_target_industry_pool()
            
            if target_stocks.empty:
                print("❌ No industry data available")
                return pd.DataFrame()
            
            # Map for Sina loop consistency
            target_stocks = target_stocks.rename(columns={'Symbol': '股票代码', 'Name': '股票简称', 'Industry': '所处行业'})
            
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
        
        spot_df = spot_df.rename(columns=col_map)

        # --- Step A: Get Industry Data (Cascading Fallback) ---
        print("🔍 Step A: Fetching Industry Data (Multi-tier Fallback)...")
        industry_source = None
        merged = pd.DataFrame()

        # Tier 1: Semi-Batch Growth/Industry API (Most Stable - uses datacenter-web)
        print("   Tier 1: Trying Semi-Batch Growth API (Stable Tier)...")
        growth_df_cached = get_industry_data_robustly()
        if not growth_df_cached.empty and '所处行业' in growth_df_cached.columns:
            def is_target(x):
                # Handle cases where multiple industries are listed combined
                return isinstance(x, str) and any(t in x for t in TARGET_INDUSTRIES)
            
            growth_df_cached['Symbol'] = growth_df_cached['股票代码'].astype(str).str.zfill(6)
            target_growth = growth_df_cached[growth_df_cached['所处行业'].apply(is_target)].copy()
            target_growth = target_growth.rename(columns={'所处行业': 'Industry'})
            
            spot_df['Symbol'] = spot_df['Symbol'].astype(str).str.zfill(6)
            merged = pd.merge(spot_df, target_growth[['Symbol', 'Industry']], on='Symbol', how='inner')
            if not merged.empty:
                industry_source = "growth_em"
                print(f"   ✅ Tier 1 Success: {len(merged)} stocks matched")

        # Tier 2: Batch Industry Board API (Fast but hits push servers)
        if merged.empty:
            print("   Tier 1 failed. Tier 2: Trying Batch Industry API (Push Tier)...")
            industry_pool = fetch_target_industry_pool()
            if not industry_pool.empty:
                spot_df['Symbol'] = spot_df['Symbol'].astype(str).str.zfill(6)
                merged = pd.merge(spot_df, industry_pool[['Symbol', 'Industry']], on='Symbol', how='inner')
                if not merged.empty:
                    industry_source = "batch_em"
                    print(f"   ✅ Tier 2 Success: {len(merged)} stocks matched")

        # Tier 3: Filter-First Per-stock Lookup (Ultimate Fallback)
        if merged.empty:
            print("   Tier 1 & 2 failed. Tier 3: Filter-First + Per-stock scan...")
            # Pre-filter spot_df to reduce scan size (Market Cap > 20B, Price > 2.0)
            candidates = spot_df.copy()
            candidates['Market_Cap'] = pd.to_numeric(candidates['Market_Cap'], errors='coerce')
            
            # If Market_Cap is missing (common in tencent source), use Price/Change criteria to at least reduce.
            # But normally we want Market Cap. If it's 0 (tencent), we keep all but rely on Price.
            filtered_cands = candidates[
                ((candidates['Market_Cap'] >= MIN_MARKET_CAP) | (candidates['Market_Cap'] == 0)) & 
                (candidates['Price'] >= 2.0)
            ].copy()
            
            print(f"   📋 Filtered to {len(filtered_cands)} candidates for scan...")
            cand_symbols = filtered_cands['Symbol'].tolist()
            # Shuffle to handle partial timeouts better in retries
            import random
            random.shuffle(cand_symbols)
            
            # Fetch industry for only these candidates
            scanned_map = fetch_industry_per_stock(cand_symbols)
            filtered_cands['Industry'] = filtered_cands['Symbol'].map(scanned_map)
            
            def is_target(x):
                return isinstance(x, str) and any(t in x for t in TARGET_INDUSTRIES)
            
            merged = filtered_cands[filtered_cands['Industry'].apply(is_target)].copy()
            if not merged.empty:
                industry_source = "per_stock_scan"
                print(f"   ✅ Tier 3 Success: {len(merged)} stocks matched")

        if merged.empty:
            print("❌ All industry-fetching tiers failed")
            return pd.DataFrame()
            
        print(f"📊 Industry Logic Complete (Source: {industry_source})")

        # --- Step B: Try to enrich with Growth Data (optional) ---
        print("Fetching Growth Data (optional, stock_yjbb_em)...")
        growth_df = growth_df_cached if growth_df_cached is not None else get_industry_data_robustly()
        
        if not growth_df.empty and '净利润-同比增长' in growth_df.columns:
            growth_lookup = growth_df[['股票代码', '净利润-同比增长']].copy()
            growth_lookup.columns = ['Symbol', 'Growth_Rate']
            growth_lookup['Symbol'] = growth_lookup['Symbol'].astype(str).str.zfill(6)
            merged = pd.merge(merged, growth_lookup, on='Symbol', how='left')
            merged['Growth_Rate'] = merged['Growth_Rate'].fillna(0)
            print(f"✅ Growth data enriched")
        else:
            print("⚠️ Growth data unavailable, skipping PEG filter")
            merged['Growth_Rate'] = 0
        
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
        if df.empty: return pd.DataFrame()
        
        # Robust column handling
        if 'date' not in df.columns:
            df = df.reset_index()
        
        col_map = {'日期': 'date', '收盘': 'close', '收盘价': 'close'}
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
        
        if 'date' not in df.columns:
             # Try common index names
             df.index.name = 'date'
             df = df.reset_index()

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
        if df is None or df.empty: return None
        
        # Robust column handling (English/Chinese/Index)
        if 'date' not in df.columns:
            df = df.reset_index()
        
        col_map = {
            '日期': 'date', '开盘': 'open', '最高': 'high', '最低': 'low', 
            '收盘': 'close', '成交量': 'volume', '收盘价': 'close'
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

        if 'date' not in df.columns: return None
        
        df = df.sort_values('date')
        df['change_pct'] = pd.to_numeric(df['close']).pct_change() * 100
        df['change_pct'] = df['change_pct'].fillna(0)
        df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
        
        # Ensure numeric types
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')

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

# --- v10.0 Ultra-Short-Term Extreme Burst Analysis ---

def calc_micro_momentum(stock_hist, index_hist):
    """v10.0: Micro Momentum (0-25).
    Replaces older 20-day / 10-day Alpha tracking.
    15 points for 3-day Alpha. 10 points for 5-day Alpha.
    """
    merged = pd.merge(stock_hist, index_hist, on='date', how='inner', suffixes=('', '_idx'))
    if len(merged) < 6:
        return 0.0, False

    closes = merged['close']
    idx_closes = merged['close_idx']

    stock_3d = (closes.iloc[-1] / closes.iloc[-4] - 1) * 100 if len(closes) > 3 else 0
    stock_5d = (closes.iloc[-1] / closes.iloc[-6] - 1) * 100 if len(closes) > 5 else 0

    idx_3d = (idx_closes.iloc[-1] / idx_closes.iloc[-4] - 1) * 100 if len(idx_closes) > 3 else 0
    idx_5d = (idx_closes.iloc[-1] / idx_closes.iloc[-6] - 1) * 100 if len(idx_closes) > 5 else 0

    alpha_3d = stock_3d - idx_3d
    alpha_5d = stock_5d - idx_5d

    # Scoring: Up to 15 pts if 3-day alpha > 7.5%, Up to 10 pts if 5-day alpha > 6.6%
    score_3d = min(max(alpha_3d * 2.0, 0), 15.0)
    score_5d = min(max(alpha_5d * 1.5, 0), 10.0)

    score = score_3d + score_5d
    is_accelerating = alpha_3d > alpha_5d > 0
    return round(score, 1), is_accelerating

def calc_institutional_burst(stock_hist, is_hot_sector):
    """v10.0: Institutional Burst (0-40).
    Captures extreme volume anomalies + price action + pocket pivots.
    """
    if len(stock_hist) < 11:
        return 0.0, 1.0, False

    today = stock_hist.iloc[-1]
    ma5_vol = stock_hist['volume'].iloc[-6:-1].mean()
    today_vol = today['volume']
    
    vol_ratio = today_vol / ma5_vol if ma5_vol > 0 else 1.0
    
    score = 0.0
    
    # 1. Price Momentum: Close near high (0-15)
    high_low_range = today['high'] - today['low']
    if high_low_range > 0:
        close_position = (today['close'] - today['low']) / high_low_range
    else:
        close_position = 1.0
        
    if close_position > 0.85 and vol_ratio >= 2.0:
        score += 15.0  # Exploding volume closing near high
    elif close_position > 0.70 and vol_ratio >= 1.5:
        score += 8.0
        
    # 2. Pocket Pivot (0-15)
    # Today's volume > max down volume of last 10 days
    recent_10 = stock_hist.iloc[-11:-1]
    down_vols = recent_10[recent_10['change_pct'] < 0]['volume']
    max_down_vol = down_vols.max() if not down_vols.empty else 0
    
    if today_vol > max_down_vol and today['change_pct'] > 0:
        score += 15.0
    elif today_vol > ma5_vol * 1.5 and today['change_pct'] > 0:
        score += 5.0
        
    # 3. Sector Synergy & Active Turnover (0-10)
    if is_hot_sector:
        score += 10.0

    return min(score, 40.0), round(vol_ratio, 2), close_position > 0.85

def calc_vcp_breakout(stock_hist):
    """v10.0: VCP & Squeeze Breakout (0-15).
    Yesterday volume extremely low, today exploding upwards.
    """
    if len(stock_hist) < 6: return 0.0, False
    
    ma5_vol_prev = stock_hist['volume'].iloc[-7:-2].mean()
    yesterday_vol = stock_hist.iloc[-2]['volume']
    today_vol = stock_hist.iloc[-1]['volume']
    
    score = 0.0
    is_vcp = False
    
    if yesterday_vol < ma5_vol_prev * 0.6:  # Extreme volume contraction yesterday
        if today_vol > yesterday_vol * 2.0 and stock_hist.iloc[-1]['change_pct'] > 2.0:
            score += 15.0  # Perfect slingshot
            is_vcp = True
        elif today_vol > yesterday_vol * 1.5 and stock_hist.iloc[-1]['change_pct'] > 0:
            score += 8.0
            
    return score, is_vcp


def calc_limit_up_gene(stock_hist, lookback=20):
    """v11.0: Limit-Up Gene Factor (连板基因) — bonus scoring (0-15).

    Evaluates:
    1. Has the stock hit limit-up in the past N days? (+5 base)
    2. How early in the day did the limit-up occur? (proxy: high == close) (+3)
    3. Day-after premium rate for the most recent limit-up day (+7 max)
    """
    if stock_hist is None or len(stock_hist) < lookback:
        return 0.0, False

    recent = stock_hist.tail(lookback)
    score = 0.0
    had_limit_up = False

    # Detect limit-up days (change_pct >= 9.5% for main board, >= 19.5% for STAR/ChiNext)
    limit_up_days = recent[recent['change_pct'] >= 9.5]

    if len(limit_up_days) == 0:
        return 0.0, False

    had_limit_up = True
    score += 5.0  # Base: had a limit-up in the lookback period

    # Check most recent limit-up quality
    last_lu = limit_up_days.iloc[-1]

    # Proxy for early seal: close == high (strong buying pressure, sealed at limit)
    if last_lu['close'] >= last_lu['high'] * 0.999:
        score += 3.0  # Tight seal — likely early limit-up

    # Day-after premium: find the bar right after the limit-up
    lu_idx = stock_hist.index.get_loc(last_lu.name)
    if lu_idx + 1 < len(stock_hist):
        next_day = stock_hist.iloc[lu_idx + 1]
        premium = next_day['change_pct']
        # Positive premium after limit-up = strong continuation gene
        if premium > 3.0:
            score += 7.0
        elif premium > 0:
            score += 4.0

    return round(min(score, 15.0), 1), had_limit_up


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

def detect_market_regime(index_hist):
    """v11.0: Detect market regime from recent index performance.

    Returns: (regime, index_5d_change)
        regime: 'bull' / 'bear' / 'neutral'
        index_5d_change: 5-day cumulative change %
    """
    if index_hist is None or len(index_hist) < 6:
        return 'neutral', 0.0

    closes = index_hist['close']
    change_5d = (closes.iloc[-1] / closes.iloc[-6] - 1) * 100

    if change_5d >= 3.0:
        return 'bull', round(change_5d, 2)
    elif change_5d <= -3.0:
        return 'bear', round(change_5d, 2)
    else:
        return 'neutral', round(change_5d, 2)


def fetch_market_sentiment():
    """v11.0: Fetch macro sentiment factors as a global confidence multiplier.

    Returns: (multiplier, sentiment_details)
        multiplier: 0.7 ~ 1.3 (dampens or amplifies confidence)
        sentiment_details: dict with individual factor readings
    """
    details = {}
    sentiment_score = 0  # -3 (extreme fear) to +3 (extreme greed)

    # Factor 1: Northbound capital flow (沪深港通)
    try:
        hsgt_df = ak.stock_hsgt_hist_em(symbol="沪深港通")
        if hsgt_df is not None and len(hsgt_df) >= 1:
            # Get latest day net inflow (in 亿元)
            latest = hsgt_df.iloc[-1]
            # Column name varies; try common patterns
            flow_col = None
            for col in hsgt_df.columns:
                if '净' in str(col) and '流' in str(col):
                    flow_col = col
                    break
            if flow_col is None:
                flow_col = hsgt_df.columns[1]  # fallback to second column

            net_flow = float(latest[flow_col])
            details['northbound_flow'] = round(net_flow, 2)
            if net_flow > 50:
                sentiment_score += 1
            elif net_flow > 100:
                sentiment_score += 2
            elif net_flow < -50:
                sentiment_score -= 1
            elif net_flow < -100:
                sentiment_score -= 2
    except Exception as e:
        print(f"  ⚠️ 北向资金获取失败: {e}")
        details['northbound_flow'] = None

    # Factor 2: Limit-up / limit-down count (涨停/跌停数)
    try:
        zt_df = ak.stock_zt_pool_em(date=datetime.datetime.now().strftime('%Y%m%d'))
        limit_up_count = len(zt_df) if zt_df is not None else 0
        details['limit_up_count'] = limit_up_count
        if limit_up_count >= 80:
            sentiment_score += 1  # Hot market
        elif limit_up_count <= 20:
            sentiment_score -= 1  # Cold market
    except Exception:
        details['limit_up_count'] = None

    try:
        dt_df = ak.stock_zt_pool_zbgc_em(date=datetime.datetime.now().strftime('%Y%m%d'))
        limit_down_count = len(dt_df) if dt_df is not None else 0
        details['limit_down_count'] = limit_down_count
        if limit_down_count >= 30:
            sentiment_score -= 1  # Panic
    except Exception:
        details['limit_down_count'] = None

    # Factor 3: Market-wide fund flow
    try:
        flow_df = ak.stock_main_fund_flow()
        if flow_df is not None and len(flow_df) >= 1:
            # Main force net inflow for the market
            latest = flow_df.iloc[0]
            for col in flow_df.columns:
                if '净' in str(col) and '额' in str(col):
                    main_flow = float(latest[col])
                    details['main_fund_flow'] = round(main_flow / 1e8, 2)  # Convert to 亿
                    if main_flow > 0:
                        sentiment_score += 1
                    break
    except Exception:
        details['main_fund_flow'] = None

    # Convert sentiment_score to multiplier
    # -3 → 0.7, 0 → 1.0, +3 → 1.3
    multiplier = 1.0 + (sentiment_score * 0.1)
    multiplier = max(0.7, min(1.3, multiplier))
    details['raw_score'] = sentiment_score

    return round(multiplier, 2), details


# Default weight allocation
DEFAULT_WEIGHTS = {
    'inst_burst': 40,
    'micro_mom': 25,
    'antigravity': 20,
    'vcp': 15,
}

# Market-regime-adaptive weight adjustments
REGIME_WEIGHT_ADJUSTMENTS = {
    'bull':    {'inst_burst': 0, 'micro_mom': +10, 'antigravity': -10, 'vcp': 0},
    'bear':    {'inst_burst': -10, 'micro_mom': 0, 'antigravity': +10, 'vcp': 0},
    'neutral': {'inst_burst': 0, 'micro_mom': 0, 'antigravity': 0, 'vcp': 0},
}


def get_regime_weights(regime='neutral'):
    """v11.0: Return adjusted weight caps based on market regime."""
    adj = REGIME_WEIGHT_ADJUSTMENTS.get(regime, REGIME_WEIGHT_ADJUSTMENTS['neutral'])
    return {k: DEFAULT_WEIGHTS[k] + adj[k] for k in DEFAULT_WEIGHTS}


def calc_composite_score(ag_score, micro_mom_score, inst_score, vcp_score, regime='neutral'):
    """v11.0: Ultra-Short-Term Extreme Burst (0-100) with market-adaptive weights.

    Default weight allocation:
    1. Institutional Burst (Volume/Price/Sector) — 40pts
    2. Micro-Momentum (3D/5D Alpha)              — 25pts
    3. Antigravity (Resilience)                  — 20pts
    4. VCP / Squeeze Breakout                    — 15pts

    Bull regime: Momentum +10, AG -10
    Bear regime: AG +10, Burst -10
    """
    w = get_regime_weights(regime)

    score = 0.0
    score += min(inst_score, w['inst_burst'])                           # capped by regime weight
    score += min(micro_mom_score, w['micro_mom'])                       # capped by regime weight
    score += min(ag_score * 2.0, float(w['antigravity']))               # ag_score natively 0-10
    score += min(vcp_score, w['vcp'])                                   # capped by regime weight

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
        if pd.isna(growth): growth = 0
        if pd.isna(pe_ttm): pe_ttm = 0
        # When growth data is unavailable (0), skip PEG filter gracefully
        if growth != 0:
            peg = pe_ttm / growth if growth > 0 else 999
            fund_ok = (growth > cfg.high_growth) or (peg < cfg.max_peg and growth > cfg.min_growth)
            if not fund_ok: return False, change_pct

    return True, change_pct

def _filter_technicals(hist, change_pct, realtime_change_pct, turnover_rate=None, cfg=CONFIG):
    """Apply v10.0 technical filters. Returns (pass, rsi, stock_3d, vcp_signal)."""
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

    # v10.0 Liquidity & Active Turnover Gate (replaces simple volume checks)
    if turnover_rate is not None and turnover_rate > 0:
        if turnover_rate < 5.0 or turnover_rate > 35.0:
            return False, rsi, stock_3d, False
    else:
        # Fallback to absolute volume if turnover is missing
        avg_volume_20 = hist['volume'].tail(20).mean()
        if pd.notna(avg_volume_20) and avg_volume_20 < cfg.min_avg_volume:
            return False, rsi, stock_3d, False

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


def calc_ma_alignment_score(stock_hist):
    """v11.0: MA Alignment Cycle Filter (周期过滤器).

    Scores based on MA5/MA20/MA60 alignment:
    - Full bull alignment (MA5 > MA20 > MA60): +10 bonus
    - Partial alignment (MA5 > MA20 only):     +5 bonus
    - Bear alignment (MA5 < MA20 < MA60):      -5 penalty
    - Neutral/mixed:                            0

    Returns: (score_adjustment, alignment_label)
    """
    if stock_hist is None or len(stock_hist) < 60:
        return 0.0, 'insufficient_data'

    close = stock_hist['close']
    ma5 = close.rolling(5).mean().iloc[-1]
    ma20 = close.rolling(20).mean().iloc[-1]
    ma60 = close.rolling(60).mean().iloc[-1]

    if pd.isna(ma5) or pd.isna(ma20) or pd.isna(ma60):
        return 0.0, 'na'

    if ma5 > ma20 > ma60:
        return 10.0, '多头排列'
    elif ma5 > ma20:
        return 5.0, '短多'
    elif ma5 < ma20 < ma60:
        return -5.0, '空头排列'
    else:
        return 0.0, '震荡'


def _save_and_report(results, csv_path, last_trading_date):
    """Save results to CSV, track in Boomerang, call Commander."""
    if not results:
        print("No stocks matched v6.0 criteria.")
        # If no stocks, write an empty CSV to clear old signals
        pd.DataFrame(columns=['Symbol', 'Name', 'Date', 'Industry', 'Price', 'Change_Pct', 'AG_Score', 'AG_Details', 'Volume_Note', 'RS_Score', 'Vol_Explosion', 'Momentum_Accel', 'Sector_Leader', 'Flow_Ratio', 'Composite']).to_csv(csv_path, index=False)
        return

    # Add Date explicitly to all results
    for r in results:
        r['Date'] = last_trading_date

    final_df = pd.DataFrame(results)
    final_df = final_df.sort_values(by=['AG_Score'], ascending=False)

    # Save CSV (OVERWRITE mode)
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
    print(f"=== Starting 'Siphon Strategy v10.0 — Ultra-Short-Term Extreme Burst' (Market: {market}) ===")
    
    # v10.2: Early exit if market is closed
    if not is_trading_day():
        print("⏸️ Market is CLOSED today. Skipping strategy execution.")
        return
    
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

    # v12.0: ATR-based Regime Sensor (from loop-win-2026)
    regime_sensor = RegimeSensor()
    regime_sensor.detect(index_df)
    regime, idx_5d_chg = detect_market_regime(index_df)
    regime_weights = get_regime_weights(regime)
    regime_labels = {'bull': '牛市', 'bear': '熊市', 'neutral': '震荡'}
    print(f"📊 市场状态: {regime_labels[regime]} (5日涨跌: {idx_5d_chg:+.2f}%)")
    print(f"   ATR状态: {regime_sensor.get_summary()}")
    print(f"   权重分配: Burst={regime_weights['inst_burst']} Mom={regime_weights['micro_mom']} AG={regime_weights['antigravity']} VCP={regime_weights['vcp']}")

    # v12.0: 初始化深度因子引擎和拥挤度检测
    deep_engine = DeepFactorEngine()
    crowd_detector = CrowdingDetector()
    reversal_scanner = ReversalScanner()

    # v11.0: Market sentiment multiplier
    sentiment_mult, sentiment_details = fetch_market_sentiment()
    print(f"🌡️ 市场情绪乘数: {sentiment_mult}x (原始分: {sentiment_details.get('raw_score', 'N/A')})")
    if sentiment_details.get('northbound_flow') is not None:
        print(f"   北向资金: {sentiment_details['northbound_flow']}亿")
    if sentiment_details.get('limit_up_count') is not None:
        print(f"   涨停数: {sentiment_details['limit_up_count']}")

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
        turnover_rate = pd.to_numeric(row.get('Turnover_Rate', 0), errors='coerce')
        hist_close = hist.iloc[-1]['close']
        current_price = spot_price if (pd.notna(spot_price) and spot_price > 0) else hist_close
        change_pct = hist.iloc[-1]['change_pct']
        
        # Step 2: Technical filtering
        tech_ok, rsi, stock_3d, vcp_signal = _filter_technicals(hist, change_pct, realtime_change_pct, turnover_rate, cfg)
        if not tech_ok: continue

        # Limit-up check
        if realtime_change_pct > cfg.limit_up_threshold:
            print(f"Skip {name}: Daily Limit Up/Surge (+{realtime_change_pct:.2f}%)")
            continue

        # Step 3: v10.0 Enhanced Scoring
        ag_score, ag_details = calculate_antigravity_score(hist, index_df)
        if ag_score < cfg.min_ag_score:
            continue

        # v10.0: Micro Momentum
        micro_mom_score, is_accelerating = calc_micro_momentum(hist, index_df)

        # v10.0: Institutional Burst
        inst_score, vol_ratio, is_closing_high = calc_institutional_burst(hist, is_hot_sector)

        # v10.0: VCP Breakout
        vcp_score, is_vcp_breakout = calc_vcp_breakout(hist)

        # v11.0: Limit-Up Gene (连板基因) — bonus factor
        lu_gene_score, had_limit_up = calc_limit_up_gene(hist)

        # v11.0: MA Alignment (周期过滤器) — bonus/penalty
        ma_align_score, ma_align_label = calc_ma_alignment_score(hist)

        # v12.0: 深度因子计算
        deep_score = None
        deep_factors = {}
        try:
            deep_factors = deep_engine.compute_for_stock(symbol, hist, index_df)
            # 简化计算deep_score: 各因子z-score等权
            factor_vals = [v for v in deep_factors.values() if v is not None]
            if factor_vals:
                arr = np.array(factor_vals)
                mean_v, std_v = arr.mean(), arr.std()
                if std_v > 0:
                    z_mean = ((arr - mean_v) / std_v).clip(-3, 3).mean()
                    deep_score = float(z_mean * 20 + 50)
                else:
                    deep_score = 50.0
        except Exception:
            deep_score = None

        # v12.0: VWAP评分
        vwap = VWAPCalc.calc_daily_vwap(hist, window=5)
        vwap_score = VWAPCalc.calc_vwap_score(current_price, vwap)

        # v12.0: 增强版综合评分 (融合深度因子 + VWAP)
        composite = calc_enhanced_composite(
            ag_score, micro_mom_score, inst_score, vcp_score,
            deep_score=deep_score, vwap_score=vwap_score, regime=regime
        )

        # v11.0: Add bonus factors (limit-up gene + MA alignment)
        composite = round(min(max(composite + lu_gene_score + ma_align_score, 0), 100.0), 1)

        # v11.0: Apply sentiment multiplier to composite score
        composite_raw = composite
        composite = round(min(composite * sentiment_mult, 100.0), 1)

        # v12.0: ATR regime阈值调整
        regime_threshold = cfg.min_composite_score * regime_sensor.get_threshold_mult()
        if composite < regime_threshold:
            continue

        # Build signal tags
        signal_tags = []
        if inst_score >= 25: signal_tags.append(f"爆量突袭{vol_ratio:.1f}x")
        if micro_mom_score >= 15: signal_tags.append("强势连击")
        if is_closing_high: signal_tags.append("光头阳")
        if is_vcp_breakout: signal_tags.append("老鸭头突破")
        if ag_score >= 4: signal_tags.append("金身防御盾")
        if is_hot_sector: signal_tags.append("主线共振")
        if had_limit_up: signal_tags.append("连板基因")
        if ma_align_label == '多头排列': signal_tags.append("多头排列")
        # v12.0: 深度因子标签
        if deep_factors.get('resid_mom') and deep_factors['resid_mom'] > 0.005:
            signal_tags.append("残差动量+")
        if deep_factors.get('lu_strength') and deep_factors['lu_strength'] > 0.05:
            signal_tags.append("封板坚定")
        if vwap_score >= 8:
            signal_tags.append("VWAP强势")
        signal_str = " ".join(signal_tags) if signal_tags else "Momentum"

        vol_note = f"VolR:{vol_ratio:.1f}x Burst:{inst_score:.0f}"

        symbol_str = str(symbol).zfill(6)

        # v12.0: 增强版信心评级
        grade, grade_label, grade_color = get_enhanced_confidence_grade(composite, regime)

        results.append({
            'Symbol': symbol_str,
            'Name': name,
            'Date': last_trading_date,
            'Industry': industry,
            'Price': float(current_price),
            'Change_Pct': change_pct,
            'AG_Score': composite,
            'Strategy': signal_str,
            'Logic': signal_str,
            'Volume_Note': vol_note,
            'RS_Score': micro_mom_score,
            'Vol_Explosion': vol_ratio,
            'Momentum_Accel': vcp_score,
            'Sector_Leader': is_hot_sector,
            'Flow_Ratio': inst_score,
            'Composite': composite,
            'Grade': grade,
            'Grade_Label': grade_label,
            'MA_Alignment': ma_align_label,
            'Deep_Score': deep_score,
            'VWAP_Score': vwap_score,
            'Regime': regime_sensor.get_regime_label(),
        })
        print(f"MATCH {name}: [{grade}] C={composite} Mom={micro_mom_score:.1f} Burst={inst_score:.0f} Deep={deep_score or 'N/A'} VWAP={vwap_score:.0f} MA={ma_align_label}")
    
    # v12.0: 拥挤度过滤 — 移除高相关性推荐
    if results and len(results) >= 3:
        try:
            rec_klines = {}
            for r in results:
                kdf = kline_cache.get(r['Symbol']) if kline_cache else None
                if kdf is not None:
                    rec_klines[r['Symbol']] = kdf
            if len(rec_klines) >= 2:
                crowd_alert = crowd_detector.check_recommendations(rec_klines)
                print(f"🔍 拥挤度: {crowd_alert.get_label()} — {crowd_alert.action}")
                if crowd_alert.reasons:
                    for reason in crowd_alert.reasons:
                        print(f"   {reason}")
                # 移除高相关股票
                to_remove = crowd_detector.filter_correlated_stocks(rec_klines)
                if to_remove:
                    before = len(results)
                    results = [r for r in results if r['Symbol'] not in to_remove]
                    print(f"   拥挤过滤: {before} → {len(results)} (移除{len(to_remove)}只高相关股)")
        except Exception as e:
            print(f"⚠️ 拥挤度检测跳过: {e}")

    # v12.0: 反转策略扫描 — 补充动量信号
    try:
        reversal_klines = {}
        for idx_r, row_r in pool.iterrows():
            sym_r = str(row_r['Symbol']).zfill(6)
            kdf_r = kline_cache.get(sym_r) if kline_cache else None
            if kdf_r is not None and len(kdf_r) >= 25:
                reversal_klines[sym_r] = kdf_r
        if reversal_klines:
            industry_map = {str(row_r['Symbol']).zfill(6): row_r['Industry']
                           for _, row_r in pool.iterrows()}
            reversal_signals = reversal_scanner.scan(
                reversal_klines, hot_industries=hot_sectors, industry_map=industry_map)
            if reversal_signals:
                print(f"🔄 反转信号: {len(reversal_signals)}只")
                existing_codes = {r['Symbol'] for r in results}
                for sig in reversal_signals:
                    if sig['stock_code'] not in existing_codes:
                        results.append({
                            'Symbol': sig['stock_code'],
                            'Name': sig.get('stock_name', ''),
                            'Date': last_trading_date,
                            'Industry': industry_map.get(sig['stock_code'], ''),
                            'Price': sig['rec_price'],
                            'Change_Pct': 0,
                            'AG_Score': sig['siphon_score'],
                            'Strategy': sig['strategy_tag'],
                            'Logic': sig['core_logic'],
                            'Volume_Note': 'Reversal',
                            'RS_Score': 0,
                            'Vol_Explosion': 0,
                            'Momentum_Accel': 0,
                            'Sector_Leader': False,
                            'Flow_Ratio': 0,
                            'Composite': sig['siphon_score'],
                            'Grade': 'B',
                            'Grade_Label': '反转观察',
                            'MA_Alignment': '',
                            'Deep_Score': None,
                            'VWAP_Score': 0,
                            'Regime': regime_sensor.get_regime_label(),
                        })
                        print(f"  + {sig['stock_code']} {sig.get('stock_name','')} "
                              f"Score={sig['siphon_score']:.0f} {sig['core_logic']}")
    except Exception as e:
        print(f"⚠️ 反转扫描跳过: {e}")

    # v12.0: 打印市场状态摘要
    print(f"\n{'='*50}")
    print(f"📊 {regime_sensor.get_summary()}")
    print(f"📈 动量推荐: {sum(1 for r in results if 'Reversal' not in r.get('Strategy',''))}只")
    print(f"🔄 反转推荐: {sum(1 for r in results if 'Reversal' in r.get('Strategy',''))}只")
    print(f"{'='*50}\n")

    # Step 4: Save and report
    _save_and_report(results, "siphon_strategy_results.csv", last_trading_date)

if __name__ == "__main__":
    run_siphoner_strategy()
