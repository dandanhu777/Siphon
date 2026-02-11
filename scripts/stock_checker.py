import akshare as ak
import pandas as pd

def fetch_data():
    print("Fetching A-Share spot data...")
    # Fetch real-time data for A-shares
    stock_spot_df = ak.stock_zh_a_spot_em()
    
    # Rename columns for clarity (optional, but good for inspection)
    # The API usually returns Chinese column names or specific English keys.
    # We will print the columns to confirm.
    print("Columns:", stock_spot_df.columns)
    
    # Check if we have the necessary columns
    # We need: Symbol, Name, Price, Static PE, Dynamic PE/TTM
    # Usually: '代码', '名称', '最新价', '市盈率-动态', '市盈率-静态'
    
    print("First 5 rows:")
    print(stock_spot_df.head())
    
    return stock_spot_df

if __name__ == "__main__":
    df = fetch_data()
