import akshare as ak
import pandas as pd
import datetime
import sys

def main():
    try:
        today = datetime.date.today()
        # Fetch trading calendar
        trade_dates_df = ak.tool_trade_date_hist_sina()
        trade_dates = pd.to_datetime(trade_dates_df['trade_date']).dt.date.tolist()
        
        if today in trade_dates:
            print(f"✅ {today} is a trading day.")
            sys.exit(0)
        else:
            print(f"⏸️ {today} is a non-trading day (Holiday/Weekend). Skipping...")
            sys.exit(1)
    except Exception as e:
        print(f"⚠️ Error checking trading day: {e}. Defaulting to run.")
        sys.exit(0)

if __name__ == "__main__":
    main()
