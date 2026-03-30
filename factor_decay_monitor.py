"""
factor_decay_monitor.py — 因子衰减监控 (适配Siphon荐股系统)
=============================================================
移植自 loop-win-2026

追踪推荐质量是否在退化:
  1. 滚动胜率/赔付比 — 推荐后N日涨跌统计
  2. 滚动IC — 推荐评分与实际收益的相关性
  3. 策略分类统计 — 动量/反转各自表现
  4. 衰减预警 — GREEN/YELLOW/RED

对Siphon的价值:
  - 在邮件报告中展示推荐质量趋势
  - 胜率下降时自动提高推荐门槛
  - 帮助用户判断策略是否仍然有效

Usage:
  from factor_decay_monitor import FactorDecayMonitor
  monitor = FactorDecayMonitor()
  monitor.record_recommendation(date, score, ...)
  monitor.record_outcome(date, pnl, ...)
  report = monitor.check_health()
"""
import os
import json
import statistics
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple


class RollingStats:
    """滚动窗口统计"""

    def __init__(self, window: int = 60):
        self.window = window
        self._values: List[float] = []

    def add(self, value: float):
        self._values.append(value)
        if len(self._values) > self.window * 2:
            self._values = self._values[-self.window:]

    @property
    def values(self) -> List[float]:
        return self._values[-self.window:]

    @property
    def count(self) -> int:
        return len(self.values)

    @property
    def mean(self) -> float:
        v = self.values
        return sum(v) / len(v) if v else 0

    def win_rate(self) -> float:
        v = self.values
        return sum(1 for x in v if x > 0) / len(v) if v else 0

    def payoff_ratio(self) -> float:
        v = self.values
        wins = [x for x in v if x > 0]
        losses = [abs(x) for x in v if x < 0]
        if not wins or not losses:
            return 0
        return (sum(wins) / len(wins)) / (sum(losses) / len(losses))


class FactorDecayMonitor:
    """因子衰减监控 — 追踪Siphon推荐质量"""

    # 基线指标 (基于历史回测)
    BASELINE = {
        'win_rate': 0.48,
        'payoff_ratio': 1.5,
        'avg_return': 1.5,  # %
    }

    def __init__(self, save_dir: str = None):
        self.save_dir = save_dir or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 'data_cache')
        os.makedirs(self.save_dir, exist_ok=True)

        # 总体推荐结果统计
        self.overall_stats = RollingStats(window=60)
        # 按策略分类
        self.momentum_stats = RollingStats(window=60)
        self.reversal_stats = RollingStats(window=60)

        # 评分与收益的相关性追踪
        self._score_return_pairs: List[Tuple[float, float]] = []

        # 推荐记录 (待回填收益)
        self._pending: Dict[str, dict] = {}  # {stock_code+date: {score, strategy}}

        # 告警历史
        self._alerts: List[Tuple[str, str, str]] = []  # (date, level, message)

        # 尝试加载历史状态
        self._load_state()

    def record_recommendation(self, rec_date: str, stock_code: str,
                               siphon_score: float, strategy_tag: str = 'Momentum'):
        """记录一条推荐 (收益待后续回填)"""
        key = f"{stock_code}_{rec_date}"
        self._pending[key] = {
            'date': rec_date,
            'code': stock_code,
            'score': siphon_score,
            'strategy': strategy_tag,
        }

    def record_outcome(self, rec_date: str, stock_code: str,
                        final_return_pct: float):
        """回填推荐结果"""
        key = f"{stock_code}_{rec_date}"
        info = self._pending.pop(key, None)

        # 更新总体统计
        self.overall_stats.add(final_return_pct)

        # 按策略分类
        strategy = info['strategy'] if info else 'Momentum'
        if 'Reversal' in strategy or '反转' in strategy:
            self.reversal_stats.add(final_return_pct)
        else:
            self.momentum_stats.add(final_return_pct)

        # 记录分数-收益对
        score = info['score'] if info else 50
        self._score_return_pairs.append((score, final_return_pct))
        if len(self._score_return_pairs) > 200:
            self._score_return_pairs = self._score_return_pairs[-120:]

    def compute_ic(self) -> Optional[float]:
        """计算推荐评分与实际收益的Rank IC (Spearman)"""
        pairs = self._score_return_pairs[-60:]
        if len(pairs) < 20:
            return None

        scores = [p[0] for p in pairs]
        returns = [p[1] for p in pairs]

        score_ranks = self._rank(scores)
        return_ranks = self._rank(returns)

        n = len(score_ranks)
        d_sq = sum((sr - rr) ** 2 for sr, rr in zip(score_ranks, return_ranks))
        ic = 1 - (6 * d_sq) / (n * (n ** 2 - 1))
        return ic

    def _rank(self, values: List[float]) -> List[float]:
        sorted_idx = sorted(range(len(values)), key=lambda i: values[i])
        ranks = [0.0] * len(values)
        for rank, idx in enumerate(sorted_idx):
            ranks[idx] = rank + 1
        return ranks

    def check_health(self) -> Dict:
        """全面健康检查, 返回报告字典"""
        report = {
            'date': date.today().isoformat(),
            'overall_status': 'GREEN',
            'metrics': {},
            'by_strategy': {},
            'ic': None,
            'alerts': [],
            'recommendation': '',
        }

        alerts = []

        # 1. 总体指标
        if self.overall_stats.count >= 10:
            wr = self.overall_stats.win_rate()
            pr = self.overall_stats.payoff_ratio()
            avg = self.overall_stats.mean

            report['metrics'] = {
                'win_rate': round(wr, 3),
                'payoff_ratio': round(pr, 2),
                'avg_return': round(avg, 2),
                'sample_size': self.overall_stats.count,
            }

            if wr < 0.38:
                alerts.append(f"[RED] 胜率 {wr:.0%} 严重低于基线{self.BASELINE['win_rate']:.0%}")
            elif wr < 0.44:
                alerts.append(f"[YELLOW] 胜率 {wr:.0%} 低于基线{self.BASELINE['win_rate']:.0%}")

            if pr > 0 and pr < 1.0:
                alerts.append(f"[RED] 赔付比 {pr:.2f} < 1.0 (亏损>盈利)")
            elif pr > 0 and pr < 1.3:
                alerts.append(f"[YELLOW] 赔付比 {pr:.2f} 低于基线{self.BASELINE['payoff_ratio']}")

        # 2. 分策略统计
        if self.momentum_stats.count >= 5:
            report['by_strategy']['Momentum'] = {
                'win_rate': round(self.momentum_stats.win_rate(), 3),
                'avg_return': round(self.momentum_stats.mean, 2),
                'count': self.momentum_stats.count,
            }
        if self.reversal_stats.count >= 5:
            report['by_strategy']['Reversal'] = {
                'win_rate': round(self.reversal_stats.win_rate(), 3),
                'avg_return': round(self.reversal_stats.mean, 2),
                'count': self.reversal_stats.count,
            }

        # 3. IC检查
        ic = self.compute_ic()
        if ic is not None:
            report['ic'] = round(ic, 4)
            if ic < 0.01:
                alerts.append(f"[RED] 评分IC={ic:.4f} 几乎无预测能力")
            elif ic < 0.03:
                alerts.append(f"[YELLOW] 评分IC={ic:.4f} 预测力较弱")

        # 4. 综合状态
        red_count = sum(1 for a in alerts if '[RED]' in a)
        yellow_count = sum(1 for a in alerts if '[YELLOW]' in a)

        if red_count >= 2:
            report['overall_status'] = 'RED'
            report['recommendation'] = '建议提高推荐门槛至60分，减少推荐数量'
        elif red_count >= 1 or yellow_count >= 2:
            report['overall_status'] = 'YELLOW'
            report['recommendation'] = '建议关注推荐质量，考虑提高门槛至50分'
        else:
            report['overall_status'] = 'GREEN'
            report['recommendation'] = '推荐质量正常'

        report['alerts'] = alerts

        # 记录告警
        today = date.today().isoformat()
        for a in alerts:
            level = 'RED' if '[RED]' in a else 'YELLOW'
            self._alerts.append((today, level, a))

        return report

    def get_status_label(self) -> str:
        """简短状态标签 (用于报告标题)"""
        report = self.check_health()
        status = report['overall_status']
        labels = {'GREEN': '正常', 'YELLOW': '关注', 'RED': '警告'}
        return labels.get(status, '未知')

    def get_status_color(self) -> str:
        report = self.check_health()
        colors = {'GREEN': '#10b981', 'YELLOW': '#f59e0b', 'RED': '#ef4444'}
        return colors.get(report['overall_status'], '#94a3b8')

    def generate_html_summary(self) -> str:
        """生成HTML摘要 (嵌入邮件报告)"""
        report = self.check_health()
        status = report['overall_status']
        color = {'GREEN': '#10b981', 'YELLOW': '#f59e0b', 'RED': '#ef4444'}.get(status, '#94a3b8')

        html = f'<div style="border:2px solid {color};border-radius:8px;padding:12px;margin:10px 0">'
        html += f'<h3 style="color:{color};margin:0">因子健康: {status}</h3>'

        if report['metrics']:
            m = report['metrics']
            html += (f'<p style="margin:5px 0">胜率: {m["win_rate"]:.0%} | '
                     f'赔付比: {m["payoff_ratio"]:.2f} | '
                     f'均收益: {m["avg_return"]:+.2f}% | '
                     f'样本: {m["sample_size"]}</p>')

        if report['ic'] is not None:
            html += f'<p style="margin:5px 0">评分IC: {report["ic"]:.4f}</p>'

        if report['alerts']:
            html += '<ul style="margin:5px 0">'
            for a in report['alerts']:
                a_color = '#ef4444' if '[RED]' in a else '#f59e0b'
                html += f'<li style="color:{a_color}">{a}</li>'
            html += '</ul>'

        if report['recommendation']:
            html += f'<p style="margin:5px 0;font-weight:bold">{report["recommendation"]}</p>'

        html += '</div>'
        return html

    def _save_state(self):
        """持久化状态"""
        state = {
            'overall_values': self.overall_stats._values[-120:],
            'momentum_values': self.momentum_stats._values[-120:],
            'reversal_values': self.reversal_stats._values[-120:],
            'score_return_pairs': self._score_return_pairs[-120:],
            'alerts': self._alerts[-50:],
        }
        path = os.path.join(self.save_dir, 'factor_decay_state.json')
        try:
            with open(path, 'w') as f:
                json.dump(state, f, ensure_ascii=False)
        except Exception:
            pass

    def _load_state(self):
        """恢复状态"""
        path = os.path.join(self.save_dir, 'factor_decay_state.json')
        if not os.path.exists(path):
            return
        try:
            with open(path) as f:
                state = json.load(f)
            self.overall_stats._values = state.get('overall_values', [])
            self.momentum_stats._values = state.get('momentum_values', [])
            self.reversal_stats._values = state.get('reversal_values', [])
            self._score_return_pairs = [tuple(p) for p in state.get('score_return_pairs', [])]
            self._alerts = [tuple(a) for a in state.get('alerts', [])]
        except Exception:
            pass
