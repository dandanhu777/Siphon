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

from index_service import get_benchmark_return

# Import Enrichment
try:
    from gemini_enricher import enrich_top_picks
except ImportError:
    enrich_top_picks = lambda x: {}

# --- Configuration ---
MAIL_HOST = "smtp.gmail.com"
MAIL_PORT = 465
MAIL_USER = "leavertondrozdowskisu239@gmail.com"
MAIL_PASS = "saimfxiilntucmph"
# v4.6 Update: Full Recipient List
FULL_LIST = [
     "28595591@qq.com",
     "89299772@qq.com",
     "milsica@gmail.com",
     "tosinx@gmail.com",
     "874686267@qq.com",
     "zhengzheng.duan@kone.com",
     "8871802@qq.com",
     "171754089@qq.com"
]
# For testing/staging, only send to Commander
MAIL_RECEIVERS = ["tosinx@gmail.com"]

CSV_PATH = "siphon_strategy_results.csv"
DB_PATH = "boomerang_tracker.db"

# --- Helpers ---

def get_stock_link(code):
    code = str(code)
    if len(code) == 5:
        return f"https://quote.eastmoney.com/hk/{code}.html"
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
                c = str(c)
                if len(c) == 5: # HK Stock
                     # Sina HK format: hk00700
                     sina_codes.append(f"hk{c}")
                else:
                    c = c.zfill(6)
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
                        code_part = parts[0].split('_')[-1] # sh600651 or hk00700
                        if code_part.startswith('hk'):
                            raw_code = code_part[2:] # 00700
                        else:
                            raw_code = code_part[2:] # 600651 (sh/sz len 2)
                        
                        data_str = parts[1].replace('"', '')
                        fields = data_str.split(',')
                        if len(fields) > 6: # HK data has different fields?
                            # Sina HK fields: EnName, ChName, Open, PrevClose, High, Low, Last, ...
                            # Let's check Sina HK format. 
                            # var hq_str_hk00700="TENCENT,腾讯控股,282.000,278.400,285.000,281.200,284.400,..."
                            # Index 6 is Last Price? 
                            # Index: 0:EnName, 1:CnName, 2:Open, 3:PrevClose, 4:High, 5:Low, 6:Last
                            if code_part.startswith('hk'):
                                current_price = float(fields[6])
                            else:
                                current_price = float(fields[3])
                            # If current price is 0 (suspended or auction), use PrevClose(2)
                            if current_price == 0.0:
                                current_price = float(fields[2])
                                
                            self.price_map[raw_code] = current_price
                            # print(f"   Got {raw_code}: {current_price}")
            except Exception as e:
                print(f"   ⚠️ Sina Batch Error: {e}")

    def get_price(self, symbol):
        symbol = str(symbol)
        if len(symbol) == 6: symbol = symbol.zfill(6) # Only zfill CN codes
        if symbol in self.price_map:
            return self.price_map[symbol]
        
        # If not in map (missed batch), try individual
        self.fetch_prices([symbol])
        return self.price_map.get(symbol, None)

# Global Instance
fetcher = DirectSinaFetcher()


# Helper for Industry Fallback
def fetch_industry_online(symbol):
    try:
        # Use Akshare to get individual stock info
        # This returns a DF with fields like '总市值', '行业' etc.
        df = ak.stock_individual_info_em(symbol=symbol)
        if df.empty: return None
        # Convert to dict for easier lookup
        # DF has 2 columns: 'item', 'value' usually?
        # Let's check structure. stock_individual_info_em returns:
        # | item | value |
        # | 行业 | 半导体 |
        row = df[df['item'] == '行业']
        if not row.empty:
            return row['value'].values[0]
        return None
    except Exception as e:
        print(f"⚠️ Industry Fetch Error for {symbol}: {e}")
        return None

def fetch_enhanced_tracking_data(industry_map={}):
    if not os.path.exists(DB_PATH): return []
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT stock_code, stock_name, rec_price, rec_date, strategy_tag, siphon_score, id, industry FROM recommendations ORDER BY rec_date ASC")
        all_rows = cursor.fetchall()
        # Schema: 0:code, 1:name, 2:price, 3:date, 4:tag, 5:score, 6:id, 7:industry
        # NOTE: I added 'id' to SELECT to allow UPDATE
        conn.close()
        
        # Dedup Logic
        dedup_map = {}
        for r in all_rows:
            code = r[0]
            if code not in dedup_map:
                dedup_map[code] = {'first': r, 'latest': r, 'count': 1}
            else:
                dedup_map[code]['count'] += 1
                dedup_map[code]['latest'] = r 
        
        # Construct Hybrid Rows & Auto-heal Industry
        final_values = []
        conn = sqlite3.connect(DB_PATH) # Re-open for updates
        cursor = conn.cursor()
        
        for code, data in dedup_map.items():
            first = data['first']   # 0:code, ..., 6:id, 7:industry
            latest = data['latest'] # ...
            
            # Check Industry (Index 7)
            ind = latest[7]
            if not ind or ind == "None":
                print(f"🔄 Fetching missing industry for {code}...")
                ind = fetch_industry_online(code)
                if ind:
                    # Update ALL records for this code (to keep DB clean)
                    try:
                        cursor.execute("UPDATE recommendations SET industry = ? WHERE stock_code = ?", (ind, code))
                        conn.commit()
                        print(f"✅ Auto-healed industry for {code}: {ind}")
                    except Exception as e:
                        print(f"❌ Failed to update DB: {e}")
            
            # Hybrid Row Construction
            # We want: code, name, rec_price, rec_date, strategy_tag, siphon_score, industry
            # Sources:
            # - First: code(0), name(1), price(2), date(3)
            # - Latest: tag(4), score(5)
            # - Healed: ind
            # Hybrid Row Construction
            # We want: code, name, rec_price, rec_date, strategy_tag, siphon_score, industry
            # Sources:
            # - First: code(0), name(1), price(2), date(3)
            # - Latest: tag(4)  <-- Keep latest tag (evolution)
            # - First: score(5) <-- Use INITIAL score (Rec Day Score) as requested
            # - Healed: ind
            hybrid_row = (first[0], first[1], first[2], first[3], latest[4], first[5], ind)
            
            final_values.append({'row': hybrid_row, 'count': data['count']})
            
        conn.close()

        sorted_codes = sorted(final_values, key=lambda x: x['row'][3])
        target_items = sorted_codes[-10:] 
        target_items.reverse()
        
        # Pre-fetch prices
        all_codes = [item['row'][0] for item in target_items]
        fetcher.fetch_prices(all_codes)
        
        final_data = []
        for item in target_items:
            r = item['row']; count = item['count']
            code, name, rec_price, rec_date_str, strategy_tag, siphon_score, industry = r
            
            # v4.2 FILTER: Exclude items with Siphon Score < 3.0
            # Handle cases where score might be None (old data) -> Default to 3.0 (keep them)
            score_val = float(siphon_score) if siphon_score is not None else 3.0
            if score_val < 3.0:
                 continue
            
            # Use Direct Fetcher
            curr_price = fetcher.get_price(code)
            
            if not curr_price: 
                curr_price = rec_price # Fallback
            
            stock_ret = ((curr_price - rec_price) / rec_price) * 100
            idx_ret = get_benchmark_return(rec_date_str)
            days = (datetime.date.today() - datetime.datetime.strptime(rec_date_str, '%Y-%m-%d').date()).days
            
            final_data.append({
                'code': code,
                'name': name,
                'rec_price': rec_price,
                'price': curr_price,
                'return': stock_ret,
                'index_str': f"{idx_ret:+.2f}%" if idx_ret is not None else "0.00%",
                'rec_date': rec_date_str,
                'days': days,
                'strategy': strategy_tag,
                'nth': count, # For badge
                't_str': f"T+{days}",
                'score': score_val,
                'industry': industry # v4.7 Display
            })
        return final_data
    except Exception as e:
        print(f"Tracking error: {e}")
        return []

# --- Generation Logic ---

def generate_report():
    if not os.path.exists(CSV_PATH): return

    # 1. Load Data
    # 1. Load Data
    df = pd.read_csv(CSV_PATH)
    
    # ---------------------------------------------------------
    # SMART NORMALIZATION & MARKET VALIDATION (Fixes 002487 vs 02487)
    # ---------------------------------------------------------
    def smart_normalize_symbol(row):
        code_str = str(row['Symbol'])
        name = row['Name']
        
        # 1. Known HK Tech List (Hard rule)
        hk_tech_names = ["腾讯", "美团", "小米", "快手", "中芯国际", "京东", "阿里", "网易", "百度"]
        for n in hk_tech_names:
            if n in name:
                # Likely HK. 
                # Tencent is 700 -> 00700 (5 digits)
                if len(code_str) <= 5: return code_str.zfill(5)
        
        # 2. Heuristic for A-Shares (Most common)
        # 2487 -> 002487 (CN) vs 02487 (HK)
        
        # Try zfill(6) first - Standard A-share
        candidate_cn = code_str.zfill(6)
        
        # Heuristic: A-share starts with 00, 30, 60, 68
        if candidate_cn.startswith(("00", "30", "60", "68")):
            # Very likely A-share. 
            return candidate_cn
            
        # If not standard prefix (e.g. 5-digit HK code?), return zfill(5)
        if len(code_str) <= 5:
            return code_str.zfill(5)
            
        return candidate_cn # Default
        
    df['Symbol'] = df.apply(smart_normalize_symbol, axis=1)
    
    industry_map = {row['Symbol']: row.get('Industry', '-') for _, row in df.iterrows()}
    
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    
    # 2. Enrichment
    print("Preparing Data...")

    # Fetch Tracking Data FIRST
    track_data = fetch_enhanced_tracking_data(industry_map)
    # Normalize track codes too just in case
    for item in track_data:
        item['code'] = smart_normalize_symbol({'Symbol': item['code'], 'Name': item['name']})
        
    tracked_codes = {x['code'] for x in track_data}
    
    # Filter candidates
    candidates = []
    for _, row in df.sort_values(by=['AG_Score'], ascending=False).iterrows():
        code_str = row['Symbol']
        if code_str not in tracked_codes:
            candidates.append(row)
            
    # Enrich Batch (CN + HK)
    enrich_batch = []
    for row in candidates:
        enrich_batch.append({'name': row['Name'], 'code': row['Symbol'], 'industry': row.get('Industry')})
    
    for item in track_data:
        if item['code'] not in {x['code'] for x in enrich_batch}:
             enrich_batch.append({'name': item['name'], 'code': item['code'], 'industry': item['industry']})
             
    print(f"Enriching {len(enrich_batch)} items via AI...")
    ai_data_map = enrich_top_picks(enrich_batch)

    # 3. Split Data into CN / HK
    # CN: 6 digits starting with 6, 0, 3, 4, 8
    # HK: 5 digits starting with 0
    # Logic: Len=6 => CN. Len=5 => HK.
    cn_candidates = [row for row in candidates if len(row['Symbol']) == 6]
    hk_candidates = [row for row in candidates if len(row['Symbol']) == 5]
    
    # Limit to top 3 each
    cn_candidates = cn_candidates[:3]
    hk_candidates = hk_candidates[:3]
    
    cn_track = [x for x in track_data if len(x['code']) == 6]
    hk_track = [x for x in track_data if len(x['code']) == 5]

    # 4. Helper for HTML Generation
    table_style = "width: 100%; border-collapse: separate; border-spacing: 0; font-family: -apple-system, sans-serif; font-size: 13px; border: 1px solid #e2e8f0; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); table-layout: fixed;"
    th_style = "padding: 6px 4px; background: #f8fafc; color: #64748b; text-align: left; font-weight: 600; font-size: 11px; letter-spacing: 0.5px; border-bottom: 2px solid #e2e8f0; vertical-align: bottom; line-height:1.3;"
    td_style = "padding: 8px 4px; border-bottom: 1px solid #f1f5f9; vertical-align: middle; overflow: hidden;"

    def render_market_section(title, anchor_id, candidates_list, track_list):
        html = f"""
        <div id="{anchor_id}" style="scroll-margin-top: 20px; margin-bottom: 40px; border-top: 3px solid #e2e8f0; padding-top: 20px;">
            <div style="font-weight:800; color:#1e293b; font-size:18px; margin-bottom:15px; display:flex; align-items:center;">
                <span style="background:#0f172a; width:4px; height:18px; margin-right:8px; border-radius:2px;"></span>
                {title}
            </div>
        """
        
        # Top Picks Table
        if candidates_list:
            html += f'<div style="font-weight:700; color:#334155; font-size:15px; margin-bottom:12px;">🚀 今日核心优选 (Top Picks)</div>'
            html += f'<table style="{table_style}">'
            html += f'<thead><tr><th style="{th_style} width:15%;">标的/行业</th><th style="{th_style} width:12%;">虹吸分</th><th style="{th_style} width:20%;">价格 <br>(信号/目标)</th><th style="{th_style} width:38%;">AI 核心逻辑</th><th style="{th_style} width:15%;">美股对标</th></tr></thead><tbody>'
            
            # Rec rows ... need to iterate candidates_list (which are rows)
            # We need to construct DataFrame from list of Series is hard.
            # Convert candidates_list back to DF or iterate dict?
            # candidates_list is list of Series.
            for row in candidates_list:
                symbol = str(row["Symbol"])
                if len(symbol) == 6: symbol = symbol.zfill(6)
                
                enrich = ai_data_map.get(symbol, {})
                link = get_stock_link(symbol)
                
                fresh_price = fetcher.get_price(symbol)
                display_price = fresh_price if fresh_price else row["Price"]
                
                score = row["AG_Score"]
                # 3. Split Data into CN / HK
    # Logic: Len=6 => CN. Len=5 => HK. (Guaranteed by smart_normalize_symbol)
    cn_candidates = [row for row in candidates if len(row['Symbol']) == 6]
    hk_candidates = [row for row in candidates if len(row['Symbol']) == 5]
    
    # Limit to top 3 each
    cn_candidates = cn_candidates[:3]
    hk_candidates = hk_candidates[:3]
    
    cn_track = [x for x in track_data if len(x['code']) == 6]
    hk_track = [x for x in track_data if len(x['code']) == 5]

    # 4. Helper for HTML Generation
    table_style = "width: 100%; border-collapse: separate; border-spacing: 0; font-family: -apple-system, sans-serif; font-size: 13px; border: 1px solid #e2e8f0; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); table-layout: fixed;"
    th_style = "padding: 6px 4px; background: #f8fafc; color: #64748b; text-align: left; font-weight: 600; font-size: 11px; letter-spacing: 0.5px; border-bottom: 2px solid #e2e8f0; vertical-align: bottom; line-height:1.3;"
    td_style = "padding: 8px 4px; border-bottom: 1px solid #f1f5f9; vertical-align: middle; overflow: hidden;"

    def render_market_section(title, anchor_id, candidates_list, track_list):
        html = f"""
        <!-- Top Picks Table -->
        """
        if candidates_list:
            html += f'<div style="font-weight:700; color:#334155; font-size:15px; margin-bottom:12px;">🚀 今日核心优选 (Top Picks)</div>'
            html += f'<table style="{table_style}">'
            html += f'<thead><tr><th style="{th_style} width:15%;">标的/行业</th><th style="{th_style} width:12%;">虹吸分</th><th style="{th_style} width:20%;">价格 <br>(信号/目标)</th><th style="{th_style} width:38%;">AI 核心逻辑</th><th style="{th_style} width:15%;">美股对标</th></tr></thead><tbody>'
            
            for row in candidates_list:
                symbol = str(row["Symbol"])
                
                enrich = ai_data_map.get(symbol, {})
                link = get_stock_link(symbol)
                
                fresh_price = fetcher.get_price(symbol)
                display_price = fresh_price if fresh_price else row["Price"]
                
                score = row["AG_Score"]
                bar_w = min(100, score*10)
                score_bar = f'<div style="width:40px; height:3px; background:#e2e8f0; border-radius:2px; margin-top:3px;"><div style="width:{bar_w}%; height:100%; background:linear-gradient(90deg, #f59e0b, #d97706); border-radius:2px;"></div></div>'
                
                tags = row.get("AG_Details", "").split()
                tag_html = "".join([f'<span style="background:#fce7f3; color:#be185d; font-size:9px; padding:1px 3px; border-radius:3px; margin-left:2px;">{t}</span>' for t in tags])
                
                html += f'<tr>'
                html += f'<td style="{td_style}"><a href="{link}" style="color:#0f172a; font-weight:bold; font-size:13px; text-decoration:none;">{row["Name"]}</a><br><span style="color:#64748b; font-size:10px;">{symbol}</span><br><span style="background:#eff6ff; color:#3b82f6; font-size:9px; padding:1px 3px; border-radius:3px;">{row.get("Industry","-")}</span> {tag_html}</td>'
                html += f'<td style="{td_style}"><div style="color:#d97706; font-weight:800; font-size:14px;">{score}</div>{score_bar}</td>'
                html += f'<td style="{td_style}"><div style="font-weight:600; color:#334155; font-size:12px;">{display_price:.2f}</div><div style="font-size:10px; color:#10b981; margin-top:1px;">🎯 {enrich.get("target_price","-")}</div></td>'
                html += f'<td style="{td_style} font-size:11px; line-height:1.4; color:#475569;">{enrich.get("business","-")}</td>'
                html += f'<td style="{td_style} font-size:11px; font-weight:600; color:#4f46e5;">{enrich.get("us_bench","-")}</td>'
                html += f'</tr>'
            html += '</tbody></table>'
        else:
            html += '<div style="font-size:12px; color:#94a3b8; padding:10px; text-align:center;">暂无今日优选 (No Top Picks Today)</div>'

        # Tracking Table
        if track_list:
            html += f"""
            <div style="margin-top: 25px;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
                    <div style="font-weight:700; color:#334155; font-size:15px;">📊 历史回顾 (Tracking)</div>
                </div>
                <table style="{table_style}">
                    <thead>
                        <tr>
                            <th style="{th_style} width:20%;">标的/行业</th>
                            <th style="{th_style} width:9%; text-align:center;">推荐日分值</th>
                            <th style="{th_style} width:16%;">AI 核心逻辑</th>
                            <th style="{th_style} width:7%; text-align:center;">持有</th>
                            <th style="{th_style} width:20%; text-align:right;">价格</th>
                            <th style="{th_style} width:14%; text-align:center;">收益</th>
                            <th style="{th_style} width:14%; text-align:center;">大盘</th>
                        </tr>
                    </thead>
                    <tbody>
            """
            for item in track_list:
                enrich = ai_data_map.get(item['code'], {})
                link = get_stock_link(item['code'])
                ret = item['return']
                ret_color = "#dc2626" if ret > 0 else "#16a34a"
                idx_str = item['index_str']
                idx_color = "#64748b"
                if idx_str.startswith("+") and idx_str != "+0.00%": idx_color = "#dc2626"
                elif idx_str.startswith("-") and idx_str != "-0.00%": idx_color = "#16a34a"
                elif "0.00" in idx_str: idx_color = "#94a3b8"

                badge = f'<span style="font-size:9px; background:#e0f2fe; color:#0284c7; padding:1px 4px; border-radius:3px; margin-left:3px;">R{item["nth"]}</span>' if item['nth'] > 1 else ""

                html += f'<tr>'
                html += f'<td style="{td_style} white-space:normal; line-height:1.3;"><a href="{link}" style="text-decoration:none; color:#334155; font-weight:600; font-size:13px;">{item["name"]}</a> {badge}<br><span style="color:#94a3b8; font-size:10px;">{item["code"]}</span><br><span style="color:#64748b; font-size:9px;">{item.get("industry","-")}</span></td>'
                html += f'<td style="{td_style} text-align:center;"><div style="color:#d97706; font-weight:700; font-size:12px;">{item.get("score", "-")}</div></td>'
                html += f'<td style="{td_style} font-size:11px; color:#475569; line-height:1.4;">{enrich.get("business", item.get("strategy"))}</td>'
                html += f'<td style="{td_style} text-align:center; font-weight:bold; color:#64748b; font-size:11px; white-space:nowrap;">{item["t_str"]}</td>'
                html += f'<td style="{td_style} text-align:right; font-size:10px; white-space:nowrap;"><div style="color:#94a3b8;">{item["rec_price"]:.2f}</div><div style="font-weight:bold; color:#334155; font-size:12px;">{item["price"]:.2f}</div></td>'
                html += f'<td style="{td_style} text-align:center; font-weight:bold; font-size:12px; color:{ret_color}; white-space:nowrap;">{ret:+.2f}%</td>'
                html += f'<td style="{td_style} text-align:center; font-size:11px; color:{idx_color}; background:#f8fafc; white-space:nowrap;">{idx_str}</td>'
                html += '</tr>'
            html += '</tbody></table></div>'
        else:
            html += '<div style="font-size:12px; color:#94a3b8; padding:10px; text-align:center;">暂无历史跟踪 (No Tracking Data)</div>'
        
        return html

    # Build Sections
    cn_html = render_market_section("🇨🇳 A-Share (沪深)", "cn_market", cn_candidates, cn_track)
    hk_html = render_market_section("🇭🇰 HK-Share (港股)", "hk_market", hk_candidates, hk_track)

    full_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {{ margin: 0; padding: 0; background-color: #ffffff; font-family: -apple-system, sans-serif; }}
        details > summary {{ list-style: none; }}
        details > summary::-webkit-details-marker {{ display: none; }}
    </style>
    </head>
    <body>
    <div style="font-family: 'Inter', -apple-system, sans-serif; max-width: 720px; margin: 0 auto; color: #1e293b; background: #ffffff;">
        <div style="text-align: center; padding: 30px 0 15px 0;">
            <div style="font-size: 24px; font-weight: 800; background: linear-gradient(135deg, #f59e0b, #d97706); -webkit-background-clip: text; -webkit-text-fill-color: transparent;">Daily Siphon v5.1</div>
            <div style="color: #64748b; font-size: 13px; margin-top: 5px; font-weight: 500;">{current_time} | 深度研报 (Deep Report)</div>
        </div>
        
        <div style="background: linear-gradient(to bottom right, #f8fafc, #ffffff); border: 1px solid #e2e8f0; border-radius: 12px; padding: 20px; margin: 10px 10px 20px 10px; box-shadow: 0 2px 4px -2px rgba(0,0,0,0.05);">
            <div style="font-weight: 700; color: #334155; font-size: 15px; display: flex; align-items: center; margin-bottom: 20px;">
                <span style="background:#dbeafe; width:8px; height:8px; border-radius:50%; margin-right:8px;"></span> 策略核心机制 (Mechanism)
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
            </div>
        </div>

        <!-- ACCORDION UI (Gmail Safe) -->
        
        <!-- A-Share Accordion (Default Open) -->
        <details open style="margin: 10px; border: 1px solid #e2e8f0; border-radius: 12px; background: #ffffff; overflow: hidden; box-shadow: 0 4px 6px -2px rgba(0,0,0,0.05);">
            <summary style="background: #f1f5f9; padding: 15px 20px; font-weight: 700; color: #334155; font-size: 16px; cursor: pointer; display: flex; justify-content: space-between; align-items: center;">
                <span>🇨🇳 A-Share (Click to Collapse)</span>
                <span style="color: #94a3b8; font-size: 12px;">▼</span>
            </summary>
            <div style="padding: 15px;">
                {cn_html}
            </div>
        </details>

        <!-- HK-Share Accordion (Click to Expand - Switching Feel) -->
        <!-- User wants "Switching". Stacked is default. Clicking opens it. This is switching visibility. -->
        <details style="margin: 10px; border: 1px solid #e2e8f0; border-radius: 12px; background: #ffffff; overflow: hidden; box-shadow: 0 4px 6px -2px rgba(0,0,0,0.05);">
            <summary style="background: #fdf2f8; padding: 15px 20px; font-weight: 700; color: #be185d; font-size: 16px; cursor: pointer; display: flex; justify-content: space-between; align-items: center;">
                <span>🇭🇰 HK-Share (Click to Expand)</span>
                <span style="color: #94a3b8; font-size: 12px;">►</span>
            </summary>
            <div style="padding: 15px;">
                {hk_html}
            </div>
        </details>

        <!-- Disclaimer -->
        <div style="margin: 30px 10px 10px 10px; padding: 15px; background: #fef2f2; border: 1px solid #fee2e2; border-radius: 8px; text-align: center;">
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
    </body>
    </html>
    """

    msg = MIMEText(full_html, 'html', 'utf-8')
    msg['From'] = Header("AI 参谋部", 'utf-8')
    msg['To'] = Header("Commander", 'utf-8')
    msg['Subject'] = Header(f"✨ 每日虹吸 v5.1: 深度研报 (HK Integration)", 'utf-8')
    try:
        smtp = smtplib.SMTP_SSL(MAIL_HOST, MAIL_PORT, timeout=30)
        smtp.login(MAIL_USER, MAIL_PASS)
        smtp.sendmail(MAIL_USER, MAIL_RECEIVERS, msg.as_string())
        smtp.quit()
        print("✅ Report sent successfully.")
    except Exception as e:
        print(f"❌ Email Error: {e}")

if __name__ == "__main__":
    generate_report()
