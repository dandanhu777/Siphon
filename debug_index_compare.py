import akshare as ak
import pandas as pd

indices = {
    "CSI300 (sh000300)": "sh000300",
    "SSEC (sh000001)": "sh000001",
    "Shenzhen (sz399001)": "sz399001"
}

print("Comparing Index Performance (Last 5 Days)...")

for name, code in indices.items():
    print(f"\n--- {name} ---")
    try:
        df = ak.stock_zh_index_daily(symbol=code)
        if not df.empty:
            df = df.sort_values('date').tail(5)
            # Calculate daily change
            df['pct_chg'] = df['close'].pct_change() * 100
            print(df[['date', 'close', 'pct_chg']])
        else:
            print("Empty DataFrame")
    except Exception as e:
        print(f"Error: {e}")
