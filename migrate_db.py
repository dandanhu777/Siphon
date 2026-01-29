import sqlite3

DB_PATH = "boomerang_tracker.db"

def migrate():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # Check if column exists
        cursor.execute("PRAGMA table_info(recommendations)")
        columns = [info[1] for info in cursor.fetchall()]
        
        if 'siphon_score' not in columns:
            print("Migrating: Adding siphon_score column...")
            cursor.execute("ALTER TABLE recommendations ADD COLUMN siphon_score REAL DEFAULT 3.0")
            conn.commit()
            print("✅ Migration successful: siphon_score added.")
        else:
            print("ℹ️ Column siphon_score already exists.")
            
    except Exception as e:
        print(f"❌ Migration failed: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
