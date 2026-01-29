import akshare as ak
import pandas as pd

def check_growth_data():
    print("Fetching Performance Report (2025 Q3)...")
    try:
        # Fetching for 2025 Q3 (2025-09-30)
        # This returns a large table with growth rates for available stocks
        df = ak.stock_yjbb_em(date="20250930")
        print("Columns:", df.columns)
        print(df.head())
        
        # Check for growth rate column
        # Usually: 净利润-同比增长 means Net Profit Growth Rate (YOY)
        if '净利润-同比增长' in df.columns:
            print("Found Growth Rate column!")
        else:
            print("Growth Rate column NOT found.")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_growth_data()
