import akshare as ak
import pandas as pd
import os
import datetime
import json

# Cache for multiple indices
INDEX_CACHE_FILE = "index_multi_cache.json"

# Mapping Logic
# 000001 (SH) -> SSEC
# 399001 (SZ) -> SZI
# 000688 (SH) -> STAR50
# 399006 (SZ) -> ChiNext
TARGET_INDICES = {
    "sh000001": "000001",
    "sz399001": "399001",
    "sh000688": "000688",
    "sz399006": "399006"
}

def get_index_code_for_stock(stock_code):
    """Determine benchmark index based on stock prefix."""
    code = str(stock_code).zfill(6)
    if code.startswith('688'): return "sh000688" # STAR
    if code.startswith('300') or code.startswith('301'): return "sz399006" # ChiNext
    if code.startswith('6'): return "sh000001" # SH Main
    if code.startswith('0') or code.startswith('3'): return "sz399001" # SZ Main
    return "sh000001" # Default

def update_index_cache():
    """Fetch all target indices."""
    print(f"🔄 Fetching Multi-Index Data...")
    
    cache = {}
    if os.path.exists(INDEX_CACHE_FILE):
        try:
           with open(INDEX_CACHE_FILE, 'r') as f: cache = json.load(f)
        except: pass
        
    for key, symbol in TARGET_INDICES.items():
        print(f"   - Updating {key} ({symbol})...")
        try:
            # Try EM first
            df = ak.stock_zh_index_daily_em(symbol=symbol)
            if df.empty:
                # Try Sina
                df = ak.stock_zh_index_daily(symbol=key)
                
            if not df.empty:
                df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
                # Store as date->close map
                data_map = dict(zip(df['date'], df['close']))
                cache[key] = {
                    "updated": datetime.datetime.now().strftime("%Y-%m-%d"),
                    "data": data_map
                }
                print(f"     ✅ Success ({len(df)} rows)")
        except Exception as e:
            print(f"     ❌ Failed {key}: {e}")
            
    with open(INDEX_CACHE_FILE, 'w') as f:
        json.dump(cache, f)

def get_benchmark_return(start_date_str, stock_code=None):
    """
    Calculate return of the APPROPRIATE index.
    """
    # Determine Index Code
    idx_key = get_index_code_for_stock(stock_code) if stock_code else "sh000001"
    
    # Load Cache
    if not os.path.exists(INDEX_CACHE_FILE): update_index_cache()
    
    try:
        with open(INDEX_CACHE_FILE, 'r') as f: cache = json.load(f)
    except: return None
    
    # Check staleness
    idx_data = cache.get(idx_key, {})
    last_update = idx_data.get("updated", "2000-01-01")
    if last_update != datetime.datetime.now().strftime("%Y-%m-%d"):
        # Lazy update if today's data missing? 
        # Actually daily update is fine.
        # If huge gap, maybe update.
        pass
        
    data_map = idx_data.get("data", {})
    if not data_map: return None
    
    dates = sorted(data_map.keys())
    current_val = list(data_map.values())[-1] # Latest available
    
    # Default to T+0 change if start_date is today
    # But usually start_date is Rec Date.
    
    base_val = None
    if start_date_str in dates:
        idx = dates.index(start_date_str)
        if idx > 0: base_val = data_map[dates[idx-1]]
        else: base_val = data_map[dates[0]]
    else:
        # Fallback to nearest past date
        for d in reversed(dates):
            if d < start_date_str:
                base_val = data_map[d]
                break
                
    if base_val and current_val:
        return ((current_val - base_val) / base_val) * 100
        
    return None
