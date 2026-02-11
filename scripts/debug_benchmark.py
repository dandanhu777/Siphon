import akshare as ak
import pandas as pd
import datetime

INDEX_CODE = "sh000300"

print(f"Fetching History for {INDEX_CODE}...")
df = ak.stock_zh_index_daily(symbol=INDEX_CODE)
df['date'] = pd.to_datetime(df['date'])
df = df.sort_values('date').tail(5)

print("\nRecent Index Data:")
print(df)

# Simulate Logic
print("\n--- Simulation ---")
dates = df['date'].dt.strftime('%Y-%m-%d').tolist()
closes = df['close'].tolist()
idx_map = dict(zip(dates, closes))

# Case 1: Rec Date = Today (Jan 22), Current = Jan 22
rec_date = dates[-1] # Jan 22
curr_date = dates[-1]

# My previous flawed logic:
base_wrong = idx_map.get(rec_date)
curr_val = idx_map.get(curr_date)
ret_wrong = (curr_val - base_wrong) / base_wrong * 100
print(f"Case T+0 (Wrong): Rec={rec_date}, Base={base_wrong}, Curr={curr_val} -> Ret={ret_wrong:.2f}%")

# Correct Logic: Base should be Prev Day (Jan 21)
prev_date = dates[-2] # Jan 21
base_correct = idx_map.get(prev_date)
ret_correct = (curr_val - base_correct) / base_correct * 100
print(f"Case T+0 (Correct): Rec={rec_date}, Base(Prev)={base_correct}, Curr={curr_val} -> Ret={ret_correct:.2f}%")

# Case 2: Rec Date = Yesterday (Jan 21), Current = Jan 22 (T+1)
rec_date_t1 = dates[-2]
# If I use Jan 21 Close as base:
base_t1 = idx_map.get(rec_date_t1)
ret_t1 = (curr_val - base_t1) / base_t1 * 100
print(f"Case T+1 (Base=RecClose): Rec={rec_date_t1}, Base={base_t1}, Curr={curr_val} -> Ret={ret_t1:.2f}%")
# Note: This is essentially today's % change if T+1 is just 1 day holding.
