
import sqlite3
import akshare as ak
import time
import random

DB_PATH = "boomerang_tracker.db"

def get_db_connection():
    return sqlite3.connect(DB_PATH)

def fetch_industry_akshare(code):
    # Method 1: Eastmoney
    try:
        df = ak.stock_individual_info_em(symbol=code)
        info = dict(zip(df['item'], df['value']))
        if info.get('行业'): return info.get('行业')
    except:
        pass

    # Method 2: CNINFO (Juchao)
    try:
        # stock_profile_cninfo returns a df with 'org_name_cn', 'primary_business'
        # It doesn't strictly have 'industry' but 'primary_business' (主营业务) is even better for logic!
        # But for 'industry' column we can infer or just use 'Unknown' but return 'primary_business' for logic?
        # Let's try to get something.
        # Check stock_industry_pe_ratio_cninfo? No.
        pass
    except:
        pass
        
    # Method 3: THS (Tonghuashun)
    try:
        # stock_a_code_to_symbol to get ths format?
        pass 
    except:
        pass
        
    return None

def fetch_business_akshare(code):
    # Helper to get business description if Industry fails
    try:
        # CNINFO Profile often has full text
        pass
    except:
        pass
    return None
    
# ... actually let's implement the specific calls
def fetch_info_robust(code):
    print(f"   [Debug] Fetching info for {code}...")
    
    # 1. Try CNINFO (Most detailed and seems working)
    try:
        df = ak.stock_profile_cninfo(symbol=code)
        if not df.empty:
            row = df.iloc[0]
            ind = row.get('所属行业')
            bus = row.get('主营业务')
            
            # CNINFO often returns '制造业' generic, but '主营业务' is specific.
            # If industry is missing or generic, we might rely on business text.
            logic = f"{bus}" if bus else None
            return ind, logic
    except Exception as e:
        print(f"    - CNINFO Failed: {e}")

    # 2. Try EM (Fallback, flaky)
    try:
        df = ak.stock_individual_info_em(symbol=code)
        info = dict(zip(df['item'], df['value']))
        ind = info.get('行业')
        if ind: 
            return ind, f"属于 {ind} 行业"
    except Exception as e:
        print(f"    - EM Failed: {e}")

    return None, None

def repair_data():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    print("🔍 Scanning DB for missing data...")
    # Select records where Industry is missing/Unknown OR Logic is missing/technical-only
    cursor.execute("""
        SELECT id, stock_code, stock_name, industry, core_logic 
        FROM recommendations 
        WHERE industry IS NULL OR industry = 'Unknown' OR core_logic IS NULL OR core_logic = '' OR core_logic LIKE 'VolRatio%'
    """)
    rows = cursor.fetchall()
    print(f"Found {len(rows)} records to repair.")

    for r in rows:
        rid, code, name, ind, logic = r
        print(f"👉 Repairing {name} ({code})...")
        
        new_ind, new_logic = fetch_info_robust(code)
        
        updates = {}
        if new_ind and (not ind or ind == 'Unknown'):
            updates['industry'] = new_ind
            print(f"   ✅ Industry: {new_ind}")
            
        if new_logic and (not logic or logic.startswith('VolRatio')):
            # If we have existing Technical Logic, PREPEND the Business Logic
            if logic and logic.startswith('VolRatio'):
                updates['core_logic'] = f"{new_logic[:50]}... | {logic}"
            else:
                updates['core_logic'] = new_logic[:100] # Trim excessive length
            print(f"   ✅ Logic: {updates['core_logic'][:50]}...")
            
        if updates:
            set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
            values = list(updates.values()) + [rid]
            cursor.execute(f"UPDATE recommendations SET {set_clause} WHERE id = ?", values)
            conn.commit()
            
        time.sleep(1.0) # Rate limit logic

if __name__ == "__main__":
    repair_data()
