# 虹吸分 v6.0 短线动量套利模型 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将虹吸分模型从防守型（抗跌+安全边际）重构为进攻型短线动量套利模型（爆发力+资金+加速度）。

**Architecture:** 重写 `calc_composite_score` 权重体系，新增3个评分函数（量能爆发度、动量加速度、板块领涨度），改造相对强度时间窗口，去掉安全边际和VCP硬过滤，放宽入选门槛。

**Tech Stack:** Python, pandas, akshare (现有依赖不变)

**Source File:** `siphon_strategy.py` (883 lines, single file project)

---

### Task 0: 备份当前版本

**Files:**
- Copy: `siphon_strategy.py` → `siphon_strategy_v5_backup.py`

**Step 1: 备份文件**

```bash
cp siphon_strategy.py siphon_strategy_v5_backup.py
```

**Step 2: 确认备份**

```bash
diff siphon_strategy.py siphon_strategy_v5_backup.py
```

Expected: 无输出（文件完全一致）

**Step 3: Commit**

```bash
git add siphon_strategy_v5_backup.py
git commit -m "backup: save siphon_strategy v5.0 before v6.0 aggressive rewrite"
```

---

### Task 1: 更新 StrategyConfig 配置

**Files:**
- Modify: `siphon_strategy.py:31-59`

**Step 1: 修改 StrategyConfig**

将 `StrategyConfig` 替换为 v6.0 配置。关键变更：
- `max_rsi`: 75.0 → 80.0（允许更强势股票）
- `max_gain_5d`: 15.0 → 25.0（放宽5日涨幅限制）
- `max_swing_3d`: 10.0 → 15.0（放宽3日波动限制）
- 去掉 `max_atr_pct`（不再过滤波动率）
- `min_composite_score`: 40.0 → 30.0（降低入选门槛）
- `min_ag_score`: 5.0 → 2.0（降低抗跌最低分）
- 新增 `vol_explosion_multiplier`: 2.0（量能爆发倍数阈值）

```python
@dataclass
class StrategyConfig:
    """v6.0: Aggressive short-term momentum arbitrage config."""
    # Filtering thresholds (relaxed for momentum)
    max_drop_pct: float = -3.0
    max_gain_5d: float = 25.0         # Relaxed from 15.0
    max_rsi: float = 80.0             # Relaxed from 75.0
    limit_up_threshold: float = 8.5
    max_swing_3d: float = 15.0        # Relaxed from 10.0
    # Fundamental filters
    min_growth: float = 10.0
    high_growth: float = 30.0
    max_peg: float = 1.5
    # Technical filters
    ma_period: int = 50
    min_avg_volume: int = 1_000_000
    vcp_vol_ratio: float = 0.6
    vcp_steady_ratio: float = 1.5
    # Scoring
    min_ag_score: float = 2.0         # Lowered from 5.0
    min_composite_score: float = 30.0 # Lowered from 40.0
    sector_momentum_pct: float = 0.4
    # v6.0: Momentum params
    vol_explosion_multiplier: float = 2.0  # Volume explosion threshold
    # Processing
    max_process: int = 300
```

**Step 2: Commit**

```bash
git add siphon_strategy.py
git commit -m "feat(v6): update StrategyConfig for aggressive momentum model"
```

---

### Task 2: 新增 `calc_volume_explosion()` 函数（20分）

**Files:**
- Modify: `siphon_strategy.py` — 在 `calc_safety_margin` 函数后插入新函数

**Step 1: 在 `calc_safety_margin` 函数之后添加新函数**

```python
def calc_volume_explosion(stock_hist):
    """v6.0: Volume explosion scoring (0-20).
    Measures today's volume vs 5-day average.
    Core signal for short-term momentum ignition.
    """
    if len(stock_hist) < 6:
        return 0.0, 1.0

    today_vol = stock_hist['volume'].iloc[-1]
    ma5_vol = stock_hist['volume'].iloc[-6:-1].mean()

    if ma5_vol <= 0:
        return 0.0, 1.0

    vol_ratio = today_vol / ma5_vol

    # Scoring: higher ratio = higher score
    if vol_ratio >= 4.0:
        score = 20.0   # Extreme explosion
    elif vol_ratio >= 3.0:
        score = 16.0
    elif vol_ratio >= 2.0:
        score = 12.0
    elif vol_ratio >= 1.5:
        score = 8.0
    elif vol_ratio >= 1.2:
        score = 4.0
    else:
        score = 0.0

    # Bonus: volume explosion on a green candle is stronger
    if stock_hist['change_pct'].iloc[-1] > 0 and vol_ratio >= 2.0:
        score = min(score + 2.0, 20.0)

    return score, round(vol_ratio, 2)
```

**Step 2: Commit**

```bash
git add siphon_strategy.py
git commit -m "feat(v6): add calc_volume_explosion scoring (0-20)"
```

---

### Task 3: 新增 `calc_momentum_acceleration()` 函数（15分）

**Files:**
- Modify: `siphon_strategy.py` — 在 `calc_volume_explosion` 后插入

**Step 1: 添加动量加速度函数**

```python
def calc_momentum_acceleration(stock_hist, index_hist):
    """v6.0: Momentum acceleration scoring (0-15).
    Detects daily alpha increasing pattern:
    today's alpha > yesterday's > day before.
    Accelerating stocks have highest short-term burst probability.
    """
    merged = pd.merge(stock_hist, index_hist, on='date', how='inner', suffixes=('', '_idx'))
    if len(merged) < 6:
        return 0.0, False

    # Calculate daily alpha (stock return - index return)
    merged['daily_alpha'] = merged['change_pct'] - merged['Index_Change']
    recent = merged.tail(5)
    alphas = recent['daily_alpha'].values

    score = 0.0

    # Pattern 1: Consecutive alpha increase (last 3 days)
    if len(alphas) >= 3:
        a1, a2, a3 = alphas[-3], alphas[-2], alphas[-1]
        if a3 > a2 > a1:
            score += 8.0  # Strong acceleration
        elif a3 > a2 and a3 > 0:
            score += 5.0  # Moderate acceleration
        elif a3 > 0:
            score += 2.0  # At least positive alpha today

    # Pattern 2: 3-day cumulative alpha positive and growing
    if len(alphas) >= 5:
        alpha_3d = alphas[-3:].sum()
        alpha_5d = alphas.sum()
        if alpha_3d > 0 and alpha_3d > alpha_5d * 0.7:
            score += 4.0  # Recent alpha concentrated in last 3 days

    # Pattern 3: Today's alpha is the strongest in 5 days
    if alphas[-1] == max(alphas) and alphas[-1] > 1.0:
        score += 3.0

    is_accelerating = score >= 8.0
    return min(score, 15.0), is_accelerating
```

**Step 2: Commit**

```bash
git add siphon_strategy.py
git commit -m "feat(v6): add calc_momentum_acceleration scoring (0-15)"
```

---

### Task 4: 改造 `calc_sector_momentum()` 支持板块领涨度（10分）

**Files:**
- Modify: `siphon_strategy.py:553-571` — 改造现有函数

**Step 1: 重写 calc_sector_momentum，返回个股在板块内的排名信息**

```python
def calc_sector_momentum(pool_df, industry_col='Industry'):
    """v6.0: Sector momentum with per-stock ranking within sector.
    Returns hot_sectors list AND a dict mapping industry -> stock rankings.
    """
    try:
        sector_stats = pool_df.groupby(industry_col).agg(
            avg_change=('Change_Pct', lambda x: pd.to_numeric(x, errors='coerce').mean()),
            count=('Symbol', 'count')
        ).reset_index()

        sector_stats = sector_stats[sector_stats['count'] >= 3]
        if sector_stats.empty:
            return [], sector_stats, {}

        sector_stats['momentum_rank'] = sector_stats['avg_change'].rank(pct=True)
        hot_sectors = sector_stats[sector_stats['momentum_rank'] > 0.4][industry_col].tolist()

        # v6.0: Build per-sector stock ranking
        sector_rankings = {}
        for industry in hot_sectors:
            sector_stocks = pool_df[pool_df[industry_col] == industry].copy()
            sector_stocks['Change_Pct_num'] = pd.to_numeric(sector_stocks['Change_Pct'], errors='coerce')
            sector_stocks['rank_in_sector'] = sector_stocks['Change_Pct_num'].rank(pct=True)
            for _, srow in sector_stocks.iterrows():
                sector_rankings[str(srow['Symbol']).zfill(6)] = srow['rank_in_sector']

        return hot_sectors, sector_stats, sector_rankings
    except Exception as e:
        print(f"⚠️ Sector momentum calc error: {e}")
        return [], pd.DataFrame(), {}
```

**Step 2: 新增板块领涨度评分函数**

```python
def calc_sector_leader_score(symbol, is_hot_sector, sector_rankings):
    """v6.0: Sector leader scoring (0-10).
    Rewards stocks that lead their hot sector.
    """
    if not is_hot_sector:
        return 0.0

    rank_pct = sector_rankings.get(symbol, 0.5)

    if rank_pct >= 0.9:
        return 10.0  # Top 10% in hot sector
    elif rank_pct >= 0.7:
        return 7.0   # Top 30%
    elif rank_pct >= 0.5:
        return 4.0   # Above median
    else:
        return 2.0   # In hot sector but not leading
```

**Step 3: Commit**

```bash
git add siphon_strategy.py
git commit -m "feat(v6): upgrade sector momentum to per-stock leader scoring (0-10)"
```

---

### Task 5: 改造 `calc_relative_strength()` 时间窗口

**Files:**
- Modify: `siphon_strategy.py:448-477`

**Step 1: 调整时间窗口为 3/5/10 日，权重 40%/35%/25%**

```python
def calc_relative_strength(stock_hist, index_hist):
    """v6.0: Short-term relative strength (3/5/10 day alpha).
    Weighted: 3d=40%, 5d=35%, 10d=25%. Shorter windows for momentum capture.
    """
    merged = pd.merge(stock_hist, index_hist, on='date', how='inner', suffixes=('', '_idx'))
    if len(merged) < 11:
        return 0.0, False

    closes = merged['close']
    idx_closes = merged['close_idx']

    stock_3d = (closes.iloc[-1] / closes.iloc[-4] - 1) * 100 if len(closes) > 3 else 0
    stock_5d = (closes.iloc[-1] / closes.iloc[-6] - 1) * 100 if len(closes) > 5 else 0
    stock_10d = (closes.iloc[-1] / closes.iloc[-11] - 1) * 100 if len(closes) > 10 else 0

    idx_3d = (idx_closes.iloc[-1] / idx_closes.iloc[-4] - 1) * 100 if len(idx_closes) > 3 else 0
    idx_5d = (idx_closes.iloc[-1] / idx_closes.iloc[-6] - 1) * 100 if len(idx_closes) > 5 else 0
    idx_10d = (idx_closes.iloc[-1] / idx_closes.iloc[-11] - 1) * 100 if len(idx_closes) > 10 else 0

    alpha_3d = stock_3d - idx_3d
    alpha_5d = stock_5d - idx_5d
    alpha_10d = stock_10d - idx_10d

    # Acceleration: short > mid > long and all positive
    is_accelerating = alpha_3d > alpha_5d > alpha_10d > 0

    # v6.0: Weighted RS (shorter windows weighted more)
    rs = alpha_3d * 0.4 + alpha_5d * 0.35 + alpha_10d * 0.25
    return round(rs, 2), is_accelerating
```

**Step 2: Commit**

```bash
git add siphon_strategy.py
git commit -m "feat(v6): shorten RS windows to 3/5/10d for momentum capture"
```

---

### Task 6: 重写 `calc_composite_score()` — 新权重体系

**Files:**
- Modify: `siphon_strategy.py:573-599`

**Step 1: 重写评分函数，新权重分配**

```python
def calc_composite_score(ag_score, rs_score, flow_info, is_hot_sector,
                         vcp_signal, vol_explosion_score, momentum_accel_score,
                         sector_leader_score):
    """v6.0: Aggressive momentum composite scoring (0-100).

    Weight allocation:
    1. Relative Strength Alpha   — 30pts (core)
    2. Volume Explosion          — 20pts (ignition signal)
    3. Institutional Flow        — 20pts (smart money)
    4. Momentum Acceleration     — 15pts (burst probability)
    5. Sector Leader             — 10pts (leading hot sector)
    6. Antigravity (resilience)  —  5pts (minor reference)
    """
    score = 0.0

    # 1. Relative Strength (0-30): multi-timeframe outperformance
    score += max(min(rs_score * 3.0, 30.0), 0.0)

    # 2. Volume Explosion (0-20): today's volume vs 5d avg
    score += min(vol_explosion_score, 20.0)

    # 3. Institutional Flow (0-20): accumulation patterns
    score += flow_info['score'] * 4.0  # max 5 * 4 = 20

    # 4. Momentum Acceleration (0-15): daily alpha increasing
    score += min(momentum_accel_score, 15.0)

    # 5. Sector Leader (0-10): rank within hot sector
    score += min(sector_leader_score, 10.0)

    # 6. Antigravity (0-5): minor resilience reference
    score += min(ag_score * 0.5, 5.0)

    # Bonus: VCP pattern still gets a small nudge (not scored independently)
    if vcp_signal:
        score += 2.0

    return round(min(score, 100.0), 1)
```

**Step 2: Commit**

```bash
git add siphon_strategy.py
git commit -m "feat(v6): rewrite composite score with aggressive momentum weights"
```

---

### Task 7: 改造 `run_siphoner_strategy()` 主流程

**Files:**
- Modify: `siphon_strategy.py:740-883`

**关键变更清单：**

1. 更新 `calc_sector_momentum` 调用以接收 `sector_rankings`
2. 去掉 `if not vcp_signal: continue` 硬过滤（第814行）
3. 去掉 `if atr_pct > cfg.max_atr_pct: continue` 安全边际过滤（第834行）
4. 新增 `calc_volume_explosion()` 调用
5. 新增 `calc_momentum_acceleration()` 调用
6. 新增 `calc_sector_leader_score()` 调用
7. 更新 `calc_composite_score()` 调用签名
8. 更新 signal_tags 构建逻辑
9. 更新 results dict 字段

**Step 1: 修改 sector_momentum 调用（约第763行）**

```python
# v6.0: Sector momentum with per-stock rankings
hot_sectors, sector_stats, sector_rankings = calc_sector_momentum(pool)
```

**Step 2: 去掉 VCP 硬过滤（约第814行）**

删除这一行:
```python
if not vcp_signal: continue
```

**Step 3: 去掉安全边际过滤（约第833-835行）**

删除这几行:
```python
safety_grade, atr_pct = calc_safety_margin(hist)
if atr_pct > cfg.max_atr_pct:
    continue  # Skip dangerously volatile stocks
```

**Step 4: 在 Step 3 (Enhanced Scoring) 区域添加新维度调用**

在 `flow_info = detect_institutional_flow(hist)` 之后添加:

```python
        # v6.0: Volume Explosion
        vol_explosion_score, vol_ratio_calc = calc_volume_explosion(hist)

        # v6.0: Momentum Acceleration
        momentum_accel_score, is_momentum_accel = calc_momentum_acceleration(hist, index_df)

        # v6.0: Sector Leader Score
        sector_leader_score_val = calc_sector_leader_score(symbol, is_hot_sector, sector_rankings)
```

**Step 5: 更新 composite score 调用**

```python
        composite = calc_composite_score(
            ag_score, rs_score, flow_info, is_hot_sector,
            vcp_signal, vol_explosion_score, momentum_accel_score,
            sector_leader_score_val
        )
```

**Step 6: 更新 signal_tags 构建**

```python
        signal_tags = []
        if vol_explosion_score >= 12: signal_tags.append(f"爆量{vol_ratio_calc}x")
        if is_momentum_accel: signal_tags.append("加速🚀")
        if is_accelerating: signal_tags.append("RS加速")
        if flow_info['rising_floor']: signal_tags.append("底升")
        if flow_info['flow_ratio'] > 1.5: signal_tags.append("吸筹")
        if vcp_signal: signal_tags.append("VCP")
        if sector_leader_score_val >= 7: signal_tags.append("领涨")
        if rsi < 50: signal_tags.append("LowRSI")
        signal_str = " ".join(signal_tags) if signal_tags else "Momentum"
```

**Step 7: 更新 results dict**

```python
        results.append({
            'Symbol': symbol_str,
            'Name': name,
            'Industry': industry,
            'Price': float(current_price),
            'Change_Pct': change_pct,
            'AG_Score': composite,
            'AG_Details': signal_str,
            'Volume_Note': f"VolR:{vol_ratio_calc:.1f}x Flow:{flow_info['flow_ratio']:.1f}",
            'RS_Score': rs_score,
            'Vol_Explosion': vol_explosion_score,
            'Momentum_Accel': momentum_accel_score,
            'Flow_Ratio': flow_info['flow_ratio'],
            'Composite': composite
        })
```

**Step 8: 更新 print 输出**

```python
        print(f"MATCH {name}: C={composite} RS={rs_score:.1f} Vol={vol_explosion_score:.0f} Accel={momentum_accel_score:.0f} Flow={flow_info['flow_ratio']:.1f} Sector={sector_leader_score_val:.0f}")
```

**Step 9: Commit**

```bash
git add siphon_strategy.py
git commit -m "feat(v6): rewire main pipeline for aggressive momentum model"
```

---

### Task 8: 更新版本号和注释

**Files:**
- Modify: `siphon_strategy.py:741`

**Step 1: 更新版本标识**

```python
def run_siphoner_strategy(market='CN', cfg=CONFIG):
    print(f"=== Starting 'Siphon Strategy v6.0 — Aggressive Momentum' (Market: {market}) ===")
```

**Step 2: Final commit**

```bash
git add siphon_strategy.py
git commit -m "feat(v6): siphon strategy v6.0 aggressive momentum model complete"
```

---

### Task 9: 冒烟测试

**Step 1: 语法检查**

```bash
python -c "import ast; ast.parse(open('siphon_strategy.py').read()); print('Syntax OK')"
```

Expected: `Syntax OK`

**Step 2: 干跑测试（如果有网络）**

```bash
cd /Users/ddhu/stock_recommendation && python siphon_strategy.py
```

检查：
- 无 ImportError / NameError
- `calc_composite_score` 被正确调用（参数数量匹配）
- 输出包含新字段（Vol, Accel, Sector）
- 有结果输出（即使数量不同于v5）

---

## 权重对比总结

| 维度 | v5.0 旧分 | v6.0 新分 | 变化 |
|------|----------|----------|------|
| 相对强度 Alpha (3/5/10d) | 25 | 30 | ↑ 核心指标 |
| 量能爆发度 (新) | 0 | 20 | ✨ 新增 |
| 机构资金/吸筹 | 20 | 20 | → 保持 |
| 动量加速度 (新) | 0 | 15 | ✨ 新增 |
| 板块领涨度 (升级) | 5 | 10 | ↑ 从热门板块升级为排名 |
| 逆势抗跌 | 30 | 5 | ↓↓ 大幅降权 |
| VCP 形态 | 5 | +2 bonus | ↓ 不再独立评分 |
| 安全边际 | 15 | 0 | ❌ 完全去掉 |
