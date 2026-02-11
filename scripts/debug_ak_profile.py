
import akshare as ak
import pandas as pd

def check_profile(code):
    print(f"--- Checking {code} ---")
    try:
        # Attempt 1: Eastmoney Individual Info (often has Industry)
        df = ak.stock_individual_info_em(symbol=code)
        info = dict(zip(df['item'], df['value']))
        print(f"EM Industry: {info.get('行业')}")
        print(f"EM Total Market Cap: {info.get('总市值')}")
    except Exception as e:
        print(f"EM Info Failed: {e}")

    try:
        # Attempt 2: CNINFO Profile (Business content)
        print("Fetching CNINFO Profile...")
        df = ak.stock_profile_cninfo(symbol=code)
        print(f"CNINFO Shape: {df.shape}")
        print(f"CNINFO Columns: {df.columns.tolist()}")
        # if not df.empty:
        #     print(f"CNINFO Business: {df.iloc[0]['primary_business']}")
    except Exception as e:
        print(f"CNINFO Failed: {e}")

if __name__ == "__main__":
    check_profile("603370") # 华新精科
    check_profile("600519") # 茅台
