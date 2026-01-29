import akshare as ak
import pandas as pd
import datetime

print("Testing Index Fetch for sh000300...")

try:
    # 1. Daily History
    print("\n[1] Daily History:")
    df = ak.stock_zh_index_daily(symbol="sh000300")
    if not df.empty:
        print(f"Rows: {len(df)}")
        print(df.tail(3))
    else:
        print("Daily History Empty!")

    # 2. Daily Spot (if available) - usually for A-share individual, index might be different
    print("\n[2] Index Spot:")
    try:
        spot = ak.stock_zh_index_spot_sina() # Trying sina specific
        row = spot[spot['代码'] == 'sh000300'] # or 000300
        if not row.empty:
            print(row)
        else:
            print("sh000300 not found in spot list")
            # Try 000300
            row = spot[spot['代码'] == '000300']
            print(f"000300 check: {row}")
    except Exception as e:
        print(f"Spot fetch error: {e}")

except Exception as e:
    print(f"Global Error: {e}")
