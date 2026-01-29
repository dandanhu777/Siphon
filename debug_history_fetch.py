
import akshare as ak
import pandas as pd
import datetime

def debug_fetch(symbol):
    print(f"--- Debugging {symbol} ---")
    end_date = datetime.datetime.now().strftime("%Y%m%d")
    start_date = (datetime.datetime.now() - datetime.timedelta(days=60)).strftime("%Y%m%d")
    
    if symbol.startswith('6'): prefix = 'sh'
    elif symbol.startswith('0') or symbol.startswith('3'): prefix = 'sz'
    else: prefix = ''
    
    full = f"{prefix}{symbol}"
    print(f"Fetching {full}...")
    
    try:
        df = ak.stock_zh_a_daily(symbol=full, start_date=start_date, end_date=end_date)
        if df is None: print("Returns None"); return
        if df.empty: print("Returns Empty DF"); return
        
        print(f"Columns: {df.columns.tolist()}")
        print(f"Index: {df.index.name}")
        print(df.head(2).to_string())
        
        if 'date' in df.columns: print("✅ Has 'date' column")
        elif '日期' in df.columns: print("✅ Has '日期' column")
        else: print("❌ Missing date column")
        
    except Exception as e:
        print(f"❌ Error: {e}")

debug_fetch("600519") # Moutai
debug_fetch("002487") # Dajin
