import schedule
import time
import os
import subprocess
from datetime import datetime

def job():
    print(f"[{datetime.now()}] Starting daily stock recommendation job...")
    # Run the main.py script
    # Ensure we pass the current environment variables (including SMTP credentials)
    result = subprocess.run(["python3", "main.py"], cwd="/Users/ddhu/stock_recommendation", capture_output=True, text=True)
    print(result.stdout)
    if result.stderr:
        print("Errors:", result.stderr)
    print(f"[{datetime.now()}] Job finished.")

def run_scheduler():
    # Schedule everyday at 16:00 (Market close is 15:00, data should be ready)
    schedule_time = "16:00"
    print(f"Scheduler started. Job will run daily at {schedule_time}.")
    
    schedule.every().day.at(schedule_time).do(job)
    
    # Also run once immediately on start to confirm it works (User likely wants immediate feedback)
    # query = input("Run once now? (y/n): ")
    # if query.lower() == 'y':
    #     job()
    
    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    # Ensure schedule lib is installed
    # pip install schedule
    try:
        import schedule
    except ImportError:
        print("Installing 'schedule' library...")
        subprocess.run(["pip", "install", "schedule"])
        import schedule

    run_scheduler()
