
import sqlite3
import requests
import time
import json

DB_PATH = "boomerang_tracker.db"
BACKEND_URL = "http://localhost:8000"

def get_db_connection():
    return sqlite3.connect(DB_PATH)

def check_backend():
    try:
        r = requests.get(f"{BACKEND_URL}/")
        return r.status_code == 200
    except:
        return False

def sync_data():
    if not check_backend():
        print("❌ Backend Service (localhost:8000) is NOT running.")
        print("   Please start it: `uvicorn backend.main:app --port 8000`")
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Select target records
    print("🔍 Scanning DB for missing data...")
    cursor.execute("""
        SELECT id, stock_code, stock_name, industry, core_logic 
        FROM recommendations 
        WHERE industry IS NULL OR industry = 'Unknown' OR core_logic IS NULL OR core_logic = '' OR length(core_logic) < 10
    """)
    rows = cursor.fetchall()
    print(f"Found {len(rows)} records to sync.")

    for r in rows:
        rid, code, name, ind, logic = r
        print(f"👉 Syncing {name} ({code})...")
        
        updates = {}
        
        # 1. Fetch Basic Info (Industry)
        if not ind or ind == 'Unknown':
            try:
                resp = requests.get(f"{BACKEND_URL}/stock/{code}")
                if resp.status_code == 200:
                    data = resp.json()
                    info = data.get('info', {})
                    new_ind = info.get('行业')
                    if new_ind:
                        updates['industry'] = new_ind
                        print(f"   MATCH Industry: {new_ind}")
            except Exception as e:
                print(f"   Info Error: {e}")
                
        # 2. Fetch AI Logic
        if not logic or len(logic) < 10: # If logic is just 'VolRatio...' (short)
            try:
                # Use AI Analysis endpoint
                # Note: This might cost tokens/time.
                print(f"   Asking Backend AI for {name}...")
                resp = requests.get(f"{BACKEND_URL}/stock/{code}/ai_analysis", timeout=60)
                if resp.status_code == 200:
                    data = resp.json()
                    ai_report = data.get('ai_report')
                    # ai_report is likely markdown text.
                    # We want a short summary or 'core logic'.
                    # Let's truncate or just save it.
                    # User table column is 'AI Core Logic'. 
                    # If text is long, table might break?
                    # Let's extract 'Summary' if possible, or first 50 chars?
                    # Backend llm_service output format: "**Rating**: ... **Summary**: ..."
                    if "**Summary**:" in ai_report:
                        summary = ai_report.split("**Summary**:")[1].strip()
                        updates['core_logic'] = summary[:100] # Limit length
                    else:
                        updates['core_logic'] = ai_report[:100]
                        
                    print(f"   MATCH Logic: {updates['core_logic'][:20]}...")
            except Exception as e:
                print(f"   AI Error: {e}")

        # Update DB
        if updates:
            set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
            values = list(updates.values()) + [rid]
            cursor.execute(f"UPDATE recommendations SET {set_clause} WHERE id = ?", values)
            conn.commit()
            print("   ✅ Validated & Updated.")
            
        time.sleep(1) # Be gentle

    conn.close()
    print("Sync Complete.")

if __name__ == "__main__":
    sync_data()
