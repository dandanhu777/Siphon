import schedule
import time
import subprocess
import datetime
import sys
import os

# Set working directory to script location
os.chdir(os.path.dirname(os.path.abspath(__file__)))

def job():
    print(f"\n⏰ Triggering Siphon Strategy at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}...")
    try:
        # Run the strategy script
        result = subprocess.run([sys.executable, "-u", "siphon_strategy.py"], capture_output=True, text=True)
        print("--- Output ---")
        print(result.stdout)
        if result.stderr:
            print("--- Error ---")
            print(result.stderr)
        print("✅ Job Completed.")
    except Exception as e:
        print(f"❌ Job Execution Failed: {e}")

# Schedule task
schedule.every().day.at("16:00").do(job)

print("🚀 Siphon Scheduler Started (PID: {}).".format(os.getpid()))
print("📅 Schedule: Daily at 16:00 (4:00 PM).")
print("💤 Waiting for next trigger...")

# Keep running
while True:
    try:
        schedule.run_pending()
        time.sleep(60) # Check every minute
    except KeyboardInterrupt:
        print("\n🛑 Scheduler stopped by user.")
        break
    except Exception as e:
        print(f"⚠️ Scheduler Error: {e}")
        time.sleep(60)
