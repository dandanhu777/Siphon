
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
    '半导体', '电子元件', '光学光电子', '消费电子', '汽车零部件',
    '通信设备', '计算机设备', '软件开发', '互联网服务',
    '光伏设备', '风电设备', '电网设备', '电池', '汽车整车',
    '医疗器械', '生物制品', '中药', '化学制药',
    '酿酒行业', '家电行业', '专用设备', '工程机械'
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

def with_cache(ttl_hours=8):
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

REQUIRED_COLS = ['Symbol', 'Name', 'Price', 'Change_Pct', 'Volume_Ratio', 'Turnover_Rate', 'PE_TTM', 'Market_Cap', 'Industry', 'Growth_Rate']

def _ensure_columns(df):
    if df.empty: return df
    for col in REQUIRED_COLS:
        if col not in df.columns:
            # Default values
            if col in ['Name', 'Symbol', 'Industry']: df[col] = 'Unknown'
            elif col == 'Market_Cap': df[col] = MIN_MARKET_CAP * 2
            elif col == 'Volume_Ratio': df[col] = 1.0
            else: df[col] = 0.0
    return df[REQUIRED_COLS] # Return strict schema

@with_cache(ttl_hours=8)
def fetch_basic_pool():
    print("Fetching Spot Data (Market Cap & Industry)...")
    
    # --- Attempt 1: Eastmoney (Primary) ---
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
            # Fallback if growth data fails but spot worked
            growth_df = pd.DataFrame(columns=['Symbol', 'Industry', 'Growth_Rate'])

        spot_df = spot_df.rename(columns=col_map)
        
        # Merge if we have growth data, otherwise just use spot
        if not growth_df.empty:
            merged = pd.merge(spot_df, growth_df, on='Symbol', how='inner')
        else:
             merged = spot_df
             merged['Industry'] = 'Unknown'
             merged['Growth_Rate'] = 0.0
        
        merged['Market_Cap'] = pd.to_numeric(merged['Market_Cap'], errors='coerce')
        merged = merged[merged['Market_Cap'] >= MIN_MARKET_CAP]
        
        def is_target_industry(ind_name):
            if not isinstance(ind_name, str): return False
            if ind_name == 'Unknown': return True # Allow unknown in fallback scenarios
            return any(target in ind_name for target in TARGET_INDUSTRIES)
            
        merged = merged[merged['Industry'].apply(is_target_industry)]
        
        return _ensure_columns(merged)
        
    except Exception as e:
        print(f"⚠️ Eastmoney Primary Failed: {e}")

    # --- Attempt 2: Sina (Fallback) ---
    try:
        print("🔄 Attempting Sina Fallback...")
        # ak.stock_zh_a_spot() returns: 代码, 名称, 最新价, 涨跌额, 涨跌幅, 买入, 卖出, 昨收, 今开, 最高, 最低, 成交量, 成交额, 时间戳
        spot_df = ak.stock_zh_a_spot()
        
        def clean_sina_symbol(x):
            return "".join(filter(str.isdigit, str(x)))
            
        spot_df['Symbol'] = spot_df['代码'].apply(clean_sina_symbol)
        spot_df['Name'] = spot_df['名称']
        spot_df['Price'] = pd.to_numeric(spot_df['最新价'], errors='coerce')
        spot_df['Change_Pct'] = pd.to_numeric(spot_df['涨跌幅'], errors='coerce') 
        
        # Fill missing critical columns
        spot_df['Volume_Ratio'] = 1.0 
        spot_df['Turnover_Rate'] = 0.0
        spot_df['PE_TTM'] = 0.0
        spot_df['Market_Cap'] = MIN_MARKET_CAP * 2 
        spot_df['Industry'] = 'Unknown' 
        spot_df['Growth_Rate'] = 0.0
        
        merged = spot_df
        print(f"✅ Sina Fallback Success: {len(merged)} candidates")
        return _ensure_columns(merged)
        
    except Exception as e:
        print(f"⚠️ Sina Fallback Failed: {e}")

    # --- Attempt 3: Soft Cache (Last Resort) ---
    print("⚠️ All Fresh Fetches Failed. Looking for Soft Cache...")
    try:
        # Find latest cache file
        cache_files = [f for f in os.listdir(CACHE_DIR) if f.startswith('siphon_fetch_basic_pool')]
        if cache_files:
            latest_file = max([os.path.join(CACHE_DIR, f) for f in cache_files], key=os.path.getmtime)
            age_hours = (time.time() - os.path.getmtime(latest_file)) / 3600
            
            with open(latest_file, 'rb') as f:
                cached_data = pickle.load(f)
                
            print(f"✅ Loaded Soft Cache: {latest_file} (Age: {age_hours:.1f}h)")
            print(f"   WARNING: Data is {age_hours:.1f} hours old. Prices may be stale.")
            return _ensure_columns(cached_data)
    except Exception as e:
        print(f"❌ Soft Cache Failed: {e}")
        
    return pd.DataFrame()

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
@retry(times=1, initial_delay=1)
def fetch_stock_history_sina(symbol, days=60):
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
        
        # v4.4 Fix: Normalize date column
        if 'date' not in df.columns:
            if '日期' in df.columns:
                df = df.rename(columns={'日期': 'date'})
        
        if 'date' not in df.columns: # Still missing
             # Try to find date-like column
             for col in df.columns:
                 if 'date' in col.lower() or 'time' in col.lower():
                     df = df.rename(columns={col: 'date'})
                     break

        if 'date' not in df.columns:
            print(f"⚠️ {symbol}: Missing 'date' column. Columns: {df.columns.tolist()}")
            return None

        df = df.sort_values('date')
        df['change_pct'] = df['close'].pct_change() * 100
        df['change_pct'] = df['change_pct'].fillna(0)
        df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
        return df[['date', 'close', 'volume', 'change_pct']]
        
    except Exception as e:
        raise e

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

def run_siphoner_strategy():
    print("=== Starting 'Siphon Strategy v2.0' (Independent Antigravity) ===")
    
    pool = fetch_basic_pool()
    pool = _ensure_columns(pool) # v4.3 Fix: Ensure strict schema
    if pool.empty: return
    print(f"Candidates In Pool: {len(pool)}")
    
    index_df = fetch_index_data()
    if index_df.empty: return
        
    results = []
    processed_count = 0
    max_process = 300
    
    # Shuffle for fairness if time limited
    pool = pool.sample(frac=1).reset_index(drop=True)
    
    for idx, row in pool.iterrows():
        symbol = str(row['Symbol'])
        name = row['Name']
        
        # v4.4 Filter: Exclude HK/Non-A-share (Must be 6 digits)
        if len(symbol) != 6 or not symbol.isdigit():
            continue
        
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
        pe_ttm = pd.to_numeric(row['PE_TTM'], errors='coerce')
        growth = pd.to_numeric(row['Growth_Rate'], errors='coerce')
        
        # v4.3 Fallback Bypass:
        if str(row['Industry']) == 'Unknown' and growth == 0.0:
            pass # Skip fundamental check in fallback mode
        else:
            if pd.isna(growth): continue
            if pd.isna(pe_ttm): pe_ttm = 0
            peg = pe_ttm / growth if growth > 0 else 999
            fund_ok = (growth > 30) or (peg < 1.5 and growth > 10)
            
            if not fund_ok: continue
            
        processed_count += 1
        if processed_count % 50 == 0:
            print(f"Processed {processed_count}/{600}...")
        if processed_count > 600:
            print("🛑 Reached max process limit (600). Stopping strategy loop.")
            break
            
        time.sleep(0.5) 
        
        try:
            hist = fetch_stock_history_sina(symbol)
        except:
             continue
             
        if hist is None: continue
        
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
    
    # Save CSV
    csv_path = "siphon_strategy_results.csv"
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
                industry=row['Industry'],
                core_logic=row['Volume_Note']
            )
    except Exception as e:
        print(f"⚠️ Boomerang tracking skipped: {e}")

    # 3. CALL THE COMMANDER tool with Top Pick Data
    consult_commander.analyze_and_report(scout_data_str, top_pick_data=top_pick_context, attachment_path=csv_path)

if __name__ == "__main__":
    run_siphoner_strategy()
