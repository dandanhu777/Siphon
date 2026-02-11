
import sqlite3
import pandas as pd
import time
from gemini_enricher import enrich_top_picks

DB_PATH = "boomerang_tracker.db"

def get_db_connection():
    return sqlite3.connect(DB_PATH)

def restore_history():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Select records needing update
    # Logic: Core Logic is missing OR Industry is Unknown OR US Bench (we don't store US bench in DB? Wait.)
    # The DB schema has: core_logic, industry.
    # US Bench is NOT in DB schema? 
    # Checking schema check output from earlier (Step 4275):
    # CREATE TABLE recommendations (... industry TEXT, core_logic TEXT);
    # No us_bench column.
    # So US Bench is transient?
    # In fallback_email_sender.py: `enrich.get("us_bench")` is used for "Top Picks".
    # For "History", the columns are: 标的/行业, Score, AI 核心逻辑, ...
    # History table does NOT show US Benchmark. (Check HTML builder).
    # Line 214 (Rec Table): Shows "美股对标".
    # Line 252 (Track Table): "标的/行业", "Score", "AI 核心逻辑", "持有", "Price", "收益", "大盘".
    # Correct. History table DOES NOT show US Benchmark.
    # So we only need to backfill `industry` and `core_logic`.
    
    print("🔍 Scanning for records needing enrichment...")
    cursor.execute("""
        SELECT id, stock_code, stock_name, strategy_tag, core_logic, industry 
        FROM recommendations 
        WHERE core_logic IS NULL OR core_logic = '' OR industry IS NULL OR industry = 'Unknown'
    """)
    rows = cursor.fetchall()
    
    if not rows:
        print("✅ No records need restoration.")
        return

    print(f"found {len(rows)} records to restore.")
    
    # Process in batches
    batch_size = 5
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i+batch_size]
        print(f"Processing batch {i//batch_size + 1}/{len(rows)//batch_size + 1}...")
        
        # Prepare for enrichment
        enrich_input = []
        for r in batch:
            rid, code, name, strategy, logic, ind = r
            enrich_input.append({'name': name, 'code': code})
            
        # Call AI
        try:
            print(f"   Asking AI to enrich {len(enrich_input)} items...")
            results = enrich_top_picks(enrich_input)
            
            # Update DB
            updates = []
            for r in batch:
                rid, code, name, strategy, logic, ind = r
                
                # Get Result
                res = results.get(code, {})
                new_logic = res.get('business') # Use 'business' as core logic description?
                new_ind = "Unknown" # Enrichment doesn't give industry category explicitly? (It gives 'business').
                # Wait, gemini_enricher prompt asks for: business, us_bench, target_price.
                # It does NOT ask for Industry Category (Sector).
                # But 'business' ("功率半导体IDM龙头...") is good for 'AI Core Logic'.
                
                # If 'core_logic' in DB is meant to be the 'reason', 'business' description fits well.
                # Strategy Tag is the 'Strategy' (e.g. VCP).
                # User report column says "AI 核心逻辑".
                # In Top Picks it shows "business" (Line 234).
                # So yes, we should map 'business' -> 'core_logic' in DB.
                
                # What about Industry?
                # The enricher doesn't return Industry check result.
                # But maybe we can guess or leave as Unknown? 
                # Or use existing unknown if not found.
                
                if new_logic:
                    # Update
                    # If existing logic was just strategy tag, overwrite/append?
                    # Let's overwrite if it was empty or seemed default.
                    final_logic = new_logic
                    updates.append((final_logic, rid))
                    print(f"   MATCH: {name} -> {final_logic[:10]}...")
            
            if updates:
                cursor.executemany("UPDATE recommendations SET core_logic = ? WHERE id = ?", updates)
                conn.commit()
                print(f"   Saved {len(updates)} updates.")
                
            time.sleep(2) # Rate limit friendly
            
        except Exception as e:
            print(f"   Error doing batch: {e}")
            
    conn.close()
    print("Restore Complete.")

if __name__ == "__main__":
    restore_history()
