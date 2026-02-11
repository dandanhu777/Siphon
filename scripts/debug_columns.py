import akshare as ak
import pandas as pd

try:
    print("Fetching spot data...")
    df = ak.stock_zh_a_spot_em()
    print("Columns found:", df.columns.tolist())
except Exception as e:
    print(e)
