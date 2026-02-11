
import akshare as ak
import pandas as pd
import time
import datetime
import os
import functools
import warnings
import pickle
import random
import consult_commander # Import the new tool

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

def with_cache(ttl_hours=4):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            arg_str = "_".join([str(a) for a in args])
            kwarg_str = "_".join([f"{k}-{v}" for k, v in kwargs.items()])
            identifier = f"siphon_{func.__name__}_{arg_str}_{kwarg_str}"
            identifier = "".join(c if c.isalnum() or c in ['_', '-'] else '_' for c in identifier)
            cache_file = os.path.join(CACHE_DIR, f"{identifier}.pkl")
            
            if os.path.exists(cache_file):
                mtime = os.path.getmtime(cache_file)
                if (time.time() - mtime) < (ttl_hours * 3600):
                    try:
                        with open(cache_file, 'rb') as f:
                            print(f"[Cache Hit] {func.__name__}")
                            return pickle.load(f)
                    except: pass
            
            result = func(*args, **kwargs)
            if result is not None:
                if isinstance(result, pd.DataFrame) and result.empty:
                    pass 
                else:
                    try:
                        with open(cache_file, 'wb') as f:
                            pickle.dump(result, f)
                    except: pass
            return result
        return wrapper
    return decorator

# --- Data Fetching ---

@with_cache(ttl_hours=4)
def fetch_basic_pool():
    print("Fetching Spot Data (Market Cap & Industry)...")
    try:
        spot_df = ak.stock_zh_a_spot_em()
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
        
        merged['Market_Cap'] = pd.to_numeric(merged['Market_Cap'], errors='coerce')
        merged = merged[merged['Market_Cap'] >= MIN_MARKET_CAP]
        
        def is_target_industry(ind_name):
            if not isinstance(ind_name, str): return False
            return any(target in ind_name for target in TARGET_INDUSTRIES)
            
        merged = merged[merged['Industry'].apply(is_target_industry)]
        return merged # Changed from final_df to merged to maintain correctness
    except Exception as e:
        print(f"Error fetching A-share pool: {e}")
        return pd.DataFrame()

@with_cache(ttl_hours=4)
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

@with_cache(ttl_hours=12)
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

@with_cache(ttl_hours=8)
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
        return df[['date', 'close', 'volume', 'change_pct']]
        
    except Exception as e:
        raise e

@with_cache(ttl_hours=8)
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
        return df[['date', 'close', 'volume', 'change_pct']]
        
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
    
    # Logic: 
    # 1. "Volume Siphon": Today Red (>0%), Volume < Yesterday (Lock-up)
    # 2. "Explosion": Today Red, Volume > 1.5 * MA5 (Aggressive Buy)
    
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

# --- Runner ---

@with_cache(ttl_hours=12)
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

# --- Runner ---

def run_siphoner_strategy(market='CN'):
    print(f"=== Starting 'Siphon Strategy v2.0' (Market: {market}) ===")
    
    if market == 'CN':
        pool = fetch_basic_pool()
        index_df = fetch_index_data()
    else:
        pool = fetch_hk_pool()
        index_df = fetch_hk_index_data()

    if pool.empty: return
    print(f"Candidates In Pool: {len(pool)}")
    
    if index_df.empty: return

    # v4.6 Fix: Identify "Latest Trading Day" from index data
    # If today is Sat/Sun, this will correctly point to Friday.
    last_trading_date = index_df['date'].iloc[-1] # Using 'date' column string
    print(f"📅 Effective Analysis Date: {last_trading_date}")
        
    results = []
    processed_count = 0
    max_process = 300
    
    # Shuffle for fairness if time limited
    pool = pool.sample(frac=1).reset_index(drop=True)
    
    for idx, row in pool.iterrows():
        symbol = row['Symbol']
        name = row['Name']
        
        # --- CRITICAL FILTERING ---
        try:
            change_pct = float(row['Change_Pct'])
        except: center_pct = 0.0
            
        # 1. Guillotine
        if change_pct < -3.0: continue

        # 2. Sector Conflict
        industry = str(row['Industry'])
        if '光伏' in industry and change_pct <= 0: continue

        # Fundamental
        pe_ttm = pd.to_numeric(row.get('PE_TTM', 0), errors='coerce')
        growth = pd.to_numeric(row.get('Growth_Rate', 0), errors='coerce')
        
        # HK Market: Skip specialized PE/Growth filters for now (data less standardized in spot limit)
        # Only apply strict PEG validtion for CN market
        if market == 'CN':
            if pd.isna(growth): continue
            if pd.isna(pe_ttm): pe_ttm = 0
            peg = pe_ttm / growth if growth > 0 else 999
            fund_ok = (growth > 30) or (peg < 1.5 and growth > 10)
            if not fund_ok: continue
            
        time.sleep(0.5) 
        
        try:
            if market == 'CN':
                hist = fetch_stock_history_cn(symbol)
            else:
                hist = fetch_stock_history_hk(symbol)
        except:
             continue
             
        if hist is None: continue
        
        # CRITICAL: Preserve real-time change_pct BEFORE it gets overwritten by historical data
        realtime_change_pct = change_pct  # This is from row['Change_Pct'] at line 262
        
        current_price = hist.iloc[-1]['close']
        change_pct = hist.iloc[-1]['change_pct']  # Historical cached data
        
        # --- PRE-CALCULATION FOR v3.0 ---
        # 3-Day Index Change (Passed from outside if optimal, or simplified here)
        # Using global index_data if available or assuming flat env
        
        # --- v3.0 FILTER 1: Anti-Chase (The "Anti-FOMO" Shield) ---
        # Exclude if cumulative gain > 15% in last 5 days
        if len(hist) > 5:
            close_5d_ago = hist.iloc[-6]['close']
            gain_5d = (current_price - close_5d_ago) / close_5d_ago * 100
            if gain_5d > 15.0: continue # Skip chasers

        # Exclude RSI > 75 (Overbought)
        # Simplified RSI-14
        delta = hist['close'].diff()
        u = delta.where(delta > 0, 0)
        d = -delta.where(delta < 0, 0)
        rs = u.rolling(14).mean() / d.rolling(14).mean()
        rsi = 100 - (100 / (1 + rs)).iloc[-1]
        if not pd.isna(rsi) and rsi > 75: continue # Skip overbought

        # --- v3.0 FILTER 1.5: No Daily Limit Up (User Request) ---
        # CRITICAL FIX: Use REAL-TIME data, not cached historical data
        # Check if stock is limit-up TODAY using real-time change_pct
        if realtime_change_pct > 8.5: 
             print(f"Skip {name}: Daily Limit Up/Surge (+{realtime_change_pct:.2f}%)")
             continue 

        # --- v3.0 FILTER 2: Siphon Pattern (Index Weak, Stock Strong) ---
        # Condition: Index (CSI300) flat/down 3d, Stock flat/up 3d
        # We need the index context. If not strictly available per-loop, we use general market sentiment.
        # Assuming `index_data` is available in scope.
        stock_3d = 0.0
        if len(hist) > 3:
            stock_3d = (current_price - hist.iloc[-4]['close']) / hist.iloc[-4]['close'] * 100
        
        # v3.5: MA50 Trend Filter (more flexible than MA60)
        if len(hist) >= 50:
            ma50 = hist['close'].rolling(50).mean().iloc[-1]
            if current_price < ma50: continue  # Must be in uptrend
        
        # v3.5: Liquidity Gate (avoid illiquid stocks)
        avg_volume_20 = hist['volume'].tail(20).mean()
        if pd.notna(avg_volume_20) and avg_volume_20 < 1000000:  # Min 1M shares/day
            continue

        # Siphon Condition: If pure logic strictness is required:
        # if market_weak and stock_strong: ...
        # For now, we enforce "Latent Strength":
        if abs(stock_3d) > 10.0: continue # Exclude wild swings (keep it latency)
        
        # --- v3.0 FILTER 3: Volume Compression (VCP) ---
        # "Drying up on drops"
        # Check last 3 days: If price drop, volume < 60% MA5
        ma5_vol = hist['volume'].tail(5).mean()
        recent_drops = hist.tail(3)[hist.tail(3)['change_pct'] < 0]
        vcp_signal = False
        
        if not recent_drops.empty:
            # If any drop day has low volume
            for _, d_row in recent_drops.iterrows():
                if d_row['volume'] < 0.6 * ma5_vol:
                    vcp_signal = True
                    break
        else:
            # If no drops (all up/flat), check if volume is steady (not exploding)
            if hist.iloc[-1]['volume'] < 1.5 * ma5_vol:
                vcp_signal = True
        
        if not vcp_signal: continue

        # --- v3.5 SCORING: Enhanced Antigravity Score ---
        ag_score, ag_details = calculate_antigravity_score(hist, index_df)
        
        # v3.5: Raised threshold from 4 to 5 for better quality
        if ag_score < 5.0:
            continue
        
        vol_ratio_val = float(row['Volume_Ratio']) if row['Volume_Ratio'] != '-' else 1.0
        siphon_ratio = (vol_ratio_val * 10) / (abs(change_pct) + 0.5)
        
        ag_score = round(siphon_ratio, 1)
        ag_details = []
        if vcp_signal: ag_details.append("VCP")
        if stock_3d > 0: ag_details.append("RelStr")
        if rsi < 50: ag_details.append("LowRSI")
        
        ag_details_str = " ".join(ag_details) if ag_details else "Siphoning"

        # Prepare Volume Analysis String for Gemini
        vol_note = f"VolRatio:{vol_ratio_val:.1f}x (vs Avg20d)"
        if vcp_signal: vol_note += ", VCP(Contraction)"

        # v3.5 Fix: Ensure symbol is 6-digit string
        symbol_str = str(symbol).zfill(6)

        results.append({
            'Symbol': symbol_str,
            'Name': name,
            'Industry': row['Industry'],
            'Price': float(current_price),
            'Change_Pct': change_pct,
            'AG_Score': ag_score,
            'AG_Details': ag_details_str,
            'Siphon_Ratio': siphon_ratio,
            'Volume_Note': vol_note
        })
        print(f"MATCH {name}: Ratio={ag_score}")
            
    # --- REPORTING ---
    if not results:
        print("No stocks matched v3.0 criteria.")
        return

    final_df = pd.DataFrame(results)
    final_df = final_df.sort_values(by=['AG_Score'], ascending=False)
    
    # Save CSV (Append/Merge mode for Multi-Market)
    csv_path = "siphon_strategy_results.csv"
    if os.path.exists(csv_path):
        try:
            existing_df = pd.read_csv(csv_path)
            # Ensure columns match
            combined_df = pd.concat([existing_df, final_df], ignore_index=True)
            # Dedup by Symbol (keep latest)
            combined_df = combined_df.drop_duplicates(subset=['Symbol'], keep='last')
            # Sort again?
            combined_df = combined_df.sort_values(by=['AG_Score'], ascending=False)
            final_df = combined_df
        except Exception as e:
            print(f"Error merging CSV: {e}")
            
    final_df.to_csv(csv_path, index=False)
    print(f"Results saved to {csv_path} (Count: {len(final_df)})")
    
    # Formulate "Scout Data" for Gemini Commander
    top_stocks = final_df.head(3) # Top 3 Strict
    # Strict Format: Index | Name | Code | Industry | Price | Range% | SiphonRatio | Logic
    scout_data_str = "Index | Name | Code | Industry | Price | Range% | Ratio | Logic\n"
    scout_data_str += "-" * 80 + "\n"
    
    for i, row in top_stocks.iterrows():
        scout_data_str += f"{i+1} | {row['Name']} | {row['Symbol']} | {row['Industry']} | {row['Price']:.2f} | {row['Change_Pct']:.2f}% | {row['AG_Score']} | {row['AG_Details']}\n"
    
    print("\n📦 Packaging data for Commander Review...")
    
    # 1. Prepare Top Pick context
    top_pick = final_df.iloc[0]
    top_pick_context = f"""
    标的名称: {top_pick['Name']} ({top_pick['Symbol']})
    当前价格: {top_pick['Price']}
    Siphon Ratio: {top_pick['AG_Score']}
    特征: {top_pick['AG_Details']}
    量能分析: {top_pick['Volume_Note']}
    """

    # 2. Auto-track top 3 recommendations (Project Boomerang)
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

    # 3. CALL THE COMMANDER tool with Top Pick Data
    consult_commander.analyze_and_report(scout_data_str, top_pick_data=top_pick_context, attachment_path=csv_path)

if __name__ == "__main__":
    run_siphoner_strategy()
