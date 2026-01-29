from stock_recommendation import fetch_and_analyze
from email_notifier import EmailNotifier
import sys

def run_workflow():
    print("=== Starting Stock Recommendation System ===")
    
    # 1. Fetch and Analyze
    golden_stock, df = fetch_and_analyze()
    
    # 2. Notify
    if df is not None and not df.empty:
        print(f"Preparing to send email for {len(df)} stocks...")
        
        # Receivers List
        # Production: ["28595591@qq.com", "89299772@qq.com", "milsica@gmail.com", "tosinx@gmail.com"]
        receivers = ["tosinx@gmail.com"] # Testing Mode
        
        notifier = EmailNotifier()
        notifier.send_recommendation_report(receivers, golden_stock, df)
    else:
        print("No stocks found, skipping email.")

    print("=== Workflow Completed ===")

if __name__ == "__main__":
    run_workflow()
