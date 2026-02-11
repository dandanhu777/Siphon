
import sqlite3
import pandas as pd
import akshare as ak
import time
import random

DB_PATH = "boomerang_tracker.db"

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    return conn

def add_column_if_missing(cursor, table, column, dtype):
    cursor.execute(f"PRAGMA table_info({table})")
    cols = [info[1] for info in cursor.fetchall()]
    if column not in cols:
        print(f"Adding column {column} to {table}...")
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {dtype}")
        return True
    return False

def fetch_industry_map():
    print("Fetching Industry Map...")
    try:
        df = ak.stock_board_industry_name_em()
        # This returns board names. We need stock-to-industry.
        # Better use stock_zh_a_spot_em or similar, or just fetch individual if needed.
        # Actually, let's use the 'siphon_strategy.py' logic: fetch_basic_pool gives industry.
        # But importing that might be complex due to dependencies.
        # Let's try to fetch basic info for all stocks first.
        
        # Spot EM
        spot = ak.stock_zh_a_spot_em()
        # Spot EM usually has no industry.
        # Profile EM?
        # Let's look at what we used in siphon_strategy: ak.stock_yjbb_em (Quarterly Report) has industry!
        growth = ak.stock_yjbb_em(date="20250930")
        if growth.empty: growth = ak.stock_yjbb_em(date="20241231")
        
        if '所处行业' in growth.columns:
            return dict(zip(growth['股票代码'], growth['所处行业']))
        return {}
    except Exception as e:
        print(f"Error fetching industry map: {e}")
        return {}

def backfill():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Schema Update
    add_column_if_missing(cursor, "recommendations", "core_logic", "TEXT")
    add_column_if_missing(cursor, "recommendations", "industry", "TEXT") # Ensure it exists
    conn.commit()
    
    # 2. Fetch Data Need Backfill
    cursor.execute("SELECT id, stock_code, stock_name, strategy_tag FROM recommendations WHERE industry IS NULL OR industry = '' OR core_logic IS NULL")
    rows = cursor.fetchall()
    print(f"Found {len(rows)} records to backfill.")
    
    if not rows:
        return

    # 3. Prepare Industry Map
    ind_map = fetch_industry_map()
    print(f"Loaded Industry Map: {len(ind_map)} entries.")
    
    updates = []
    
    for r in rows:
        rid, code, name, strategy = r
        
        # Industry
        ind = ind_map.get(code, "Unknown")
        if ind == "Unknown":
            # Try fuzzy match? Or just leave as Unknown for now.
            pass
            
        # Core Logic
        # Default to strategy_tag if empty.
        # If strategy_tag is something like "VolRatio:2.0x, VCP", that IS the core logic.
        logic = strategy if strategy else "Siphon Pattern"
        
        updates.append((ind, logic, rid))
        
    # 4. Update
    print("Updating records...")
    cursor.executemany("UPDATE recommendations SET industry = ?, core_logic = ? WHERE id = ?", updates)
    conn.commit()
    conn.close()
    print("Backfill Complete.")

if __name__ == "__main__":
    backfill()
