
import akshare as ak
import pandas as pd
import datetime
import time
import os
import pickle

# Reuse Siphon Strategy Constants
TARGET_INDUSTRIES = [
    '半导体', '电子元件', '光学光电子', 
    '通信设备', '计算机设备', '软件开发', '互联网服务',
    '光伏设备', '风电设备', '电网设备', '电池' 
]
MIN_MARKET_CAP = 100 * 10000 * 10000

# Date Range
BACKTEST_START = "2025-04-01"
BACKTEST_DAYS = 30
DATA_START = "20250101"
DATA_END = "20250701"

CACHE_DIR = "backtest_cache"
if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR)

# --- Helpers ---
def load_index_data():
    cache_file = os.path.join(CACHE_DIR, "index_data.pkl")
    if os.path.exists(cache_file):
        with open(cache_file, 'rb') as f: return pickle.load(f)
    
    print("Fetching Index Data...")
    df = ak.stock_zh_index_daily(symbol="sh000001")
    df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
    df = df[(df['date'] >= "2025-01-01") & (df['date'] <= "2025-07-01")]
    df = df.set_index('date')
    df['Index_Change'] = df['close'].pct_change() * 100
    
    with open(cache_file, 'wb') as f: pickle.dump(df, f)
    return df

def get_target_stocks():
    siphon_cache = "data_cache/siphon_fetch_basic_pool__.pkl"
    if os.path.exists(siphon_cache):
        print(f"Loading cached pool from {siphon_cache}...")
        with open(siphon_cache, 'rb') as f:
            df = pickle.load(f)
            return df[['Symbol', 'Name', 'Industry']].to_dict('records')
    return []

def fetch_stock_history_batch(stocks):
    full_data = {}
    print(f"Fetching history for {len(stocks)} stocks (Sequential)...")
    
    count = 0
    total = min(len(stocks), 400)
    stocks = stocks[:400]
    
    for stock in stocks:
        count += 1
        symbol = stock['Symbol']
        cache_path = os.path.join(CACHE_DIR, f"hist_{symbol}.pkl")
        
        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'rb') as f:
                    full_data[symbol] = pickle.load(f)
                    continue
            except: pass
            
        try:
            if symbol.startswith('6'): prefix = 'sh'
            elif symbol.startswith('0') or symbol.startswith('3'): prefix = 'sz'
            else: prefix = ''
            
            if count % 10 == 0:
                print(f"Progress: {count}/{total} ({(count/total)*100:.1f}%)", end="\r")
            
            df = ak.stock_zh_a_daily(symbol=f"{prefix}{symbol}", start_date=DATA_START, end_date=DATA_END)
            if not df.empty:
                df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
                df = df.set_index('date')
                df['change_pct'] = df['close'].pct_change() * 100
                df['volume'] = pd.to_numeric(df['volume'], errors='coerce')
                
                with open(cache_path, 'wb') as f: pickle.dump(df, f)
                full_data[symbol] = df
            
            time.sleep(0.05)
        except Exception as e:
            pass
                
    return full_data

# --- v3.5 Enhanced Strategy Logic ---
def calc_score(stock_df, index_df, current_date):
    """
    v3.5 Improvements over v3.1:
    1. MA50 instead of MA60 (more flexible)
    2. Liquidity check (avg volume)
    3. Consecutive resilience bonus
    4. Refined scoring
    """
    stock_hist = stock_df[stock_df.index <= current_date]
    if len(stock_hist) < 60: return 0, ""  # Still need 60 days for MA50 calc
    
    common_dates = stock_hist.index.intersection(index_df.index)
    if len(common_dates) < 5: return 0, ""
    
    recent = stock_hist.tail(20)
    latest = recent.iloc[-1]
    latest_price = latest['close']
    
    # MAs
    ma20 = recent['close'].tail(20).mean()
    ma50 = stock_hist['close'].tail(50).mean()  # v3.5: Changed from MA60
    
    # v3.5 Enhancement 1: Relaxed Trend Filter (MA50)
    if latest_price < ma50: return 0, "Downtrend"
    
    # v3.5 Enhancement 2: Liquidity Gate
    avg_volume_20 = recent['volume'].tail(20).mean()
    if pd.notna(avg_volume_20) and avg_volume_20 < 1000000:  # Min 1M shares/day
        return 0, "Illiquid"
    
    # Anti-Chase
    last_5_change = recent['change_pct'].tail(5).sum()
    if last_5_change > 20: return 0, "Chased"
    
    # Siphon Logic
    score = 0
    details = []
    
    idx_subset = index_df.loc[common_dates].tail(10)
    stk_subset = stock_hist.loc[common_dates].tail(10)
    down_days = idx_subset[idx_subset['Index_Change'] < -0.3]
    
    siphon_points = 0
    consecutive_resilience = 0
    
    for date, row in down_days.iterrows():
        idx_chg = row['Index_Change']
        stk_chg = stk_subset.loc[date]['change_pct']
        
        if stk_chg > 0:
            siphon_points += 2
            consecutive_resilience += 1
            details.append("逆势")
        elif stk_chg > idx_chg + 1.5:
            siphon_points += 1
            consecutive_resilience += 1
            details.append("抗跌")
        else:
            consecutive_resilience = 0  # Reset if not resilient
            
    if siphon_points == 0: return 0, "No Resilience"
    score += siphon_points

    # v3.5 Enhancement 3: Consecutive Resilience Bonus
    if consecutive_resilience >= 2:
        score += 1
        details.append("连续抗跌")

    # MA Support
    if latest_price > ma20 and latest_price < ma20 * 1.05:
        score += 2
        details.append("MA20撑")
        
    return score, " ".join(details)

# --- Main Simulation ---
def run_backtest():
    index_df = load_index_data()
    target_list = get_target_stocks()
    stock_data = fetch_stock_history_batch(target_list)
    
    all_dates = sorted(index_df.index.unique())
    start_idx = -1
    for i, d in enumerate(all_dates):
        if d >= BACKTEST_START:
            start_idx = i
            break
            
    if start_idx == -1:
        print("No valid dates found")
        return None

    sim_dates = all_dates[start_idx : start_idx + BACKTEST_DAYS]
    
    results = []
    
    print(f"\n=== Starting Backtest v3.5 ({BACKTEST_START}, {BACKTEST_DAYS} Days) ===")
    
    total_wins = 0
    total_recs = 0
    
    for sim_date in sim_dates:
        print(f"Testing {sim_date}...", end="\r")
        daily_scores = []
        
        # Screen
        for stock in target_list:
            sym = stock['Symbol']
            if sym not in stock_data: continue
            
            df = stock_data[sym]
            if sim_date not in df.index: continue
            
            row = df.loc[sim_date]
            if row['change_pct'] > 9.5: continue
            
            score, logic = calc_score(df, index_df, sim_date)
            # v3.5: Raised threshold from 4 to 5 for better quality
            if score >= 5:
                daily_scores.append({
                    'Symbol': sym, 'Name': stock['Name'], 
                    'Score': score, 'Price': row['close'],
                    'Logic': logic
                })
        
        # Rank & Pick Top 3
        daily_scores.sort(key=lambda x: x['Score'], reverse=True)
        top_3 = daily_scores[:3]
        
        # Evaluate (T+10)
        for pick in top_3:
            sym = pick['Symbol']
            df = stock_data[sym]
            
            future_dates = [d for d in all_dates if d > sim_date]
            future_dates = future_dates[:10]
            
            if not future_dates: continue
            
            start_price = pick['Price']
            
            periods_df = df.loc[df.index.isin(future_dates)]
            if periods_df.empty: 
                final_ret = 0
                max_ret = 0
            else:
                final_price = periods_df.iloc[-1]['close']
                max_price = periods_df['close'].max()
                
                final_ret = (final_price - start_price) / start_price * 100
                max_ret = (max_price - start_price) / start_price * 100
                
            is_win = final_ret > 0
            grade = "Gold" if final_ret > 15 else ("Silver" if final_ret > 5 else ("Loss" if final_ret < 0 else "Flat"))
            
            if is_win: total_wins += 1
            total_recs += 1
            
            results.append({
                'Date': sim_date,
                'Stock': pick['Name'],
                'Code': sym,
                'Start': start_price,
                'Score': pick['Score'],
                'Final%': round(final_ret, 2),
                'Max%': round(max_ret, 2),
                'Grade': grade
            })
            
    # Summary
    print("\n" + "="*50)
    print(f"BACKTEST RESULTS v3.5 ({BACKTEST_START})")
    print("="*50)
    
    if total_recs > 0:
        win_rate = (total_wins / total_recs) * 100
        print(f"Total Recommendations: {total_recs}")
        print(f"Win Rate (>0%): {win_rate:.1f}%")
    else:
        print("No recommendations made.")
        
    res_df = pd.DataFrame(results)
    if not res_df.empty:
        print("\nTOP PERFORMERS:")
        print(res_df[res_df['Final%'] > 10][['Date','Stock','Final%','Max%']])
        
        csv_path = "backtest_result_v35.csv"
        res_df.to_csv(csv_path, index=False, encoding='utf-8-sig')
        print(f"\nDetailed results saved to {csv_path}")
        
    return res_df

if __name__ == "__main__":
    # Multi-month validation
    months_to_test = [
        ("2025-03-01", "March"),
        ("2025-04-01", "April"),
        ("2025-05-01", "May"),
        ("2025-06-01", "June"),
        ("2025-07-01", "July")
    ]
    
    all_results = []
    
    print("="*60)
    print("MULTI-PERIOD VALIDATION (v3.5 Refined Strategy)")
    print("="*60)
    
    for start_date, month_name in months_to_test:
        print(f"\n>>> Testing {month_name} 2025 <<<")
        BACKTEST_START = start_date
        result_df = run_backtest()
        
        if result_df is not None and not result_df.empty:
            wins = len(result_df[result_df['Final%'] > 0])
            total = len(result_df)
            win_rate = (wins/total*100) if total > 0 else 0
            avg_return = result_df['Final%'].mean()
            
            all_results.append({
                'Month': month_name,
                'Total': total,
                'Wins': wins,
                'WinRate': round(win_rate, 1),
                'AvgReturn': round(avg_return, 2)
            })
        else:
            all_results.append({
                'Month': month_name,
                'Total': 0,
                'Wins': 0,
                'WinRate': 0,
                'AvgReturn': 0
            })
    
    # Summary Report
    print("\n" + "="*60)
    print("AGGREGATE RESULTS (5-Month v3.5 Validation)")
    print("="*60)
    
    summary_df = pd.DataFrame(all_results)
    print(summary_df.to_string(index=False))
    
    if not summary_df.empty and summary_df['Total'].sum() > 0:
        active_months = summary_df[summary_df['Total'] > 0]
        if not active_months.empty:
            overall_win_rate = active_months['WinRate'].mean()
            print(f"\n>>> Overall Average Win Rate: {overall_win_rate:.1f}%")
            print(f">>> Win Rate Std Dev: {active_months['WinRate'].std():.1f}%")
            print(f">>> Best Month: {active_months.loc[active_months['WinRate'].idxmax(), 'Month']} ({active_months['WinRate'].max():.1f}%)")
            print(f">>> Worst Month: {active_months.loc[active_months['WinRate'].idxmin(), 'Month']} ({active_months['WinRate'].min():.1f}%)")
            
            # Compare with v3.1
            print("\n" + "="*60)
            print("COMPARISON: v3.5 vs v3.1")
            print("="*60)
            print("v3.1 Baseline: 56.8% avg (±12.1%), 176 total trades")
            print(f"v3.5 Result:   {overall_win_rate:.1f}% avg (±{active_months['WinRate'].std():.1f}%), {active_months['Total'].sum()} total trades")
    
    summary_df.to_csv("backtest_summary_v35_multi_month.csv", index=False)
    print("\nSummary saved to backtest_summary_v35_multi_month.csv")
