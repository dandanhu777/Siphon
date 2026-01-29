
import akshare as ak
import pandas as pd
import time

def test_source(name, func):
    print(f"\n--- Testing {name} ---")
    try:
        start = time.time()
        df = func()
        elapsed = time.time() - start
        if df is not None and not df.empty:
            print(f"✅ Success! Rows: {len(df)}, Time: {elapsed:.2f}s")
            print(df.head(1).to_string())
            return True
        else:
            print("❌ Empty result")
            return False
    except Exception as e:
        print(f"❌ Failed: {e}")
        return False

# 1. Primary (Eastmoney Spot)
test_source("Eastmoney Spot", ak.stock_zh_a_spot_em)

# 2. Sina Spot (older interface)
try:
    test_source("Sina Spot", ak.stock_zh_a_spot)
except AttributeError:
    print("❌ ak.stock_zh_a_spot does not exist/deprecated")

# 3. Realtime Quote (Sina) - requires explicit list usually, checking if there is a 'get all'
# There isn't a direct 'get all' for Sina generally without iterating.

# 4. Check for Cache
import os
import pickle
CACHE_PATH = "data_cache/siphon_fetch_basic_pool_.pkl"
if os.path.exists(CACHE_PATH):
    print(f"\n--- Checking Cache ({CACHE_PATH}) ---")
    mtime = os.path.getmtime(CACHE_PATH)
    age = (time.time() - mtime) / 3600
    print(f"Cache Age: {age:.2f} hours")
    try:
        with open(CACHE_PATH, 'rb') as f:
            data = pickle.load(f)
            print(f"✅ Cache Loadable. Rows: {len(data)}")
    except Exception as e:
        print(f"❌ Cache Corrupt: {e}")
else:
    print("\n❌ No Cache Found")
