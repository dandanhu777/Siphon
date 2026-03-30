from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import pandas as pd
import numpy as np
import os, time, math, glob, json

# v11.0: Import shared scoring engine for backtest/live consistency
try:
    from scoring_engine import (
        precompute_static_factors_unified,
        calc_composite_score,
        detect_market_regime,
        get_confidence_grade,
    )
    USE_UNIFIED_SCORING = True
except ImportError:
    USE_UNIFIED_SCORING = False

app = FastAPI(title="Siphon Backtest Server")
_cache = {'bars_5min': {}, 'daily_klines': {}, 'stock_names': {}}
_last_result = {}

def preload_data():
    base_dir = r"C:\QuantTrade\data"
    print(f"Preloading data from {base_dir}...")
    for f in glob.glob(os.path.join(base_dir, "klines_5min", "*.parquet")):
        sym = os.path.basename(f).split('.')[0]
        df = pd.read_parquet(f); df['date'] = pd.to_datetime(df['date'])
        for c in ['open','high','low','close','volume']:
            if c in df.columns: df[c] = pd.to_numeric(df[c], errors='coerce')
        _cache['bars_5min'][sym] = df
    for f in glob.glob(os.path.join(base_dir, "klines", "*.parquet")):
        sym = os.path.basename(f).split('.')[0]
        df = pd.read_parquet(f); df['date'] = pd.to_datetime(df['date'])
        for c in ['open','high','low','close','volume']:
            if c in df.columns: df[c] = pd.to_numeric(df[c], errors='coerce')
        df = df.sort_values('date').ffill().fillna(0)
        _cache['daily_klines'][sym] = df
    
    # Load stock names
    name_file = os.path.join(base_dir, "stock_names.csv")
    if os.path.exists(name_file):
        ndf = pd.read_csv(name_file)
        for _, r in ndf.iterrows():
            _cache['stock_names'][str(r['code']).zfill(6)] = r['name']
    else:
        # Try to build from baostock
        try:
            import baostock as bs
            bs.login()
            rs = bs.query_stock_basic()
            rows = []
            while rs.error_code == '0' and rs.next():
                rows.append(rs.get_row_data())
            if rows:
                ndf = pd.DataFrame(rows, columns=rs.fields)
                for _, r in ndf.iterrows():
                    code = r['code'].split('.')[1] if '.' in str(r['code']) else str(r['code'])
                    _cache['stock_names'][code] = r.get('code_name', code)
                # Save for next time
                pd.DataFrame([{'code':k,'name':v} for k,v in _cache['stock_names'].items()]).to_csv(name_file, index=False)
                print(f"Built stock name map: {len(_cache['stock_names'])} stocks")
            bs.logout()
        except:
            print("Warning: Could not load stock names")
    
    print(f"Preload Done: {len(_cache['bars_5min'])} 5min, {len(_cache['daily_klines'])} daily, {len(_cache['stock_names'])} names.")

def get_stock_name(sym):
    name = _cache['stock_names'].get(sym, '')
    if not name:
        if sym.startswith('300'): return f"创业板{sym}"
        elif sym.startswith('688'): return f"科创板{sym}"
        elif sym.startswith('60'): return f"沪主板{sym}"
        elif sym.startswith('00'): return f"深主板{sym}"
        else: return sym
    return name

def get_board(sym):
    if sym.startswith('300'): return "创业板"
    elif sym.startswith('688'): return "科创板"
    elif sym.startswith('60'): return "沪主板"
    elif sym.startswith('00'): return "深主板"
    elif sym.startswith('51'): return "ETF"
    else: return "其他"

def precompute_static_factors(df_daily):
    """Legacy static factors. Use precompute_static_factors_unified when available."""
    if USE_UNIFIED_SCORING:
        return precompute_static_factors_unified(df_daily)
    if len(df_daily) < 10: return None
    close = df_daily['close'].values; high = df_daily['high'].values
    volume = df_daily['volume'].values; dates = df_daily['date'].values
    n = len(close)
    pct_3d = np.zeros(n); vol_ratio = np.ones(n)
    is_vcp = np.zeros(n, dtype=bool); avg_vol = np.zeros(n)
    for i in range(10, n):
        pct_3d[i] = (close[i]/close[i-3]-1)*100 if close[i-3]!=0 else 0
        v3 = np.mean(volume[i-2:i+1]); v5 = np.mean(volume[i-7:i-2])
        vol_ratio[i] = v3/(v5+1e-9)
        pk = np.argmax(high[i-9:i+1])
        is_vcp[i] = (pk<=4 and close[i]>close[i-1] and np.min(close[i-3:i])<(high[i-(9-pk)] if pk<10 else 99999))
        avg_vol[i] = np.mean(volume[i-4:i+1])
    df_f = pd.DataFrame({'date':dates,'last_close':close,'pct_3d':pct_3d,'vol_ratio':vol_ratio,'is_vcp':is_vcp,'avg_daily_vol':avg_vol})
    shrink = df_f['vol_ratio']<0.7
    df_f['ag_score_static'] = np.maximum(0,df_f['pct_3d'])*0.4+np.minimum(df_f['vol_ratio'],3.0)*10+df_f['is_vcp'].astype(int)*15+shrink.astype(int)*5
    return df_f

class BacktestRequest(BaseModel):
    start_date: str = "2025-01-01"
    end_date: str = "2025-12-31"
    hold_days: int = 5
    max_positions: int = 3
    params: dict = {}
    use_superstar: bool = False
    trailing_stop_pct: float = 0.0
    take_profit_pct: float = 0.0
    stop_loss_pct: float = 0.0

DEFAULT_PARAMS = {
    "w_ag": 0.35, "w_pct": 0.25, "w_vol": 0.25, "w_turn": 0.15,
    "min_pct": 0.3, "max_pct": 6.0, "min_turnover": 0.5,
}

@app.on_event("startup")
async def startup(): preload_data()

@app.get("/", response_class=HTMLResponse)
async def index():
    p = r"C:\QuantTrade\backtest_report.html"
    if os.path.exists(p):
        with open(p,'r',encoding='utf-8') as f: return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>No report. POST /api/backtest first.</h1>")

@app.get("/report", response_class=HTMLResponse)
async def report():
    p = r"C:\QuantTrade\backtest_report.html"
    if os.path.exists(p):
        with open(p,'r',encoding='utf-8') as f: return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>No report</h1>", status_code=404)

@app.get("/health")
async def health():
    return {"status":"ok","stocks_5min":len(_cache.get('bars_5min',{})),"stocks_daily":len(_cache.get('daily_klines',{}))}

@app.post("/api/backtest")
async def run_backtest(req: BacktestRequest):
    if not _cache: raise HTTPException(500,"Data not loaded")
    use_trailing = req.trailing_stop_pct > 0
    use_tpsl = req.take_profit_pct > 0 or req.stop_loss_pct > 0
    if use_tpsl: mode_str = f"TP={req.take_profit_pct}% SL={req.stop_loss_pct}%"
    elif use_trailing: mode_str = f"trailing={req.trailing_stop_pct}%"
    else: mode_str = f"hold={req.hold_days}d"
    print(f"\n[BT] {req.start_date}->{req.end_date} | superstar={req.use_superstar} | {mode_str}")

    stock_factors = {}
    for sym, dd in _cache['daily_klines'].items():
        f = precompute_static_factors(dd)
        if f is not None: stock_factors[sym] = f.set_index('date')

    bars_5min = _cache['bars_5min']
    p = {**DEFAULT_PARAMS, **req.params}
    t0 = time.time()
    start_dt = pd.to_datetime(req.start_date).date()
    end_dt = pd.to_datetime(req.end_date).date()
    all_dates = set()
    for df in bars_5min.values():
        sel = df[(df['date'].dt.date>=start_dt)&(df['date'].dt.date<=end_dt)]
        if not sel.empty: all_dates.update(sel['date'].dt.date)
    trade_dates = sorted(all_dates)
    if not trade_dates: return {"status":"error","error":"no dates"}

    cash, initial_cash = 1_000_000.0, 1_000_000.0
    commission, slip_bps = 0.00085, 5
    pos_size = initial_cash / req.max_positions
    portfolio = {}; daily_nav = []; trades = []; sell_queue = []

    def get_bar_at(df, td, suffix):
        m = df[df['time']==f"{td.strftime('%Y%m%d')}{suffix}"]
        return m.iloc[0] if len(m)>0 else None

    for td_idx, td in enumerate(trade_dates):
        if td_idx % 20 == 0:
            nav = daily_nav[-1]['nav'] if daily_nav else initial_cash
            print(f"  [{td}] ({td_idx}/{len(trade_dates)}) P:{len(portfolio)} NAV:{nav:.0f}")

        # === EXIT ===
        if use_tpsl:
            for sym in list(portfolio.keys()):
                pos = portfolio[sym]
                if sym not in bars_5min: continue
                df_5m = bars_5min[sym]
                today_bars = df_5m[df_5m['date'].dt.date == td]
                if today_bars.empty: continue
                
                ep = pos['ep']
                exit_reason = None
                
                # Walk through intraday bars to find exact trigger point
                for _, bar in today_bars.iterrows():
                    bar_high = float(bar['high'])
                    bar_low = float(bar['low'])
                    bar_close = float(bar['close'])
                    
                    # Check stop loss first (more urgent)
                    if req.stop_loss_pct > 0:
                        sl_price = ep * (1 - req.stop_loss_pct / 100)
                        if bar_low <= sl_price:
                            exit_reason = "stop_loss"
                            # Sell at the SL trigger price (or bar close if gap down)
                            sell_price = min(sl_price, float(bar['open']))
                            break
                    
                    # Check take profit
                    if req.take_profit_pct > 0:
                        tp_price = ep * (1 + req.take_profit_pct / 100)
                        if bar_high >= tp_price:
                            exit_reason = "take_profit"
                            # Sell at TP trigger price (or bar close if gap up)
                            sell_price = max(tp_price, float(bar['open']))
                            break
                
                if exit_reason:
                    # Update peak for stats
                    intraday_high = float(today_bars['high'].max())
                    peak = max(pos.get('peak_price', ep), intraday_high)
                    
                    sp = sell_price * (1 - slip_bps/10000)
                    profit_rmb = pos['shares'] * sp * (1 - commission) - pos['shares'] * ep * (1 + commission)
                    pnl = (sp / ep - 1) * 100
                    hold_days_actual = (td - pos['date']).days
                    trades.append({
                        "symbol": sym, "name": get_stock_name(sym), "board": get_board(sym),
                        "pnl_pct": round(pnl, 2), "profit_rmb": round(profit_rmb, 0),
                        "buy_date": str(pos['date']), "sell_date": str(td),
                        "buy_price": round(ep, 2), "sell_price": round(sp, 2),
                        "shares": pos['shares'], "hold_days": hold_days_actual,
                        "exit_reason": exit_reason,
                        "peak_gain": round((peak/ep-1)*100, 2),
                        "score": pos.get('score', 0),
                    })
                    cash += pos['shares'] * sp * (1 - commission)
                    del portfolio[sym]
                else:
                    # Update peak price tracking
                    intraday_high = float(today_bars['high'].max())
                    portfolio[sym]['peak_price'] = max(pos.get('peak_price', ep), intraday_high)
                    
        elif use_trailing:
            for sym in list(portfolio.keys()):
                pos = portfolio[sym]
                if sym not in bars_5min: continue
                df_5m = bars_5min[sym]; today_bars = df_5m[df_5m['date'].dt.date==td]
                if today_bars.empty: continue
                intraday_high = float(today_bars['high'].max())
                current_close = float(today_bars.iloc[-1]['close'])
                new_peak = max(pos.get('peak_price',pos['ep']), intraday_high)
                portfolio[sym]['peak_price'] = new_peak
                dd_pct = (new_peak-current_close)/new_peak*100
                if dd_pct >= req.trailing_stop_pct:
                    sp = current_close*(1-slip_bps/10000)
                    profit_rmb = pos['shares']*sp*(1-commission)-pos['shares']*pos['ep']*(1+commission)
                    trades.append({"symbol":sym,"name":get_stock_name(sym),"board":get_board(sym),
                        "pnl_pct":round((sp/pos['ep']-1)*100,2),"profit_rmb":round(profit_rmb,0),
                        "buy_date":str(pos['date']),"sell_date":str(td),
                        "buy_price":round(pos['ep'],2),"sell_price":round(sp,2),
                        "shares":pos['shares'],"hold_days":(td-pos['date']).days,
                        "exit_reason":"trailing_stop","peak_gain":round((new_peak/pos['ep']-1)*100,2),
                        "score":pos.get('score',0)})
                    cash += pos['shares']*sp*(1-commission); del portfolio[sym]
        else:
            for sq in list(sell_queue):
                sq_date,sym,shares,ep = sq
                if td>=sq_date:
                    bar=get_bar_at(bars_5min[sym],td,"093500000")
                    sp=(float(bar['open']) if bar is not None else ep)*(1-slip_bps/10000)
                    profit_rmb=shares*sp*(1-commission)-shares*ep*(1+commission)
                    trades.append({"symbol":sym,"name":get_stock_name(sym),"board":get_board(sym),
                        "pnl_pct":round((sp/ep-1)*100,2),"profit_rmb":round(profit_rmb,0),
                        "buy_date":"","sell_date":str(td),"buy_price":round(ep,2),"sell_price":round(sp,2),
                        "shares":shares,"hold_days":0,"exit_reason":"fixed_hold","peak_gain":0,"score":0})
                    cash+=shares*sp*(1-commission)
                    if sym in portfolio: del portfolio[sym]
                    sell_queue.remove(sq)

        # === NAV ===
        pv = cash
        for sym, pos in portfolio.items():
            bar = get_bar_at(bars_5min[sym], td, "093500000")
            pv += pos["shares"]*(float(bar['close']) if bar is not None else pos["ep"])
        daily_nav.append({"date":td,"nav":pv})

        # === ENTRY ===
        if len(portfolio) < req.max_positions:
            signals = []
            for sym in bars_5min:
                if sym in portfolio: continue
                df_5m = bars_5min[sym]
                bar_0940 = get_bar_at(df_5m, td, "094000000")
                bar_0935 = get_bar_at(df_5m, td, "093500000")
                if bar_0940 is None or bar_0935 is None: continue
                fac_df = stock_factors.get(sym)
                if fac_df is None: continue
                idx = fac_df.index.searchsorted(pd.Timestamp(td))
                if idx == 0: continue
                static = fac_df.iloc[idx-1]
                prev_close = static['last_close']
                if prev_close <= 0: continue
                pct_chg = (float(bar_0940['close'])-prev_close)/prev_close*100
                vol_early = float(bar_0935['volume'])+float(bar_0940['volume'])
                expected = static['avg_daily_vol']*(10/240)
                vr = vol_early/(expected+1e-9)
                turnover = vol_early/(static['avg_daily_vol']+1e-9)*48
                if pct_chg<p['min_pct'] or pct_chg>p['max_pct']: continue
                if vol_early<50000 or turnover<p['min_turnover']: continue
                def mm(v,lo,hi): return max(0,min(100,(v-lo)/(hi-lo)*100)) if hi!=lo else 50
                score = (mm(static['ag_score_static'],0,50)*p['w_ag']+mm(pct_chg,p['min_pct'],p['max_pct'])*p['w_pct']+mm(min(vr,10),0,10)*p['w_vol']+mm(min(turnover,20),0,20)*p['w_turn']+(10 if static['is_vcp'] else 0))
                if req.use_superstar and (score>56.0 or prev_close>=50.0): continue
                signals.append({"symbol":sym,"score":round(score,2),"pct_chg":round(pct_chg,2),"vol_ratio":round(vr,2)})

            signals.sort(key=lambda x:x['score'],reverse=True)
            avail = req.max_positions - len(portfolio)
            for sig in signals[:avail]:
                sym = sig['symbol']
                bar_1000 = get_bar_at(bars_5min[sym], td, "100000000")
                if bar_1000 is None: continue
                bp = float(bar_1000['open'])*(1+slip_bps/10000)
                shares = int(pos_size/bp/100)*100
                if shares<=0: continue
                cost = shares*bp*(1+commission)
                if cost>cash: continue
                cash -= cost
                portfolio[sym] = {"shares":shares,"ep":bp,"date":td,"peak_price":bp,"score":sig['score']}
                if not use_trailing and not use_tpsl:
                    sell_idx = td_idx+req.hold_days
                    sell_td = trade_dates[min(sell_idx,len(trade_dates)-1)]
                    sell_queue.append((sell_td,sym,shares,bp))

    # Close remaining
    for sym, pos in portfolio.items():
        cash += pos["shares"]*pos["ep"]
        trades.append({"symbol":sym,"name":get_stock_name(sym),"board":get_board(sym),
            "pnl_pct":0.0,"profit_rmb":0,"buy_date":str(pos['date']),"sell_date":"持有中",
            "buy_price":round(pos['ep'],2),"sell_price":round(pos['ep'],2),
            "shares":pos['shares'],"hold_days":(trade_dates[-1]-pos['date']).days,
            "exit_reason":"end_of_period","peak_gain":0,"score":pos.get('score',0)})

    navs = pd.DataFrame(daily_nav)
    if len(navs)<2: return {"status":"error","error":"insufficient data"}
    navs["ret"] = navs["nav"].pct_change().dropna()
    total_pnl = (navs["nav"].iloc[-1]/initial_cash-1)*100
    ann_ret = (navs["nav"].iloc[-1]/initial_cash)**(1/(len(trade_dates)/252))-1
    dr = navs["ret"].dropna()
    sharpe = (dr.mean()/dr.std()*math.sqrt(252)) if dr.std()>0 else 0
    dd = ((navs["nav"]-navs["nav"].cummax())/navs["nav"].cummax()).min()
    wr = sum(1 for t in trades if t["pnl_pct"]>0)/len(trades) if trades else 0
    tp_count = sum(1 for t in trades if t.get('exit_reason')=='take_profit')
    sl_count = sum(1 for t in trades if t.get('exit_reason')=='stop_loss')
    total_profit = sum(t.get('profit_rmb',0) for t in trades)

    elapsed = time.time()-t0
    print(f"BT Done: PnL={total_pnl:.2f}% | Sharpe={sharpe:.2f} | Trades={len(trades)} | TP={tp_count} SL={sl_count} | {elapsed:.0f}s")
    
    result = {
        "status":"done","sharpe_ratio":round(float(sharpe),4),"max_drawdown":round(float(dd),4),
        "win_rate":round(float(wr),4),"total_trades":len(trades),"annualized_return":round(float(ann_ret),4),
        "total_pnl_pct":round(float(total_pnl),2),"trade_dates":len(trade_dates),"elapsed_sec":round(elapsed,1),
        "mode":mode_str,"tp_count":tp_count,"sl_count":sl_count,"total_profit_rmb":round(total_profit,0),
        "trades":trades,
    }
    generate_report(result, req)
    return result

def generate_report(result, req):
    trades = result.get('trades', [])
    tp = result.get('tp_count',0); sl = result.get('sl_count',0); total = result.get('total_trades',0)
    total_profit = result.get('total_profit_rmb',0)
    
    trade_rows = ""
    for i, t in enumerate(trades, 1):
        pnl = t.get('pnl_pct', 0)
        pnl_class = 'pos' if pnl > 0 else 'neg' if pnl < 0 else ''
        profit = t.get('profit_rmb', 0)
        profit_class = 'pos' if profit > 0 else 'neg' if profit < 0 else ''
        reason = t.get('exit_reason','')
        reason_map = {'take_profit':'🟢止盈','stop_loss':'🔴止损','trailing_stop':'🟡追踪','end_of_period':'⚪持有中','fixed_hold':'🔵到期'}
        reason_cn = reason_map.get(reason, reason)
        name = t.get('name', t.get('symbol',''))
        board = t.get('board','')
        score = t.get('score', 0)
        peak = t.get('peak_gain', 0)
        
        trade_rows += f"""<tr data-reason="{reason}" data-board="{board}" data-sym="{t.get('symbol','')}">
<td>{i}</td><td class="sym-cell"><strong>{t.get('symbol','')}</strong><br><span class="name-tag">{name}</span></td>
<td><span class="board-tag board-{board}">{board}</span></td>
<td>{t.get('buy_date','')}</td><td>¥{t.get('buy_price',0):.2f}</td>
<td>{t.get('sell_date','')}</td><td>¥{t.get('sell_price',0):.2f}</td>
<td>{t.get('shares',0)}</td><td>{t.get('hold_days',0)}</td>
<td class="{pnl_class}" data-val="{pnl}">{pnl:+.2f}%</td>
<td class="{profit_class}" data-val="{profit}">¥{profit:+,.0f}</td>
<td data-val="{peak}">{peak:+.2f}%</td>
<td data-val="{score}">{score:.1f}</td>
<td>{reason_cn}</td></tr>\n"""

    # Board distribution
    boards = {}
    for t in trades:
        b = t.get('board','其他')
        if b not in boards: boards[b] = {'count':0,'profit':0,'wins':0}
        boards[b]['count'] += 1
        boards[b]['profit'] += t.get('profit_rmb',0)
        if t.get('pnl_pct',0) > 0: boards[b]['wins'] += 1
    
    board_rows = ""
    for b, s in sorted(boards.items(), key=lambda x:-x[1]['count']):
        wr = s['wins']/s['count']*100 if s['count']>0 else 0
        pc = 'pos' if s['profit']>0 else 'neg'
        board_rows += f"<tr><td>{b}</td><td>{s['count']}</td><td>{wr:.1f}%</td><td class='{pc}'>¥{s['profit']:+,.0f}</td></tr>\n"
    
    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>虹吸策略 盲测报告</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
:root {{--bg:#0f1117;--surface:#1a1d27;--surface2:#22263a;--border:#2d3348;--text:#e4e6ef;--text2:#8b8fa3;--accent:#6c5ce7;--green:#00d68f;--red:#ff6b6b;--gold:#ffd93d;--blue:#4ecdc4;}}
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{font-family:'Inter',-apple-system,sans-serif;background:var(--bg);color:var(--text);line-height:1.6;padding:16px;}}
.container{{max-width:1400px;margin:0 auto;}}
.header{{text-align:center;padding:30px 20px;background:linear-gradient(135deg,#1a1d27,#2d1b69,#1a1d27);border-radius:16px;margin-bottom:20px;border:1px solid var(--border);}}
.header h1{{font-size:24px;font-weight:700;background:linear-gradient(135deg,#a78bfa,#6c5ce7,#4ecdc4);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;}}
.header .sub{{color:var(--text2);font-size:13px;margin-top:4px;}}
.header .badge{{display:inline-block;margin-top:8px;padding:4px 12px;background:rgba(108,92,231,0.2);border:1px solid var(--accent);border-radius:20px;font-size:11px;color:var(--accent);}}
.kpi-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:20px;}}
.kpi{{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:16px;text-align:center;}}
.kpi .kv{{font-size:24px;font-weight:700;}}.kpi .kl{{font-size:11px;color:var(--text2);margin-top:2px;}}
.section{{margin-bottom:20px;}}.section-title{{font-size:16px;font-weight:600;margin-bottom:10px;padding-left:10px;border-left:3px solid var(--accent);}}
table{{width:100%;border-collapse:collapse;background:var(--surface);border-radius:10px;overflow:hidden;font-size:12px;}}
thead th{{background:var(--surface2);padding:8px 6px;text-align:center;font-size:10px;font-weight:600;color:var(--text2);text-transform:uppercase;cursor:pointer;user-select:none;white-space:nowrap;}}
thead th:hover{{background:var(--accent);color:white;}}
tbody td{{padding:6px;text-align:center;border-top:1px solid var(--border);}}
.pos{{color:var(--green);font-weight:600;}}.neg{{color:var(--red);font-weight:600;}}
.sym-cell{{text-align:left !important;min-width:100px;}}.name-tag{{font-size:10px;color:var(--text2);}}
.board-tag{{font-size:10px;padding:2px 6px;border-radius:4px;white-space:nowrap;}}
.board-创业板{{background:rgba(255,107,107,0.15);color:var(--red);}}.board-科创板{{background:rgba(78,205,196,0.15);color:var(--blue);}}
.board-沪主板{{background:rgba(108,92,231,0.15);color:var(--accent);}}.board-深主板{{background:rgba(255,217,61,0.15);color:var(--gold);}}
.board-ETF{{background:rgba(139,143,163,0.15);color:var(--text2);}}
.toolbar{{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px;align-items:center;}}
.search-box{{padding:6px 12px;border-radius:8px;border:1px solid var(--border);background:var(--surface);color:var(--text);font-size:12px;width:200px;}}
.filter-btn{{padding:5px 12px;border-radius:8px;border:1px solid var(--border);background:var(--surface);color:var(--text);cursor:pointer;font-size:11px;transition:all 0.2s;}}
.filter-btn:hover,.filter-btn.active{{background:var(--accent);border-color:var(--accent);color:white;}}
.sort-arrow{{font-size:8px;margin-left:2px;}}
.footer{{text-align:center;padding:16px;color:var(--text2);font-size:11px;}}
@media(max-width:768px){{.kpi-grid{{grid-template-columns:repeat(3,1fr);}}.container{{padding:8px;}}}}
</style></head><body><div class="container">
<div class="header">
<h1>🔬 虹吸策略 — 盲测回测报告</h1>
<div class="sub">{req.start_date} → {req.end_date} · {'超模标的' if req.use_superstar else '全部标的'} · {len(_cache['bars_5min'])} 只股票</div>
<div class="badge">{'止盈+'+str(req.take_profit_pct)+'% · 止损-'+str(req.stop_loss_pct)+'%' if req.take_profit_pct>0 else ('追踪止损'+str(req.trailing_stop_pct)+'%' if req.trailing_stop_pct>0 else '固定持有'+str(req.hold_days)+'天')}</div>
</div>

<div class="kpi-grid">
<div class="kpi"><div class="kv {'pos' if result['total_pnl_pct']>0 else 'neg'}">{result['total_pnl_pct']:+.2f}%</div><div class="kl">总收益率</div></div>
<div class="kpi"><div class="kv {'pos' if total_profit>0 else 'neg'}">¥{total_profit:+,.0f}</div><div class="kl">总盈亏(元)</div></div>
<div class="kpi"><div class="kv">{result['sharpe_ratio']:.2f}</div><div class="kl">夏普比率</div></div>
<div class="kpi"><div class="kv neg">{result['max_drawdown']*100:.1f}%</div><div class="kl">最大回撤</div></div>
<div class="kpi"><div class="kv">{result['win_rate']*100:.1f}%</div><div class="kl">胜率</div></div>
<div class="kpi"><div class="kv">{total}</div><div class="kl">总交易</div></div>
<div class="kpi"><div class="kv pos">{tp}</div><div class="kl">止盈次数</div></div>
<div class="kpi"><div class="kv neg">{sl}</div><div class="kl">止损次数</div></div>
</div>

<div class="section"><div class="section-title">📊 板块分布</div>
<table><thead><tr><th>板块</th><th>交易次数</th><th>胜率</th><th>盈亏(元)</th></tr></thead>
<tbody>{board_rows}</tbody></table></div>

<div class="section"><div class="section-title">📋 全部交易记录 ({total} 笔)</div>
<div class="toolbar">
<input type="text" class="search-box" id="searchBox" placeholder="🔍 搜索代码/名称..." oninput="filterTable()">
<button class="filter-btn active" onclick="setFilter('all',this)">全部({total})</button>
<button class="filter-btn" onclick="setFilter('take_profit',this)">🟢止盈({tp})</button>
<button class="filter-btn" onclick="setFilter('stop_loss',this)">🔴止损({sl})</button>
<button class="filter-btn" onclick="setFilter('创业板',this)">创业板</button>
<button class="filter-btn" onclick="setFilter('科创板',this)">科创板</button>
<button class="filter-btn" onclick="setFilter('沪主板',this)">沪主板</button>
</div>
<div style="overflow-x:auto;">
<table id="tradesTable"><thead><tr>
<th onclick="sortTable(0)">#</th>
<th onclick="sortTable(1)">代码/名称</th>
<th onclick="sortTable(2)">板块</th>
<th onclick="sortTable(3)">买入日期</th>
<th onclick="sortTable(4)">买入价</th>
<th onclick="sortTable(5)">卖出日期</th>
<th onclick="sortTable(6)">卖出价</th>
<th onclick="sortTable(7)">股数</th>
<th onclick="sortTable(8)">持有天数</th>
<th onclick="sortTable(9)">盈亏%</th>
<th onclick="sortTable(10)">盈亏(元)</th>
<th onclick="sortTable(11)">最高涨幅</th>
<th onclick="sortTable(12)">虹吸分</th>
<th onclick="sortTable(13)">类型</th>
</tr></thead><tbody>{trade_rows}</tbody></table></div></div>

<div class="footer">虹吸短线精选 v10.1.0 · {time.strftime('%Y-%m-%d %H:%M')} · {result['elapsed_sec']:.0f}s</div>
</div>
<script>
let currentFilter='all';let sortCol=-1;let sortAsc=true;
function setFilter(f,btn){{currentFilter=f;document.querySelectorAll('.filter-btn').forEach(b=>b.classList.remove('active'));btn.classList.add('active');filterTable();}}
function filterTable(){{const q=document.getElementById('searchBox').value.toLowerCase();document.querySelectorAll('#tradesTable tbody tr').forEach(r=>{{let show=true;if(currentFilter!=='all'){{const reason=r.dataset.reason||'';const board=r.dataset.board||'';if(['take_profit','stop_loss','trailing_stop'].includes(currentFilter))show=reason===currentFilter;else show=board===currentFilter;}}if(show&&q){{const sym=r.dataset.sym||'';const txt=r.textContent.toLowerCase();show=txt.includes(q);}}r.style.display=show?'':'none';}});}}
function sortTable(col){{const tb=document.getElementById('tradesTable').tBodies[0];const rows=Array.from(tb.rows);if(sortCol===col)sortAsc=!sortAsc;else{{sortCol=col;sortAsc=true;}}rows.sort((a,b)=>{{let av=a.cells[col].getAttribute('data-val')||a.cells[col].textContent.replace(/[¥,%+,]/g,'');let bv=b.cells[col].getAttribute('data-val')||b.cells[col].textContent.replace(/[¥,%+,]/g,'');const an=parseFloat(av),bn=parseFloat(bv);if(!isNaN(an)&&!isNaN(bn))return sortAsc?an-bn:bn-an;return sortAsc?String(av).localeCompare(String(bv)):String(bv).localeCompare(String(av));}});rows.forEach(r=>tb.appendChild(r));}}
</script></body></html>"""
    
    with open(r"C:\QuantTrade\backtest_report.html", 'w', encoding='utf-8') as f:
        f.write(html)
    print("Report generated -> C:\\QuantTrade\\backtest_report.html")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
