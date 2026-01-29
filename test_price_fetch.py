import akshare as ak
import pandas as pd
import datetime

targets = [
    ("002594", "2026-01-27"), # BYD (T+2)
    ("601899", "2026-01-26"), # Zijin (T+3)
    ("600519", "2026-01-27")  # Moutai
]

print("Testing Price Fetch...")
for code, date_str in targets:
    print(f"\nTarget: {code} @ {date_str}")
    
    # Range: Date-10 to Date
    dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
    start_dt = dt - datetime.timedelta(days=10)
    s_str = start_dt.strftime("%Y%m%d")
    e_str = dt.strftime("%Y%m%d")
    
    print(f"   Searching Range: {s_str} -> {e_str}")
    
    try:
        # Try Sina (needs prefix)
        prefix = "sz" if code.startswith("0") or code.startswith("3") else "sh"
        long_code = prefix + code
        print(f"   Trying Sina: {long_code}")
        df = ak.stock_zh_a_daily(symbol=long_code, start_date=s_str, end_date=e_str, adjust="qfq")
        if not df.empty:
            last_row = df.iloc[-1]
            print(f"   ✅ Sina Found: Date={last_row['date']} Close={last_row['close']}")
        else:
            print("   ❌ Sina Empty Result")
    except Exception as e:
        print(f"   ❌ Sina Exception: {e}")
