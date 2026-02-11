"""
Project Boomerang - Recommendation Tracking System
Core tracking engine and database management
"""

import sqlite3
import datetime
import pandas as pd
from typing import Optional, Dict, List
import os
import akshare as ak
import pickle
import time

# Database path
DB_PATH = "boomerang_tracker.db"

def fetch_index_data(symbol="sh000001", days=60):
    """Fetch market index data (Shanghai Composite)"""
    cache_file = f"data_cache/index_{symbol}.pkl"
    
    # Try cache first (valid for 4 hours)
    if os.path.exists(cache_file):
        mtime = os.path.getmtime(cache_file)
        if (time.time() - mtime) < (4 * 3600):
            try:
                with open(cache_file, 'rb') as f:
                    return pickle.load(f)
            except: pass
            
    # Fetch fresh data
    try:
        # Stock index daily data
        df = ak.stock_zh_index_daily(symbol=symbol)
        df['date'] = pd.to_datetime(df['date']).dt.date
        df = df.sort_values('date')
        df = df.set_index('date')
        
        # Cache it
        if not os.path.exists("data_cache"):
            os.makedirs("data_cache")
        with open(cache_file, 'wb') as f:
            pickle.dump(df, f)
            
        return df
    except Exception as e:
        print(f"Error fetching index data: {e}")
        return pd.DataFrame()

def attach_market_performance(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate and attach market index performance to recommendations"""
    if df.empty:
        df['index_return'] = 0.0
        return df
        
    index_df = fetch_index_data()
    if index_df.empty:
        df['index_return'] = 0.0
        return df
    
    index_returns = []
    
    for _, row in df.iterrows():
        try:
            rec_date = datetime.datetime.strptime(row['rec_date'], '%Y-%m-%d').date()
            
            # Find closest index price for rec_date
            if rec_date in index_df.index:
                start_idx = index_df.loc[rec_date]['close']
            else:
                # Fallback to nearest previous trading day
                prev_days = index_df.index[index_df.index < rec_date]
                if not prev_days.empty:
                    start_idx = index_df.loc[prev_days[-1]]['close']
                else:
                    index_returns.append(0.0)
                    continue

            # Use the latest index price available as current benchmark
            end_idx = index_df.iloc[-1]['close']
            
            # Calculate return
            idx_ret = (end_idx - start_idx) / start_idx * 100
            index_returns.append(idx_ret)
            
        except Exception as e:
            index_returns.append(0.0)
            
    df['index_return'] = index_returns
    return df

def init_database():
    """Initialize the tracking database with required tables"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Recommendations table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS recommendations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code TEXT NOT NULL,
            stock_name TEXT NOT NULL,
            rec_date DATE NOT NULL,
            rec_price REAL NOT NULL,
            strategy_tag TEXT,
            status TEXT DEFAULT 'Active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Daily performance tracking table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_performance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rec_id INTEGER NOT NULL,
            trade_date DATE NOT NULL,
            close_price REAL NOT NULL,
            daily_change_pct REAL,
            cumulative_return REAL,
            max_drawdown REAL,
            max_high REAL,
            relative_strength REAL,
            FOREIGN KEY (rec_id) REFERENCES recommendations(id),
            UNIQUE(rec_id, trade_date)
        )
    """)
    
    conn.commit()
    conn.close()
    print("✅ Boomerang database initialized")

def add_recommendation(stock_code: str, stock_name: str, rec_price: float, strategy_tag: str = "", siphon_score: float = 3.0, custom_date: datetime.date = None, industry: str = "") -> int:
    """
    Add a new recommendation to tracking
    Returns: recommendation ID
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    rec_date = custom_date if custom_date else datetime.date.today()
    
    # Check if already tracked today to prevent duplicates (fix for multiple runs)
    cursor.execute("""
        SELECT id FROM recommendations 
        WHERE stock_code = ? AND rec_date = ?
    """, (stock_code, rec_date))
    existing = cursor.fetchone()
    
    if existing:
        # v4.3 Fix: Update score even if already exists (for re-runs)
        rec_id = existing[0]
        cursor.execute("""
            UPDATE recommendations 
            SET siphon_score = ?, rec_price = ?, strategy_tag = ?, industry = ?
            WHERE id = ?
        """, (siphon_score, rec_price, strategy_tag, industry, rec_id))
        conn.commit()
        conn.close()
        print(f"🔄 Updated Tracking: {stock_name} ({stock_code}) | Score: {siphon_score}")
        return rec_id
    
    cursor.execute("""
        INSERT INTO recommendations (stock_code, stock_name, rec_date, rec_price, strategy_tag, status, siphon_score, industry)
        VALUES (?, ?, ?, ?, ?, 'Active', ?, ?)
    """, (stock_code, stock_name, rec_date, rec_price, strategy_tag, siphon_score, industry))
    
    rec_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    print(f"📊 Tracking: {stock_name} ({stock_code}) @ ¥{rec_price:.2f} | Tag: {strategy_tag} | Score: {siphon_score}")
    return rec_id

def update_daily_performance(stock_data_fetcher):
    """
    Update daily performance for all active recommendations
    stock_data_fetcher: function that takes stock_code and returns current price data
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Get all active recommendations
    cursor.execute("""
        SELECT id, stock_code, stock_name, rec_date, rec_price 
        FROM recommendations 
        WHERE status = 'Active'
    """)
    
    active_recs = cursor.fetchall()
    today = datetime.date.today()
    
    for rec_id, stock_code, stock_name, rec_date_str, rec_price in active_recs:
        rec_date = datetime.datetime.strptime(rec_date_str, '%Y-%m-%d').date()
        days_tracked = (today - rec_date).days
        
        # Auto-close after 10 trading days (roughly 14 calendar days)
        if days_tracked > 14:
            cursor.execute("UPDATE recommendations SET status = 'Closed' WHERE id = ?", (rec_id,))
            print(f"🔒 Closed tracking: {stock_name} (T+{days_tracked})")
            continue
        
        # Fetch current price
        try:
            current_data = stock_data_fetcher(stock_code)
            if not current_data:
                continue
                
            close_price = current_data['close']
            daily_change_pct = current_data.get('change_pct', 0)
            
            # Calculate cumulative return
            cumulative_return = (close_price - rec_price) / rec_price * 100
            
            # Get historical max/min for this recommendation
            cursor.execute("""
                SELECT MAX(close_price), MIN(close_price) 
                FROM daily_performance 
                WHERE rec_id = ?
            """, (rec_id,))
            
            hist_max, hist_min = cursor.fetchone()
            max_high = max(close_price, hist_max or close_price)
            min_low = min(close_price, hist_min or close_price)
            
            # Calculate max drawdown from recommendation price
            max_drawdown = (min_low - rec_price) / rec_price * 100
            
            # Insert/update daily performance
            cursor.execute("""
                INSERT OR REPLACE INTO daily_performance 
                (rec_id, trade_date, close_price, daily_change_pct, cumulative_return, max_drawdown, max_high)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (rec_id, today, close_price, daily_change_pct, cumulative_return, max_drawdown, max_high))
            
            # Note: No auto-close on stop-loss - keep all stocks for full 10-day tracking period
            
        except Exception as e:
            print(f"Error updating {stock_name}: {e}")
            continue
    
    conn.commit()
    conn.close()
    print(f"✅ Updated {len(active_recs)} active recommendations")

def get_active_recommendations() -> pd.DataFrame:
    """Get all active recommendations with latest performance (deduplicated)"""
    conn = sqlite3.connect(DB_PATH)
    
    query = """
        SELECT 
            r.id,
            r.stock_code,
            r.stock_name,
            r.rec_date,
            r.rec_price,
            r.strategy_tag,
            r.status,
            dp.close_price as current_price,
            dp.daily_change_pct,
            dp.cumulative_return,
            dp.max_drawdown,
            dp.max_high,
            julianday('now') - julianday(r.rec_date) as days_tracked
        FROM recommendations r
        LEFT JOIN (
            SELECT rec_id, close_price, daily_change_pct, cumulative_return, max_drawdown, max_high
            FROM daily_performance
            WHERE (rec_id, trade_date) IN (
                SELECT rec_id, MAX(trade_date)
                FROM daily_performance
                GROUP BY rec_id
            )
        ) dp ON r.id = dp.rec_id
        WHERE r.status = 'Active'
        ORDER BY r.rec_date DESC, r.id DESC
    """
    
    df = pd.read_sql_query(query, conn)
    conn.close()
    
    # Deduplicate by stock_code to show cleaning list
    if not df.empty:
        df = df.drop_duplicates(subset=['stock_code'], keep='first')
        
    return attach_market_performance(df)

def get_closed_recommendations(days: int = 30) -> pd.DataFrame:
    """Get recently closed recommendations (deduplicated by stock code)"""
    conn = sqlite3.connect(DB_PATH)
    
    query = """
        SELECT 
            r.id,
            r.stock_code,
            r.stock_name,
            r.rec_date,
            r.rec_price,
            r.strategy_tag,
            dp.close_price as final_price,
            dp.cumulative_return as final_return,
            dp.max_drawdown,
            dp.max_high
        FROM recommendations r
        LEFT JOIN (
            SELECT rec_id, close_price, cumulative_return, max_drawdown, max_high
            FROM daily_performance
            WHERE (rec_id, trade_date) IN (
                SELECT rec_id, MAX(trade_date)
                FROM daily_performance
                GROUP BY rec_id
            )
        ) dp ON r.id = dp.rec_id
        WHERE r.status = 'Closed'
        AND julianday('now') - julianday(r.rec_date) <= ?
        ORDER BY r.rec_date DESC
    """
    
    df = pd.read_sql_query(query, conn, params=(days,))
    conn.close()
    
    # Deduplicate by stock_code, keeping only the most recent record
    if not df.empty:
        df = df.drop_duplicates(subset=['stock_code'], keep='first')
    
    return attach_market_performance(df)

def calculate_strategy_metrics(strategy_tag: str = None) -> Dict:
    """Calculate win rate and performance metrics by strategy"""
    conn = sqlite3.connect(DB_PATH)
    
    if strategy_tag:
        where_clause = "WHERE r.strategy_tag = ?"
        params = (strategy_tag,)
    else:
        where_clause = ""
        params = ()
    
    query = f"""
        SELECT 
            r.strategy_tag,
            COUNT(*) as total_recs,
            AVG(dp.cumulative_return) as avg_return,
            AVG(dp.max_drawdown) as avg_drawdown,
            SUM(CASE WHEN dp.cumulative_return > 0 THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN dp.cumulative_return > 15 THEN 1 ELSE 0 END) as gold_count,
            SUM(CASE WHEN dp.cumulative_return > 5 THEN 1 ELSE 0 END) as silver_count,
            SUM(CASE WHEN dp.cumulative_return < -5 OR dp.max_drawdown < -8 THEN 1 ELSE 0 END) as trash_count
        FROM recommendations r
        LEFT JOIN (
            SELECT rec_id, cumulative_return, max_drawdown
            FROM daily_performance
            WHERE (rec_id, trade_date) IN (
                SELECT rec_id, MAX(trade_date)
                FROM daily_performance
                GROUP BY rec_id
            )
        ) dp ON r.id = dp.rec_id
        {where_clause}
        GROUP BY r.strategy_tag
    """
    
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    
    if df.empty:
        return {}
    
    metrics = {}
    for _, row in df.iterrows():
        tag = row['strategy_tag'] or 'Unknown'
        metrics[tag] = {
            'total': int(row['total_recs']),
            'win_rate': (row['wins'] / row['total_recs'] * 100) if row['total_recs'] > 0 else 0,
            'avg_return': row['avg_return'] or 0,
            'avg_drawdown': row['avg_drawdown'] or 0,
            'gold_rate': (row['gold_count'] / row['total_recs'] * 100) if row['total_recs'] > 0 else 0,
            'silver_rate': (row['silver_count'] / row['total_recs'] * 100) if row['total_recs'] > 0 else 0,
            'trash_rate': (row['trash_count'] / row['total_recs'] * 100) if row['total_recs'] > 0 else 0
        }
    
    return metrics

# Initialize database on import
if not os.path.exists(DB_PATH):
    init_database()
