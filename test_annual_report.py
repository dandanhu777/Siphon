import akshare as ak
import pandas as pd

def check_annual_report():
    print("Fetching Annual Report (2024)...")
    try:
        # 2024 Annual Report -> 20241231
        df = ak.stock_yjbb_em(date="20241231")
        print("Columns:", df.columns)
        print(df.head())
        
        if '每股收益' in df.columns:
            print("Found EPS column!")
        else:
            print("EPS column NOT found.")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_annual_report()
