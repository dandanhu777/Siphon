print("DEBUG: Script started...")
import smtplib
from email.mime.text import MIMEText
from email.header import Header
import pandas as pd
import datetime
import sqlite3
import akshare as ak
import time
import os
import random

from index_service import get_benchmark_return, update_index_cache

# Import Enrichment
if os.environ.get("SKIP_AI"):
    enrich_top_picks = lambda x: {}
    print("⚠️ AI Enrichment Disabled (SKIP_AI=1)")
else:
    try:
        from gemini_enricher import enrich_top_picks
    except ImportError:
        enrich_top_picks = lambda x: {}

# --- Configuration ---
MAIL_HOST = "smtp.gmail.com"
MAIL_PORT = 465
# Use Environment Variables for Security (GitHub Actions) with Local Fallback
MAIL_USER = os.environ.get("MAIL_USER")
MAIL_PASS = os.environ.get("MAIL_PASS")

# Receivers from Env (Comma separated) or Default
env_receivers_str = os.environ.get("MAIL_RECEIVERS_LIST")
if env_receivers_str:
    MAIL_RECEIVERS = [x.strip() for x in env_receivers_str.split(",")]
else:
    # Minimal fallback or empty
    MAIL_RECEIVERS = ["tosinx@gmail.com"] # Default fallback

CSV_PATH = "siphon_strategy_results.csv"

# Env Override
env_receiver = os.environ.get("MAIL_RECEIVER")
if env_receiver:
    print(f"⚠️ [TEST MODE] Overriding Receivers: {env_receiver}")
    MAIL_RECEIVERS = [env_receiver]

print(f"🚀 Starting Report Generation. CSV: {CSV_PATH}")
if os.path.exists(CSV_PATH):
    print("✅ CSV File Found.")
else:
    print("❌ CSV File NOT Found.")
DB_PATH = "boomerang_tracker.db"

# --- v7.0.4 Data Inspector Module (extracted) ---
from data_inspector import DataInspector

# Global inspector instance
inspector = DataInspector(CSV_PATH)

def get_stock_link(code):
    market = "sh" if code.startswith("6") else "sz"
    return f"https://quote.eastmoney.com/{market}{code}.html"

import requests

class DirectSinaFetcher:
    def __init__(self):
        self.price_map = {}

    def fetch_prices(self, codes: list):
        """Batch fetch prices from Sina Direct API"""
        if not codes: return
        print(f"🔄 Fetching Prices (Sina Direct) for {len(codes)} symbols...")
        
        # Split into chunks of 20 to be safe with URL length
        chunk_size = 20
        for i in range(0, len(codes), chunk_size):
            chunk = codes[i:i+chunk_size]
            sina_codes = []
            for c in chunk:
                c = str(c).zfill(6)
                prefix = "sh" if c.startswith("6") else "sz"
                sina_codes.append(f"{prefix}{c}")
            
            try:
                list_str = ",".join(sina_codes)
                url = f"http://hq.sinajs.cn/list={list_str}"
                headers = {'Referer': 'https://finance.sina.com.cn/'}
                resp = requests.get(url, headers=headers, timeout=5)
                
                if resp.status_code == 200:
                    lines = resp.text.strip().split('\n')
                    for line in lines:
                        if "=\"" not in line: continue
                        # var hq_str_sh600651="Name,Open,PrevClose,Current,..."
                        parts = line.split('=')
                        code_part = parts[0].split('_')[-1] # sh600651
                        raw_code = code_part[2:] # 600651
                        
                        data_str = parts[1].replace('"', '')
                        fields = data_str.split(',')
                        if len(fields) > 3:
                            current_price = float(fields[3])
                            # If current price is 0 (suspended or auction), use PrevClose(2)
                            if current_price == 0.0:
                                current_price = float(fields[2])
                                
                            self.price_map[raw_code] = current_price
                            # print(f"   Got {raw_code}: {current_price}")
            except Exception as e:
                print(f"   ⚠️ Sina Batch Error: {e}")

    def get_price(self, symbol):
        symbol = str(symbol).zfill(6)
        if symbol in self.price_map:
            return self.price_map[symbol]
        
        # If not in map (missed batch), try individual
        self.fetch_prices([symbol])
        return self.price_map.get(symbol, None)

# --- v7.0 Logging System ---
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("SiphonSystem")

# --- v7.0 KlineCache + Shield (extracted modules) ---
from kline_cache import KlineCache
from shield_service import ShieldService

# Global KlineCache instance
kline_cache = KlineCache()

# ShieldService imported above

# Global Instance
fetcher = DirectSinaFetcher()

def fetch_enhanced_tracking_data(industry_map={}):
    if not os.path.exists(DB_PATH): return []
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT stock_code, stock_name, rec_price, rec_date, strategy_tag, siphon_score, industry, core_logic FROM recommendations ORDER BY rec_date DESC, siphon_score DESC, id ASC")
        # Ordered by Date DESC (Newest first), then Score DESC (Best first)
        all_rows = cursor.fetchall()
        conn.close()
        
        # 1. Group by Date to enforce "Top 3 Per Day"
        date_groups = {}
        for r in all_rows:
            d = r[3] # rec_date
            if d not in date_groups: date_groups[d] = []
            date_groups[d].append(r)
            
        # 2. Filter Top 3
        filtered_rows = []
        for d in sorted(date_groups.keys(), reverse=True):
             # They are already sorted by Score DESC in SQL
             day_picks = date_groups[d]
             # KEEP TOP 3
             top3 = day_picks[:3]
             filtered_rows.extend(top3)
        
        # 3. Proceed with existing logic using filtered_rows
        # Dedup Logic: Keep the OLDEST rec_date for each stock.
        # This ensures stocks that were recommended previously maintain their
        # original tracking date and don't get lost when re-recommended today.
        dedup_map = {}
        # Iterate from Newest to Oldest (filtered_rows is roughly Newest->Oldest dates)
        for r in filtered_rows:
            code = r[0]
            if code not in dedup_map:
                dedup_map[code] = {'row': r, 'count': 1}
            else:
                # Keep the OLDEST rec_date (overwrite with older entry)
                existing_date = dedup_map[code]['row'][3]
                current_date = r[3]
                if current_date < existing_date:
                    dedup_map[code] = {'row': r, 'count': dedup_map[code]['count'] + 1}
                else:
                    dedup_map[code]['count'] += 1
        
        sorted_codes = sorted(dedup_map.values(), key=lambda x: x['row'][3]) # Sort by Date ASC for processing logic
        
        # ... logic continues ...
        
        # v4.4 Fix: Exclude T+0 (Today's picks) from History Tracking
        # v4.5 Req: History Review 15 trading days (~25 calendar days)
        today = datetime.date.today()
        today_str = today.strftime('%Y-%m-%d')
        cutoff_date = (today - datetime.timedelta(days=25)).strftime('%Y-%m-%d')
        
        history_candidates = [
            item for item in sorted_codes 
            if item['row'][3] < today_str and item['row'][3] >= cutoff_date
        ]
        
        # Take all valid history items (reversed to show newest first)
        target_items = history_candidates 
        target_items.reverse()
        
        # Pre-fetch prices
        all_codes = [item['row'][0] for item in target_items]
        fetcher.fetch_prices(all_codes)
        
        final_data = []
        for item in target_items:
            r = item['row']; count = item['count']
            code, name, rec_price, rec_date_str, strategy_tag, siphon_score, db_industry, db_core_logic = r
            
            # v4.4 Filter: Exclude HK/Non-A (History)
            if len(str(code)) != 6:
                continue
            
            # v6.0 FIX: Exclude ETFs (Names with ETF or 51/15 prefix funds)
            if "ETF" in name.upper() or code.startswith("51") or code.startswith("15"):
                continue

            # v4.2 FILTER: Exclude items with Siphon Score < 3.0
            # Handle cases where score might be None (old data) -> Default to 3.0 (keep them)
            score_val = float(siphon_score) if siphon_score is not None else 3.0
            if score_val < 3.0:
                 continue
            
            # Use Direct Fetcher
            curr_price = fetcher.get_price(code)
            
            if not curr_price: 
                curr_price = rec_price # Fallback
            
            days = (datetime.date.today() - datetime.datetime.strptime(rec_date_str, '%Y-%m-%d').date()).days
            
            # v6.0 FIX: Universal Price Correction for History
            # Always try to verify Rec Price from history to ensure accuracy (e.g. checks against splits/bad DB data)
            # Only skipping if T+0 (today)
            if days > 0:
                verified_price = None
                for _ in range(3): # Retry 3 times for flaky network
                    try:
                        # AkShare History (Sina Source) - More reliable
                        # Range: RecDate - 10 days -> RecDate
                        prefix = "sz" if code.startswith("0") or code.startswith("3") else "sh"
                        long_code = prefix + code
                        rec_dt = datetime.datetime.strptime(rec_date_str, "%Y-%m-%d")
                        s_str = (rec_dt - datetime.timedelta(days=10)).strftime("%Y%m%d")
                        e_str = rec_dt.strftime("%Y%m%d")
                        
                        df_hist = ak.stock_zh_a_daily(symbol=long_code, start_date=s_str, end_date=e_str, adjust="qfq")
                        
                        if not df_hist.empty:
                            verified_price = float(df_hist.iloc[-1]['close'])
                            break
                    except Exception:
                        time.sleep(1)
                
                if verified_price is not None:
                    # Update if different
                     if abs(verified_price - rec_price) > 0.01:
                         # print(f"   [v6.0 Fix] {code} RecPrice {rec_price} -> {verified_price}")
                         rec_price = verified_price

            stock_ret = ((curr_price - rec_price) / rec_price) * 100
            
            # v4.5: Pass stock_code for multi-index matching
            idx_ret = get_benchmark_return(rec_date_str, stock_code=code)
            idx_ret_str = f"{idx_ret:+.2f}%" if idx_ret is not None else "0.00%"
            
            # v4.6 FIX: Replace "Missing API Key" message
            final_logic = db_core_logic if db_core_logic else strategy_tag
            if "Unavailable" in str(final_logic) or "Missing API Key" in str(final_logic):
                 # Try simple Fallback logic (Industry)
                 final_logic = "Unknown sector placeholder" # Default
                 try:
                     # Deterministic lookup (Lightweight)
                     # We can't import gemini_enricher here easily without circular dep, 
                     # so strictly use EM/CNINFO inline or simple placeholder to 'repair' display
                     import akshare as aks
                     try:
                         # Try CNINFO
                         df_info = aks.stock_profile_cninfo(symbol=code)
                         if not df_info.empty:
                             bus = df_info.iloc[0].get('主营业务')
                             if bus: final_logic = bus[:50] + "..."
                     except Exception:
                        pass
                 except Exception: pass

            # v9.0: Calculate Max Return Since Recommendation (using KlineCache)
            max_ret_str = "-"
            max_ret_val = 0.0
            try:
                if days > 0:
                    # Use pre-fetched KlineCache instead of individual API call
                    cached_max = kline_cache.get_max_high(code, rec_date_str)
                    if cached_max is not None:
                        max_high = float(cached_max)
                    else:
                        # Fallback to API if cache miss
                        prefix = "sz" if code.startswith("0") or code.startswith("3") else "sh"
                        long_code = prefix + code
                        today_str_clean = datetime.date.today().strftime("%Y%m%d")
                        rec_dt_str_clean = rec_date_str.replace("-", "")
                        df_max = ak.stock_zh_a_daily(symbol=long_code, start_date=rec_dt_str_clean, end_date=today_str_clean, adjust="qfq")
                        max_high = float(df_max['high'].max()) if not df_max.empty else curr_price
                    # Ensure Current Price is considered (for T+0 or intraday breakout)
                    if curr_price > max_high:
                        max_high = curr_price
                    # Calculate Max Return
                    if rec_price > 0:
                         max_ret_val = ((max_high - rec_price) / rec_price) * 100
                         max_ret_str = f'<div style="color:#ef4444; font-weight:800; font-size:12px;">{max_high:.2f}</div><div style="color:#dc2626; font-weight:800; font-size:16px;">+{max_ret_val:.1f}%</div>'
            except Exception:
                pass

            final_data.append({
                'code': code,
                'name': name,
                'rec_price': rec_price,
                'price': curr_price,
                'return': stock_ret,
                'index_str': idx_ret_str,
                'rec_date': rec_date_str,
                'days': days,
                'strategy': strategy_tag,
                'nth': count, # For badge
                't_str': f"T+{days}",
                'score': score_val,
                'industry': db_industry if db_industry else "Unknown",
                'core_logic': final_logic,
                'max_return': max_ret_str, # v6.3 Field
                'max_val': max_ret_val # v6.8 Field for Logic
            })
        return final_data
    except Exception as e:
        print(f"Tracking error: {e}")
        return []

# --- Generation Logic ---

def generate_report():
    if not os.path.exists(CSV_PATH): return

    # 1. Load Data
    df = pd.read_csv(CSV_PATH)
    industry_map = {str(row['Symbol']).zfill(6): row.get('Industry', '-') for _, row in df.iterrows()}
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    
    # 2. Enrichment
    print("Preparing Data...")

    # Fetch Tracking Data FIRST (to filter)
    track_data = fetch_enhanced_tracking_data(industry_map)
    tracked_codes = {x['code'] for x in track_data}
    
    # v7.0 Optimization: Pre-fetch K-line data for all tracked stocks
    all_tracked_codes = [x['code'] for x in track_data]
    if all_tracked_codes:
        logger.info(f"🚀 v7.0 Optimization: Batch pre-fetching K-line data...")
        kline_cache.prefetch(all_tracked_codes, shield_service=ShieldService)
    
    # v7.0.4 Data Inspector - Automated validation
    global inspector
    inspector = DataInspector()  # Reset for fresh check
    inspector.run_all_checks(track_data)
    
    # Filter candidates
    candidates = []
    others_today = []
    
    # Sort by Score
    sorted_df = df.sort_values(by=['AG_Score'], ascending=False)
    
    today_found = False
    for _, row in sorted_df.iterrows():
        code_str = str(row['Symbol']).zfill(6)
        
        # Check date (Assuming CSV has Date column, usually row['Date'])
        # If no Date column, assuming all result in CSV is fresh from today's run?
        # siphon_candidates.csv is usually APPENDED? No, run.sh doesn't clear it?
        # Actually usually siphon_strategy.py overwrites or appends?
        # Let's assume the CSV contains *latest* run data if generated today.
        # But wait, looking at generate_report logic, it didn't filter by date before.
        # It just took everything in CSV?
        # Line 281 `pd.read_csv`.
        # Line 294 iterates `df`.
        # If `siphon_candidates.csv` is the *daily output*, then all of it is Today.
        
        candidates.append(row)
            
    # Top Pick (Only 1 for the Daily Section)
    df_top = pd.DataFrame(candidates[:1]) if candidates else pd.DataFrame()
    
    # Runners Up (For History Section as T+0)
    if len(candidates) > 1:
        for row in candidates[1:]:
            others_today.append(row)
            
    # Force Update Index Cache for T+0 Data
    try: update_index_cache()
    except Exception: pass

    # Inject Runners Up into track_data (Limit to Top 3 Total = Rank 1 + Rank 2,3)
    t0_count = 0
    MAX_T0_DISPLAY = 2 
    
    for row in others_today:
        if t0_count >= MAX_T0_DISPLAY: break
    
        code = str(row['Symbol']).zfill(6)
        # Check if already in track_data (unlikely for T+0 unless re-running)
        if code not in tracked_codes:
            # v7.0.3 T+0 Benchmark - Use REAL-TIME index change
            t0_ret = 0.0
            t0_idx_str = "-"
            try:
                # Import real-time fetcher
                from index_service import get_realtime_index_change, get_index_code_for_stock
                
                # Get real-time data
                realtime_data = get_realtime_index_change()
                
                if realtime_data:
                    idx_key = get_index_code_for_stock(code)
                    if idx_key in realtime_data:
                        t0_idx_val = realtime_data[idx_key]
                        t0_idx_str = f"{t0_idx_val:+.2f}%"
                        logger.info(f"T+0 Benchmark for {code}: Real-time {idx_key} = {t0_idx_str}")
                else:
                    # Fallback to cache if real-time unavailable
                    import json
                    cache_file = "index_multi_cache.json"
                    if os.path.exists(cache_file):
                        with open(cache_file, 'r') as f:
                            cache = json.load(f)
                        idx_key = get_index_code_for_stock(code)
                        idx_data = cache.get(idx_key, {}).get("data", {})
                        if idx_data:
                            dates = sorted(idx_data.keys())
                            if len(dates) >= 2:
                                last_close = idx_data[dates[-1]]
                                prev_close = idx_data[dates[-2]]
                                t0_idx_val = ((last_close - prev_close) / prev_close) * 100
                                t0_idx_str = f"{t0_idx_val:+.2f}%"
            except Exception as e:
                logger.warning(f"T+0 Benchmark error for {code}: {e}")

            t0_item = {
                'code': code,
                'name': row['Name'],
                'rec_price': float(row['Price']),
                'price': float(row['Price']),
                'return': 0.0,
                'index_str': t0_idx_str,
                'rec_date': datetime.date.today().strftime("%Y-%m-%d"),
                'days': 0,
                'strategy': row.get('Strategy', 'Siphon'),
                'nth': t0_count + 2, # Start from Rank 2
                't_str': "T+0 (New)",
                'score': row['AG_Score'],
                'industry': row.get('Industry', 'Unknown'),
                'core_logic': row.get('Logic', 'Daily Candidate'),
                'max_return': "-"
            }
            # Add to proper position (Top of table)
            track_data.insert(t0_count, t0_item) # Insert specifically at top (0, 1, 2...)
            tracked_codes.add(code)
            t0_count += 1

    
    enrich_batch = []
    for _, row in df_top.iterrows():
        enrich_batch.append({'name': row['Name'], 'code': str(row['Symbol']).zfill(6), 'industry': row.get('Industry')})
    
    # Add tracking items
    for item in track_data:
        if item['code'] not in {x['code'] for x in enrich_batch}:
             enrich_batch.append({'name': item['name'], 'code': item['code'], 'industry': item['industry']})
             
    print(f"Enriching {len(enrich_batch)} items via AI...")
    ai_data_map = enrich_top_picks(enrich_batch)
    
    # v7.1: Validation Check - Ensure AI data is not empty
    if not ai_data_map or len(ai_data_map) == 0:
        print("⚠️ AI enrichment returned empty data. Using emergency fallback...")
        # Emergency fallback: use industry as business description
        ai_data_map = {}
        for item in enrich_batch:
            code = item['code']
            industry = item.get('industry', 'Unknown')
            ai_data_map[code] = {
                "business": f"属于{industry}行业" if industry != 'Unknown' else "待补充",
                "us_bench": "-",
                "target_price": "-"
            }
    else:
        print(f"✅ AI enrichment successful: {len(ai_data_map)} stocks enriched")
        # Debug: Show first enriched stock
        first_code = list(ai_data_map.keys())[0] if ai_data_map else None
        if first_code:
            print(f"   Sample: {first_code} -> {ai_data_map[first_code].get('business', 'N/A')[:50]}...")

    # 3. HTML Builder
    table_style = "width: 100%; border-collapse: separate; border-spacing: 0; font-family: -apple-system, sans-serif; font-size: 13px; border: 1px solid #e2e8f0; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); table-layout: fixed;"
    th_style = "padding: 8px 6px; background: #f8fafc; color: #64748b; text-align: left; font-weight: 600; font-size: 11px; letter-spacing: 0.5px; border-bottom: 2px solid #e2e8f0; vertical-align: bottom; line-height:1.3;"
    td_style = "padding: 10px 6px; border-bottom: 1px solid #f1f5f9; vertical-align: middle; overflow: hidden;"
    
    # Industry Summary (New Feature)
    industry_html = ""
    if 'Industry' in df_top.columns:
        top_inds = df_top['Industry'].dropna().unique().tolist()
        # Filter invalid
        top_inds = [x for x in top_inds if x and x != '-' and x != 'Unknown']
        if top_inds:
            badges = "".join([f'<span style="background:#e0e7ff; color:#4338ca; padding:3px 8px; border-radius:12px; font-size:11px; font-weight:600; margin-right:6px; border:1px solid #c7d2fe;">{ind}</span>' for ind in top_inds])
            industry_html = f'<div style="margin-bottom:12px; display:flex; align-items:center;"><span style="font-size:12px; font-weight:700; color:#475569; margin-right:8px;">🎯 涉及行业:</span>{badges}</div>'

    # Rec Table
    rec_html = industry_html + f'<table style="{table_style}">'
    rec_html += f'<thead><tr><th style="{th_style} width:15%;">标的/行业</th><th style="{th_style} width:12%;">虹吸分</th><th style="{th_style} width:20%;">价格 <br>(信号/目标)</th><th style="{th_style} width:38%;">AI 核心逻辑</th><th style="{th_style} width:15%;">美股对标</th></tr></thead><tbody>'

    for i, row in df_top.iterrows():
        symbol = str(row["Symbol"]).zfill(6)
        enrich = ai_data_map.get(symbol, {})
        link = get_stock_link(symbol)
        
        # Ensure fresh price
        # row['Price'] is from CSV (Strategy Run). We might want fresh too?
        # Ideally Strategy Run is fresh. But if we want real-time Rec Price:
        fresh_price = fetcher.get_price(symbol)
        display_price = fresh_price if fresh_price else row["Price"]
        
        bar_w = min(100, row["AG_Score"]*10)
        score_bar = f'<div style="width:40px; height:3px; background:#e2e8f0; border-radius:2px; margin-top:3px;"><div style="width:{bar_w}%; height:100%; background:linear-gradient(90deg, #f59e0b, #d97706); border-radius:2px;"></div></div>'
        
        ind = row.get("Industry","-")
        if not ind or ind == "Unknown" or ind == "-":
             try:
                 import akshare as aks
                 df_info = aks.stock_profile_cninfo(symbol=symbol) # symbol is 6-digit code
                 if not df_info.empty:
                     ind = df_info.iloc[0].get('行业')
             except Exception: pass
        if not ind: ind = "Unknown"

        rec_html += f'<tr>'
        rec_html += f'<td style="{td_style}"><a href="{link}" style="color:#0f172a; font-weight:bold; font-size:13px; text-decoration:none;">{row["Name"]}</a><br><span style="color:#64748b; font-size:10px;">{symbol}</span><br><span style="background:#eff6ff; color:#3b82f6; font-size:9px; padding:1px 3px; border-radius:3px;">{ind}</span></td>'
        rec_html += f'<td style="{td_style}"><div style="color:#d97706; font-weight:800; font-size:14px;">{row["AG_Score"]}</div>{score_bar}</td>'
        rec_html += f'<td style="{td_style}"><div style="font-weight:600; color:#334155; font-size:12px;">¥{display_price:.2f}</div><div style="font-size:10px; color:#10b981; margin-top:1px;">🎯 {enrich.get("target_price","-")}</div></td>'
        rec_html += f'<td style="{td_style} font-size:11px; line-height:1.4; color:#475569;">{enrich.get("business","-")}</td>'
        rec_html += f'<td style="{td_style} font-size:11px; font-weight:600; color:#4f46e5;">{enrich.get("us_bench","-")}</td>'
        rec_html += f'</tr>'
    rec_html += '</tbody></table>'

    # Tracking Table
    if track_data:
        track_html = f"""
        <div style="margin-top: 35px;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
                <div style="font-weight:700; color:#334155; font-size:15px;">📊 历史回顾 (Tracking)</div>
                <div style="font-size:11px; color:#94a3b8; background:#f1f5f9; padding:2px 6px; border-radius:4px;">Ref: SSEC</div>
            </div>
            <table style="{table_style}">
                <thead>
                    <tr>
                        <th style="{th_style} width:15%;">标的/行业</th>
                        <th style="{th_style} width:8%; text-align:center;">推荐当日分值</th>
                        <th style="{th_style} width:25%;">AI 核心逻辑</th>
                        <th style="{th_style} width:8%; text-align:center;">持有时间</th>
                        <th style="{th_style} width:10%; text-align:right;">推荐日价格/现价</th>
                        <th style="{th_style} width:9%; text-align:center;">现有收益</th>
                        <th style="{th_style} width:10%; text-align:center;">操作建议</th>
                        <th style="{th_style} width:9%; text-align:center;">最高收益</th>
                        <th style="{th_style} width:8%; text-align:center;">同期大盘</th>
                    </tr>
                </thead>
                <tbody>
        """
        for item in track_data:
            enrich = ai_data_map.get(item['code'], {})
            link = get_stock_link(item['code'])
            ret = item['return']
            
            # v6.7 Shield v2 Logic
            _, action_text, action_bg, action_fg = ShieldService.evaluate(item['code'], item['price'], item['days'], ret, max_return_pct=item.get('max_val', 0.0), kline_cache=kline_cache)
            ret_color = "#dc2626" if ret > 0 else "#16a34a"
            idx_str = item['index_str']
            idx_color = "#64748b"
            if idx_str.startswith("+") and idx_str != "+0.00%": idx_color = "#dc2626"
            elif idx_str.startswith("-") and idx_str != "-0.00%": idx_color = "#16a34a"
            elif "0.00" in idx_str: idx_color = "#94a3b8"

            badge = f'<span style="font-size:9px; background:#e0f2fe; color:#0284c7; padding:1px 4px; border-radius:3px; margin-left:3px;">R{item["nth"]}</span>' if item['nth'] > 1 else ""

            track_html += f'<tr>'
            track_html += f'<td style="{td_style}"><a href="{link}" style="text-decoration:none; color:#334155; font-weight:600; font-size:13px;">{item["name"]}</a> {badge}<br><span style="color:#94a3b8; font-size:10px;">{item["code"]}</span><br><span style="color:#64748b; font-size:9px;">{item.get("industry","-")}</span></td>'
            track_html += f'<td style="{td_style} text-align:center;"><div style="color:#d97706; font-weight:700; font-size:12px;">{item.get("score", "-")}</div></td>'
            core_logic = item.get("core_logic")
            if not core_logic: core_logic = enrich.get("business", item.get("strategy"))
            track_html += f'<td style="{td_style} font-size:11px; color:#475569; line-height:1.4;">{core_logic}</td>'
            track_html += f'<td style="{td_style} text-align:center; font-weight:bold; color:#64748b; font-size:11px;">{item["t_str"]}</td>'
            track_html += f'<td style="{td_style} text-align:right; font-size:10px;"><div style="color:#94a3b8;">{item["rec_price"]:.2f}</div><div style="font-weight:bold; color:#334155; font-size:12px;">{item["price"]:.2f}</div></td>'
            track_html += f'<td style="{td_style} text-align:center; font-weight:bold; font-size:12px; color:{ret_color};">{ret:+.2f}%</td>'
            track_html += f'<td style="{td_style} text-align:center;"><span style="background:{action_bg}; color:{action_fg}; padding:4px 8px; border-radius:4px; font-weight:800; font-size:11px; display:inline-block; min-width:50px;">{action_text}</span></td>' 
            track_html += f'<td style="{td_style} text-align:center; font-size:11px;">{item["max_return"]}</td>'

            track_html += f'<td style="{td_style} text-align:center; font-size:11px; color:{idx_color}; background:#f8fafc;">{idx_str}</td>'
            track_html += '</tr>'
        track_html += '</tbody></table></div>'
    else: track_html = ""

    full_html = f"""
    <div style="font-family: 'Inter', -apple-system, sans-serif; max-width: 720px; margin: 0 auto; color: #1e293b; background: #ffffff;">
    <div style="text-align:center; padding: 25px 0;">
            <div style="font-size:24px; font-weight:800; color:#1e293b; letter-spacing:-0.5px;">短线虹吸精选 (v8.0.0)</div>
            <div style="font-size:13px; color:#64748b; margin-top:6px;">{current_time}</div>
        </div>
        
        <div style="background: linear-gradient(to bottom right, #f8fafc, #ffffff); border: 1px solid #e2e8f0; border-radius: 12px; padding: 20px; margin: 25px 0; box-shadow: 0 4px 6px -2px rgba(0,0,0,0.03);">
            <div style="font-weight: 700; color: #334155; font-size: 15px; display: flex; align-items: center; margin-bottom: 20px;">
                <span style="background:#dbeafe; width:8px; height:8px; border-radius:50%; margin-right:8px;"></span> 策略核心进入机制 (Entry Mechanism)
            </div>
            
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px; font-size: 12px; color: #475569; line-height: 1.6;">
                <div>
                    <div style="color:#0ea5e9; font-weight:700; margin-bottom:6px;">1. 虹吸分 (Siphon Score)</div>
                    <div>衡量大资金“逆势吸筹”意愿。分数基于<span style="background:#e0f2fe; color:#0284c7; padding:0 3px;">抗跌幅度</span>与<span style="background:#e0f2fe; color:#0284c7; padding:0 3px;">主动买盘</span>比率。得分 >3.0 表示主力介入。</div>
                </div>
                <div>
                     <div style="color:#f59e0b; font-weight:700; margin-bottom:6px;">2. VCP 形态 (Contraction)</div>
                     <div>价格波动收敛 + 量能极致枯竭。意味着洗盘结束。</div>
                </div>
                <div>
                     <div style="color:#10b981; font-weight:700; margin-bottom:6px;">3. 选股逻辑 (Selection)</div>
                     <div>我们只选择 <span style="background:#f0fdf4; padding:2px 4px; border-radius:3px;">MA50之上趋势向上</span> 且流动性>1亿的标的。</div>
                </div>
                <div>
                     <div style="color:#8b5cf6; font-weight:700; margin-bottom:6px;">4. VCP RelStr (相对强度)</div>
                     <div><span style="background:#f3e8ff; padding:2px 4px; border-radius:3px;">Relative Strength</span> 优先选择 RS 评分 > 80 的标的，即走势强于全市场80%的个股。</div>
                </div>
            </div>
        </div>
        
        <div style="margin-bottom: 10px;">
            <div style="font-weight:700; color:#334155; font-size:15px; margin-bottom:12px;">🚀 今日核心优选 (Top Picks)</div>
            {rec_html}
        </div>
        
        {track_html}
        
        
        <div style="background: linear-gradient(to bottom right, #fff1f2, #ffffff); border: 1px solid #ffe4e6; border-radius: 12px; padding: 20px; margin: 25px 0; box-shadow: 0 4px 6px -2px rgba(0,0,0,0.03);">
            <div style="font-weight: 700; color: #be123c; font-size: 15px; display: flex; align-items: center; margin-bottom: 20px;">
                <span style="background:#fda4af; width:8px; height:8px; border-radius:50%; margin-right:8px;"></span> 策略核心退出机制 (Exit Mechanism)
            </div>
            
            <div style="font-size: 12px; color: #334155; line-height: 1.6;">
                <div style="margin-bottom: 15px;">
                    <div style="color:#e11d48; font-weight:700; margin-bottom:4px;">1. 初始化: 防御基准 (Hard Exit)</div>
                    <div><span style="background:#ffe4e6; color:#9f1239; padding:0 4px; border-radius:3px;">生存锁</span>: 触及 <strong>-7%</strong> 立即清算。无条件执行，防止非线性亏损螺旋。</div>
                </div>
                
                <div style="margin-bottom: 15px;">
                    <div style="color:#d97706; font-weight:700; margin-bottom:4px;">2. 滞涨过滤: 资本效率 (Soft Exit)</div>
                    <div><span style="background:#fffbeb; color:#b45309; padding:0 4px; border-radius:3px;">机会成本</span>: 持仓 <strong>>5天浮亏</strong> 或 <strong>>10天僵滞</strong>，视为动量失效，立即回收资金。</div>
                </div>

                <div style="margin-bottom: 15px;">
                    <div style="color:#059669; font-weight:700; margin-bottom:4px;">3. 动量捕获: 合成凸性 (Smart Exit)</div>
                    <div><span style="background:#ecfdf5; color:#047857; padding:0 4px; border-radius:3px;">Trailing Stop</span>: 利润 >15% 后激活追踪止损 (回撤5%)，只做右侧离场，让利润奔跑。</div>
                </div>

                <div>
                    <div style="color:#7c3aed; font-weight:700; margin-bottom:4px;">4. 环境感知: 主动防御 (De-risk)</div>
                    <div><span style="background:#f3e8ff; color:#6d28d9; padding:0 4px; border-radius:3px;">Technical Warning</span>: 出现 MACD 死叉或破位时，主动降低仓位敞口。</div>
                </div>
            </div>
        </div>


        <!-- Scoring Logic Appendix (Chinese) -->
        <div style="margin: 25px 0; border-top: 1px solid #f1f5f9; padding-top: 15px;">
            <div style="font-size: 11px; font-weight: 700; color: #94a3b8; margin-bottom: 8px; text-transform: uppercase;">逻辑技术附录: V10.0 打板极爆版 (满分 100) | 10:00探索 & 14:40定版</div>
            <div style="font-size: 10px; color: #64748b; line-height: 1.5; font-family: Consolas, Monaco, monospace; background: #f8fafc; padding: 12px; border-radius: 6px; border: 1px solid #e2e8f0;">
                <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
                    <span><strong>1. 资金爆破模块 (40分)</strong></span>
                    <span>强索量价共振: 当日极速爆量且收盘价逼近全天最高点 (光头阳线)</span>
                </div>
                <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
                    <span><strong>2. 极速微观动量 (25分)</strong></span>
                    <span>3日Alpha与5日Alpha连击。短线越强越买，彻底抛弃20日慢线数据</span>
                </div>
                <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
                    <span><strong>3. 逆势抗跌核心 (20分)</strong></span>
                    <span>指数大跌或跳水时的逆势金身表现 (避险盾牌)</span>
                </div>
                <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
                    <span><strong>4. 老鸭头形态 VCP (15分)</strong></span>
                    <span>捕捉极限的缩量起爆点：昨日极致萎缩，今日放量拉涨</span>
                </div>
                <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
                    <span style="color: #0369a1;"><strong>⏰ 日内双线运行机制:</strong></span>
                    <span style="color: #0369a1; text-align: right;"><strong>10:00</strong> 早盘警示打底仓；<br><strong>14:40</strong> 尾盘定版防跳水 (过滤假突破)。</span>
                </div>
            </div>
        </div>

        <!-- Disclaimer -->
        <div style="margin: 30px 0 10px 0; padding: 15px; background: #fef2f2; border: 1px solid #fee2e2; border-radius: 8px; text-align: center;">
            <div style="color: #dc2626; font-weight: 700; font-size: 12px; margin-bottom: 5px;">⚠️ 风险提示 (Risk Warning)</div>
            <div style="color: #b91c1c; font-size: 11px; line-height: 1.5;">
                当前为测试版本 (Beta)。股市有风险，投资需谨慎，风险自负。<br>
                The current version is for testing only. Investment involves risk.
            </div>
        </div>
        
        <div style="margin: 20px 0 20px 0; text-align: center;">
            <a href="https://github.com/Antigravity" style="color: #cbd5e1; font-size: 11px; text-decoration: none;">Antigravity Alpha System | Powered by ddhu</a>
        </div>
    </div>
    """
    msg = MIMEText(full_html, 'html', 'utf-8')
    msg['From'] = Header("AI 参谋部", 'utf-8')
    msg['To'] = Header("Commander", 'utf-8')
    today_date = datetime.date.today().strftime("%m/%d")
    msg['Subject'] = Header(f"✨ 短线虹吸精选 v8.0.0: 深度研报 ({today_date})", 'utf-8')
    # v7.0.1: Add retry logic for SSL errors
    for attempt in range(3):
        try:
            logger.info(f"📧 Sending email (attempt {attempt+1}/3)...")
            smtp = smtplib.SMTP_SSL(MAIL_HOST, MAIL_PORT, timeout=60)
            smtp.login(MAIL_USER, MAIL_PASS)
            smtp.sendmail(MAIL_USER, MAIL_RECEIVERS, msg.as_string())
            smtp.quit()
            logger.info("✅ Report sent successfully.")
            print("✅ Report sent successfully.")
            break
        except Exception as e:
            logger.warning(f"Email attempt {attempt+1} failed: {e}")
            if attempt == 2:
                print(f"❌ Email Error (all attempts failed): {e}")
            else:
                time.sleep(2)  # Wait before retry

if __name__ == "__main__":
    generate_report()
