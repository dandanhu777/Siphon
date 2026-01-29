import akshare as ak
import pandas as pd
import datetime

# Test Stock: 688728 (GeKeWei) - From user screenshot
CODE = "688728"
INDEX = "sh000001"

print(f"=== Debugging Tracking Data for {CODE} ===")

# 1. Test History Interface (Current implementation)
try:
    print("\n[Test 1] ak.stock_zh_a_hist (Daily History)")
    start = (datetime.datetime.now() - datetime.timedelta(days=5)).strftime("%Y%m%d")
    end = datetime.datetime.now().strftime("%Y%m%d")
    df_hist = ak.stock_zh_a_hist(symbol=CODE, period="daily", start_date=start, end_date=end, adjust="qfq")
    print(df_hist.tail(2))
except Exception as e:
    print(f"Error: {e}")

# 2. Test Spot Interface (Alternative)
try:
    print("\n[Test 2] ak.stock_zh_a_spot_em (Real-time Spot)")
    df_spot = ak.stock_zh_a_spot_em()
    row = df_spot[df_spot['代码'] == CODE]
    print(row)
except Exception as e:
    print(f"Error: {e}")

# 3. Test Index Interface
try:
    print(f"\n[Test 3] Index Spot ({INDEX})")
    # Try getting index spot
    df_index = ak.stock_zh_index_spot() 
    row_idx = df_index[df_index['代码'] == INDEX]
    print(row_idx)
except Exception as e:
    print(f"Error: {e}")
