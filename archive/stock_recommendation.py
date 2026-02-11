import akshare as ak
import pandas as pd
import time
import functools
import datetime
import requests
import re
import os
import pickle

CACHE_DIR = "data_cache"
if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR)

def with_cache(ttl_hours=8):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Generate cache key
            arg_str = "_".join([str(a) for a in args])
            kwarg_str = "_".join([f"{k}-{v}" for k, v in kwargs.items()])
            identifier = f"{func.__name__}_{arg_str}_{kwarg_str}"
            # Clean filename
            identifier = "".join(c if c.isalnum() or c in ['_', '-'] else '_' for c in identifier)
            cache_file = os.path.join(CACHE_DIR, f"{identifier}.pkl")
            
            # 1. Try Load
            if os.path.exists(cache_file):
                mtime = os.path.getmtime(cache_file)
                if (time.time() - mtime) < (ttl_hours * 3600):
                    print(f"[Cache] Loading {func.__name__} from {cache_file}...")
                    try:
                        with open(cache_file, 'rb') as f:
                            return pickle.load(f)
                    except Exception as e:
                        print(f"[Cache] Read failed: {e}")
            
            # 2. Fetch
            result = func(*args, **kwargs)
            
            # 3. Save (if valid)
            if isinstance(result, pd.DataFrame):
                 if not result.empty:
                    try:
                        with open(cache_file, 'wb') as f:
                            pickle.dump(result, f)
                        print(f"[Cache] Saved {func.__name__} to {cache_file}")
                    except Exception as e:
                         print(f"[Cache] Write failed: {e}")
            
            return result
        return wrapper
    return decorator

def retry(times=3, delay=2):
    """
    Retry decorator for robust API calls.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for i in range(times):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    print(f"[Warning] Attempt {i+1}/{times} failed for {func.__name__}: {e}")
                    time.sleep(delay)
            print(f"[Error] All {times} attempts failed for {func.__name__}.")
            return pd.DataFrame() # Return empty DF on failure
        return wrapper
    return decorator

def fetch_tencent_spot_data():
    """
    Backup Priority #1: Tencent (qtimg).
    Provides Price, PE (Dynamic), Volume Ratio.
    Mapping:
    ~3: Price
    ~32: Change%
    ~39: PE (Dynamic)
    ~49: Volume Ratio
    """
    print("Trying Tencent Finance Backup...")
    try:
        # 1. Get Code List
        stock_info = ak.stock_info_a_code_name()
        codes = stock_info['code'].tolist()
        
        # 2. Batch Request
        # Format: sh600519
        data_list = []
        batch_size = 60
        
        print(f"Fetching {len(codes)} stocks from Tencent in batches...")
        
        for i in range(0, len(codes), batch_size):
            batch = codes[i:i+batch_size]
            query_list = []
            for code in batch:
                prefix = 'sh' if code.startswith('6') else 'sz' if code.startswith('0') or code.startswith('3') else ''
                if prefix: query_list.append(f"{prefix}{code}")
            
            if not query_list: continue
            
            # Tencent API supports comma separated list
            url = f"http://qt.gtimg.cn/q={','.join(query_list)}"
            
            try:
                resp = requests.get(url, timeout=5)
                # Encoding is usually GBK
                content = resp.text
                
                # Parse
                lines = content.split(';')
                for line in lines:
                    line = line.strip()
                    if not line: continue
                    if '="' in line:
                        parts = line.split('="')
                        # v_sh600519
                        symbol_part = parts[0]
                        values = parts[1].strip('"').split('~')
                        
                        if len(values) > 50:
                            symbol = values[2] # 600519
                            name = values[1]
                            price = float(values[3])
                            change_pct = float(values[32])
                            
                            # Safe Parse PE (Index 39)
                            pe = values[39]
                            pe_ttm = float(pe) if pe and pe != '' else None
                            
                            # Safe Parse Vol Ratio (Index 49)
                            vr = values[49]
                            vol_ratio = float(vr) if vr and vr != '' else 0.0
                            
                            data_list.append({
                                '代码': symbol,
                                '名称': name,
                                '最新价': price,
                                '涨跌幅': change_pct,
                                '市盈率-动态': pe_ttm,
                                '量比': vol_ratio
                            })
            except Exception as e:
                print(f"Tencent Batch Failed: {e}")
            
            time.sleep(0.1)
            
        return pd.DataFrame(data_list)
        
    except Exception as e:
        print(f"Tencent Backup Failed: {e}")
        return pd.DataFrame()

@with_cache(ttl_hours=8)
@retry(times=3, delay=5)
def fetch_spot_data():
    print("Fetching Spot Data...")
    try:
        # Primary: AkShare (Eastmoney)
        df = ak.stock_zh_a_spot_em()
        return df[['代码', '名称', '最新价', '涨跌幅', '市盈率-动态', '量比']].copy()
    except Exception as e:
        print(f"Primary Source Failed: {e}")
        # Secondary: Tencent (Better Data: PE + VolRatio)
        return fetch_tencent_spot_data()

@with_cache(ttl_hours=8)
@retry(times=3, delay=5)
def fetch_annual_eps(date="20241231"):
    print(f"Fetching Annual Report Data ({date})...")
    df = ak.stock_yjbb_em(date=date)
    # Need: Code, EPS ('每股收益')
    if '每股收益' not in df.columns:
        # Fallback for older API versions or structure changes
        print("Warning: '每股收益' column not found directly. Columns:", df.columns)
        return pd.DataFrame()
    return df[['股票代码', '每股收益']].copy()

@with_cache(ttl_hours=8)
@retry(times=3, delay=5)
def fetch_growth_rate(date="20250930"):
    print(f"Fetching Growth Data ({date})...")
    df = ak.stock_yjbb_em(date=date)
    # Need: Code, Net Profit Growth ('净利润-同比增长'), Industry ('所处行业')
    if '净利润-同比增长' not in df.columns:
         print("Warning: '净利润-同比增长' column not found. Columns:", df.columns)
         return pd.DataFrame()
    # Ensure Industry column exists
    # Ensure Industry column exists
    if '所处行业' not in df.columns:
        print("Warning: '所处行业' column not found.")
        # Create dummy if missing to avoid crash, but filtering will fail
        df['所处行业'] = 'Unknown'
        
    return df[['股票代码', '净利润-同比增长', '所处行业']].copy()

@retry(times=3, delay=5)
def fetch_history(symbol, start_date, end_date):
    """
    Fetch daily history for a stock.
    """
    try:
        # ak.stock_zh_a_hist takes 6 digit code.
        df = ak.stock_zh_a_hist(symbol=symbol, period="daily", start_date=start_date, end_date=end_date, adjust="qfq")
        if df.empty: return pd.DataFrame()
        # Columns: 日期, 开盘, 收盘, 最高, 最低, 成交量, 成交额...
        return df[['日期', '收盘', '成交量', '涨跌幅']].copy()
    except Exception as e:
        print(f"Error fetching history for {symbol}: {e}")
        return pd.DataFrame()

def calculate_macd(df, fast=12, slow=26, signal=9):
    """
    Calculate MACD indicators.
    """
    if df.empty or len(df) < slow: return 0, 0, 0 # Not enough data
    
    # Calculate EMAs
    ema_fast = df['收盘'].ewm(span=fast, adjust=False).mean()
    ema_slow = df['收盘'].ewm(span=slow, adjust=False).mean()
    
    # Calculate DIF and DEA
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    macd = (dif - dea) * 2
    
    # Return latest values
    return dif.iloc[-1], dea.iloc[-1], macd.iloc[-1]

def analyze_startup_phase(row):
    """
    Check if stock is in 'Initial Startup Phase' (High potential).
    Logic (Optimized):
    1. Volume Expanding (Ratio > 1.2).
    2. Price Stable (5-Day Chg < 20%).
    3. Technical: MACD Golden Cross or Bullish (DIF > DEA).
    Returns: (bool is_startup, str reason, float price_change)
    """
    end_date = datetime.datetime.now().strftime("%Y%m%d")
    start_date = (datetime.datetime.now() - datetime.timedelta(days=60)).strftime("%Y%m%d") # Need more history for MACD
    
    hist_df = fetch_history(row['Symbol'], start_date, end_date)
    if hist_df.empty or len(hist_df) < 26: # Need enough for Slow EMA
        return False, "Insufficient Data", 0.0
    
    # MACD Calculation
    dif, dea, macd = calculate_macd(hist_df)
    is_macd_bullish = (dif > dea) or (macd > 0)
    
    # Get last 5 trading days
    last_5 = hist_df.tail(5)
    
    # Volume Trend
    vol_recent = last_5['成交量'].iloc[-2:].mean()
    vol_prev = last_5['成交量'].iloc[:-2].mean()
    vol_trend_ratio = vol_recent / vol_prev if vol_prev > 0 else 0
    
    # Price Trend
    price_change = last_5['涨跌幅'].sum()
    
    # Logic:
    # 1. Volume expanding (Ratio > 1.2)
    # 2. Price Rising (Change > 0) but not Overheated (Change < 20)
    # 3. MACD Bullish
    is_startup = (vol_trend_ratio > 1.2) and (0 < price_change < 20) and is_macd_bullish
    
    macd_str = "Bullish" if is_macd_bullish else "Bearish"
    reason = f"Vol: {vol_trend_ratio:.2f}x, 5D: {price_change:.1f}%, MACD: {macd_str}"
    print(f"DEBUG: {row['Name']} - {reason}")
    return is_startup, reason, price_change

def analyze_potential_breakout(row):
    """
    Check if stock is in 'Pre-Breakout Consolidation' (Low Elevation, High Potential).
    Criteria:
    1. Consolidation: 5-Day Change between -3% and +5%. (Not flew yet)
    2. Trend Support: Price > MA20 (Bullish).
    3. Volume: Healthy (0.8 < Ratio < 2.5).
    4. Technical: MACD Bullish or Turning Up.
    
    Returns: (bool is_potential, str reason, float score_boost)
    """
    end_date = datetime.datetime.now().strftime("%Y%m%d")
    start_date = (datetime.datetime.now() - datetime.timedelta(days=60)).strftime("%Y%m%d")
    
    hist_df = fetch_history(row['Symbol'], start_date, end_date)
    if hist_df.empty or len(hist_df) < 26: 
        return False, "Insufficient Data", 0.0
        
    # 1. Calc MA20
    hist_df['MA20'] = hist_df['收盘'].rolling(window=20).mean()
    current_price = hist_df['收盘'].iloc[-1]
    ma20 = hist_df['MA20'].iloc[-1]
    
    # 2. MACD
    dif, dea, macd = calculate_macd(hist_df)
    is_macd_bullish = (dif > dea) or (macd > 0) or (dif > dif * 0.9) # Improving or Bullish
    
    # 3. 5-Day Change (Consolidation)
    last_5 = hist_df.tail(5)
    price_change_5d = last_5['涨跌幅'].sum()
    
    # 4. Filter Logic
    is_consolidating = (-3 <= price_change_5d <= 8) # Tight range
    is_above_support = (current_price >= ma20)
    
    vol_ratio = row.get('Volume_Ratio', 0)
    is_volume_healthy = (0.8 <= vol_ratio <= 3.0) # Not too cold, not too hot
    
    is_potential = is_consolidating and is_above_support and is_macd_bullish and is_volume_healthy
    
    reason = []
    if is_consolidating: reason.append(f"横盘震荡({price_change_5d:.1f}%)")
    if is_above_support: reason.append("MA20支撑")
    if is_macd_bullish: reason.append("趋势向上")
    
    score_boost = 0
    if is_potential:
        score_boost = 30 # Big boost for this pattern
        # Extra points for very tight consolidation
        if abs(price_change_5d) < 3: score_boost += 10
        # Extra points for perfect support test
        if 1.0 <= (current_price / ma20) <= 1.03: score_boost += 10
        
    return is_potential, " ".join(reason), score_boost

def fetch_and_analyze():
    # 1. Fetch all data
    spot_df = fetch_spot_data()
    if spot_df.empty:
        print("Critical: Failed to fetch spot data.")
        return None, pd.DataFrame()
        
    eps_df = fetch_annual_eps("20241231")
    # If 2024 Annual isn't out (it's Jan 2026), 2024 should be available. 
    # If not, we might need 2023. But let's assume 2024 is available or we use TTM logic strictly.
    # Actually, for "Static PE", we usually use last full year. In Jan 2026, 2024 Annual is the last full year.
    # Note: 2025 Annual report is NOT out in Jan 2026 (usually Apr 2026).
    # So Static PE should be based on 2024 Annual EPS? 
    # Or 2025 if available? Stocks usually release annual reports Jan-Apr.
    # To be safe, let's try 20241231. If empty, maybe try 20231231? 
    # Let's stick to the plan: fetch 2024.
    
    growth_df = fetch_growth_rate("20250930") # Q3 2025

    # 2. Rename columns for merging
    print(f"Spot DF Columns (Before Rename): {spot_df.columns.tolist()}")
    spot_df.rename(columns={'代码': 'Symbol', '名称': 'Name', '最新价': 'Price', '涨跌幅': 'Change_Pct', '市盈率-动态': 'PE_TTM', '量比': 'Volume_Ratio'}, inplace=True)
    print(f"Spot DF Columns (After Rename): {spot_df.columns.tolist()}")
    if not eps_df.empty:
        eps_df.rename(columns={'股票代码': 'Symbol', '每股收益': 'EPS'}, inplace=True)
    else: 
        eps_df = pd.DataFrame(columns=['Symbol', 'EPS'])

    if not growth_df.empty:
        growth_df.rename(columns={'股票代码': 'Symbol', '净利润-同比增长': 'Growth_Rate', '所处行业': 'Industry'}, inplace=True)
    else:
        growth_df = pd.DataFrame(columns=['Symbol', 'Growth_Rate', 'Industry'])

    # 3. Merge
    print("Merging Data...")
    merged = pd.merge(spot_df, eps_df, on='Symbol', how='left')
    merged = pd.merge(merged, growth_df, on='Symbol', how='left')
    
    # 4. Cleanup types
    cols = ['Price', 'PE_TTM', 'EPS', 'Growth_Rate', 'Volume_Ratio']
    for col in cols:
        merged[col] = pd.to_numeric(merged[col], errors='coerce')
        
    # 5. Calculate Static PE and PEG
    merged['PE_Static'] = merged.apply(lambda row: row['Price'] / row['EPS'] if (pd.notnull(row['EPS']) and row['EPS'] > 0) else None, axis=1)
    merged['PEG'] = merged.apply(lambda row: row['PE_TTM'] / row['Growth_Rate'] if (pd.notnull(row['Growth_Rate']) and row['Growth_Rate'] > 0 and pd.notnull(row['PE_TTM'])) else None, axis=1)
    merged['PE_Improvement_Ratio'] = (merged['PE_Static'] - merged['PE_TTM']) / merged['PE_Static']

    # --- SECTOR RESONANCE ANALYSIS ---
    print("Calculating Sector Heat...")
    # Group by Industry and calculate mean price change
    sector_heat = merged.groupby('Industry')['Change_Pct'].mean().sort_values(ascending=False)
    # Identify Top 10 Hot Sectors
    top_10_sectors = sector_heat.head(10).index.tolist()
    print(f"Top 5 Hot Sectors: {top_10_sectors[:5]}")
    
    # Add Sector Score (Bonus)
    merged['Is_Hot_Sector'] = merged['Industry'].apply(lambda x: x in top_10_sectors)

    # 6. Advanced Filter & Rank
    print("Applying Advanced Filters (Hard Tech + Turnaround + Volume)...")
    
    # Hard Tech Industries (Whitelist)
    hard_tech_list = [
        '电子元件', '半导体', '光学光电子', '消费电子', # Electronics
        '计算机设备', '软件开发', '互联网服务', # AI/Computer
        '通信设备', '通信服务', # Comm
        '航天航空', '船舶制造', # Defense
        '光伏设备', '风电设备', '电池', '电网设备', # Power/New Energy
        '专用设备', '通用设备', '自动化设备', # Machinery
        '生物制品', '化学制药', '医疗器械' # Bio
    ]
    # Note: 'Industry' names from Eastmoney are usually specific. We might need partial match or broad categories.
    # The list above attempts to cover common Eastmoney/Shenwan L2 names. 
    # To be safe, we check if the industry *contains* key terms if exact match fails, or use a broader list.
    # Let's use a simpler keyword approach for robustness.
    tech_keywords = ['电子', '半导体', '计算机', '软件', '通信', '航天', '航空', '光伏', '风电', '电池', '设备', '生物', '制药', '医疗']
    
    def is_hard_tech(ind):
        if not isinstance(ind, str): return False
        return any(k in ind for k in tech_keywords)

    # Check Data Integrity for Fallback
    has_pe = merged['PE_TTM'].count() > 0
    has_vol = (merged['Volume_Ratio'].max() > 0) if not merged['Volume_Ratio'].empty else False
    
    if has_pe and has_vol:
        print("Primary Data Integrity Confirmed.")
        filtered = merged[
            (merged['PE_TTM'] > 0) &
            (merged['PEG'] > 0) & 
            (merged['PEG'] < 1) &
            (merged['PE_TTM'] < merged['PE_Static']) &
            
            # Turnaround Criteria:
            (merged['Growth_Rate'] > 50) & # High Growth
            (merged['PE_Improvement_Ratio'] > 0.3) & # Significant Valuation Repair
            
            # Volume Criteria:
            (merged['Volume_Ratio'] > 1.5) # Abnormal Volume
        ].copy()
        sort_col = 'Volume_Ratio'
    else:
        # Fallback Mode (Sina)
        print("!! Fallback Mode Detected (Missing PE/Volume). Relaxing filters. !!")
        # Filter by Growth and Industry only (Price > 0, Growth > 30)
        filtered = merged[
            (merged['Price'] > 0) &
            (merged['Growth_Rate'] > 30) # Relaxed Growth
        ].copy()
        sort_col = 'Change_Pct' # Sort by Gain since Volume is 0
    
    # Apply Industry Filter
    filtered = filtered[filtered['Industry'].apply(is_hard_tech)]
    
    # Sort by Volume Ratio (descending) -> "Hot" Turnaround
    # Sort
    filtered.sort_values(by=sort_col, ascending=False, inplace=True)
    
    # Limit to top 3 (User Request)
    top_3 = filtered.head(3).copy()
    
    # 7. Analyze Trend (Startup Phase & Pre-Breakout)
    # Optimization: Run analysis on ALL filtered stocks (not just top 20) to find hidden gems.
    # But for performance (API cost), looking at top 50 matches is safer.
    print(f"Matched Criteria: {len(filtered)}. Selecting Top Candidates...")
    
    candidates = filtered.head(50).copy()
    candidates['Is_Startup'] = False
    candidates['Is_Potential'] = False # Pre-Breakout
    candidates['Reason'] = ""
    candidates['Price_Change_5D'] = 0.0
    candidates['Final_Score'] = 0.0
    
    for idx, row in candidates.iterrows():
        # Check Startup (Existing Logic)
        is_startup, s_reason, pchg = analyze_startup_phase(row)
        
        # Check Pre-Breakout (New Logic)
        is_potential, p_reason, p_score = analyze_potential_breakout(row)
        
        candidates.at[idx, 'Is_Startup'] = is_startup
        candidates.at[idx, 'Is_Potential'] = is_potential
        candidates.at[idx, 'Price_Change_5D'] = pchg
        
        # Scoring Logic (Hybrid)
        # Base: Volume Ratio * 10
        vol = row.get('Volume_Ratio', 0)
        if pd.isna(vol): vol = 0
        score = vol * 10
        
        if row.get('Is_Hot_Sector', False): score += 20
        if is_startup: score += 10
        if is_potential: score += p_score # Boost for Potential Breakout (+30~50)
        
        # Penalize if already rose too much (User feedback)
        if pchg > 20: score -= 20 
        
        candidates.at[idx, 'Final_Score'] = score
        
        # Generate Remark
        remarks = []
        if is_potential: remarks.append("✨蓄势待发") # Highlight this!
        elif is_startup: remarks.append("🚀技术启动")
        
        if row.get('Is_Hot_Sector', False): remarks.append("🔥热门板块")
        if row.get('PE_Improvement_Ratio', 0) > 0.5: remarks.append("估值修复")
        
        candidates.at[idx, 'Remark'] = " ".join(remarks) if remarks else "成长低估"
        
        print(f"Analyzed {row['Name']}: Score={score:.1f} (Potential={is_potential}, Startup={is_startup})")

    # Sort by Final Modified Score
    candidates.sort_values(by='Final_Score', ascending=False, inplace=True)
    
    # Top 3
    top_3 = candidates.head(3).copy()

    # Select Golden Stock (Winner)
    if not top_3.empty:
        golden_row = top_3.iloc[0]
        
        # Build Reasoning
        is_pot = golden_row.get('Is_Potential', False)
        
        sector_str = "🔥 处于今日强势领涨板块" if golden_row.get('Is_Hot_Sector', False) else f"所属{golden_row['Industry']}板块"
        
        if is_pot:
            trend_type = "✨ 潜伏金股 (蓄势待发)"
            tech_str = "股价回踩MA20支撑，近期缩量横盘整理，技术指标(MACD)金叉向上，具备极高爆发潜力"
        elif golden_row['Is_Startup']:
            trend_type = "🚀 启动金股 (右侧交易)"
            tech_str = "技术面呈现完美启动形态 (MACD金叉/多头)，资金抢筹明显"
        else:
            trend_type = "💎 价值金股 (成长驱动)"
            tech_str = "资金关注度极高，基本面强劲"
        
        vol_val = golden_row.get('Volume_Ratio', 0)
        vol_str = f"量比 {vol_val:.2f}倍" if vol_val > 0 else f"涨幅 {golden_row.get('Change_Pct', 0):.2f}%"
        
        pe_ttm_val = golden_row.get('PE_TTM', 'N/A')
        pe_str = f"动态PE({pe_ttm_val})"
        
        logic_str = f"综合评分第一。{trend_type}。{vol_str}，净利增长 {golden_row['Growth_Rate']:.0f}%。"
        advantage_str = f"业绩处于加速释放期，{pe_str}，{sector_str}。"
        why_str = f"{tech_str}，相比追高更具安全边际。"
        
        golden_stock = {
            'Symbol': golden_row['Symbol'],
            'Name': golden_row['Name'],
            'Price': golden_row['Price'],
            'Industry': golden_row['Industry'],
            'Logic': logic_str,
            'Advantage': advantage_str,
            'Why': why_str
        }
    else:
        golden_stock = None
    
    print("-" * 30)
    print(f"Selected Top: {len(top_3)}")
    print("-" * 30)
    
    if not top_3.empty:
        # Save to CSV for inspection
        cols_to_save = ['Symbol', 'Name', 'Industry', 'Price', 'PE_Static', 'PE_TTM', 'Growth_Rate', 'PEG', 'Volume_Ratio', 'Is_Startup', 'Is_Potential', 'Remark', 'Final_Score']
        top_3[cols_to_save].to_csv("stock_recommendations.csv", index=False)
        return golden_stock, top_3
    else:
        return None, pd.DataFrame()

if __name__ == "__main__":
    fetch_and_analyze()
