"""Download 5min klines for 创业板 (300xxx) and 科创板 (688xxx) stocks via BaoStock."""
import baostock as bs
import pandas as pd
import os, glob, sys, time

DATA_DIR = r"C:\QuantTrade\data"
OUT_DIR = os.path.join(DATA_DIR, "klines_5min")
DAILY_DIR = os.path.join(DATA_DIR, "klines")

# Get list of stocks that have daily data but no 5min data
daily_files = glob.glob(os.path.join(DAILY_DIR, "*.parquet"))
existing_5min = set(os.path.basename(f).split('.')[0] for f in glob.glob(os.path.join(OUT_DIR, "*.parquet")))

missing = []
for f in daily_files:
    sym = os.path.basename(f).split('.')[0]
    if sym not in existing_5min and (sym.startswith('300') or sym.startswith('688')):
        missing.append(sym)

print(f"Total missing 5min: {len(missing)} (300xxx + 688xxx)")
if not missing:
    print("Nothing to download!"); sys.exit(0)

lg = bs.login()
print(f"BaoStock login: {lg.error_code} {lg.error_msg}")

downloaded = 0
errors = 0
for i, sym in enumerate(missing):
    # BaoStock format: sz.300001 or sh.688001
    prefix = "sz" if sym.startswith('300') else "sh"
    bs_code = f"{prefix}.{sym}"
    
    try:
        rs = bs.query_history_k_data_plus(bs_code,
            "date,time,code,open,high,low,close,volume,amount",
            start_date="2024-06-01", end_date="2025-12-31",
            frequency="5", adjustflag="2")
        
        rows = []
        while rs.error_code == '0' and rs.next():
            rows.append(rs.get_row_data())
        
        if rows:
            df = pd.DataFrame(rows, columns=rs.fields)
            out_path = os.path.join(OUT_DIR, f"{sym}.parquet")
            df.to_parquet(out_path, index=False)
            downloaded += 1
            if downloaded % 50 == 0:
                print(f"  [{downloaded}/{len(missing)}] Downloaded {sym} ({len(df)} bars)")
        else:
            errors += 1
            
    except Exception as e:
        errors += 1
        if errors < 5: print(f"  ERROR {sym}: {e}")
    
    # Rate limiting
    if i % 100 == 99:
        print(f"  Progress: {i+1}/{len(missing)} | OK={downloaded} ERR={errors}")
        time.sleep(2)

bs.logout()
print(f"\nDone! Downloaded={downloaded} Errors={errors}")
