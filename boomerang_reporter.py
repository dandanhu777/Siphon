"""
Project Boomerang - Report Generator
Generate performance reports and strategy analytics
"""

import boomerang_tracker as bt
import pandas as pd
from datetime import datetime

def grade_recommendation(cumulative_return: float, max_drawdown: float) -> tuple:
    """
    Grade a recommendation based on performance
    Returns: (grade, emoji)
    """
    # Stop-loss triggered
    if max_drawdown < -8.0:
        return "⚠️ 失败", "⚠️"
    
    # Performance grading
    if cumulative_return > 15:
        return "👑 金股", "👑"
    elif cumulative_return > 5:
        return "🥈 银股", "🥈"
    elif cumulative_return < -5:
        return "🗑️ 垃圾", "🗑️"
    else:
        return "📊 观察", "📊"

def generate_markdown_report() -> str:
    """Generate markdown report for active and champion gold stocks"""
    
    # Get active recommendations (all stocks currently being tracked)
    active_df = bt.get_active_recommendations()
    
    # Get recently closed (last 10 days) - will filter for champions only
    closed_df = bt.get_closed_recommendations(days=10)
    
    report = "# 📊 Boomerang 策略回测追踪\n\n"
    
    # Active Recommendations Section - Show ALL
    if not active_df.empty:
        report += "## 🔄 追踪中的推荐\n\n"
        report += "| 推荐日期 | 标的 | 策略标签 | 今日涨幅 | T+N累计 | 同期大盘 | 最高触及 | 最大回撤 | 评价 |\n"
        report += "|---------|------|---------|---------|---------|---------|---------|---------|------|\n"
        
        for _, row in active_df.iterrows():
            rec_date = row['rec_date']
            stock_name = row['stock_name']
            strategy = row['strategy_tag'] or 'N/A'
            daily_chg = row['daily_change_pct'] if pd.notna(row['daily_change_pct']) else 0
            cum_return = row['cumulative_return'] if pd.notna(row['cumulative_return']) else 0
            index_return = row['index_return'] if pd.notna(row['index_return']) else 0
            max_high_pct = ((row['max_high'] - row['rec_price']) / row['rec_price'] * 100) if pd.notna(row['max_high']) else 0
            max_dd = row['max_drawdown'] if pd.notna(row['max_drawdown']) else 0
            days = int(row['days_tracked']) if pd.notna(row['days_tracked']) else 0
            
            grade, emoji = grade_recommendation(cum_return, max_dd)
            
            # Alpha check
            alpha = "⚡" if cum_return > index_return else ""
            
            report += f"| {rec_date} | {stock_name} | {strategy} | {daily_chg:+.1f}% | T+{days} {cum_return:+.1f}%{alpha} | {index_return:+.1f}% | {max_high_pct:+.1f}% | {max_dd:.1f}% | {grade} |\n"
    else:
        report += "## 🔄 追踪中的推荐\n\n*暂无活跃追踪*\n\n"
    
    # Closed Recommendations Review - Show ALL (no filtering)
    if not closed_df.empty:
        report += "\n## 📁 10日追踪回顾\n\n"
        report += "| 推荐日期 | 标的 | 策略标签 | 最终收益 | 同期大盘 | 最高触及 | 最大回撤 | 评价 |\n"
        report += "|---------|------|---------|---------|---------|---------|---------|------|\n"
        
        for _, row in closed_df.iterrows():
            rec_date = row['rec_date']
            stock_name = row['stock_name']
            strategy = row['strategy_tag'] or 'N/A'
            final_return = row['final_return'] if pd.notna(row['final_return']) else 0
            index_return = row['index_return'] if pd.notna(row['index_return']) else 0
            max_high_pct = ((row['max_high'] - row['rec_price']) / row['rec_price'] * 100) if pd.notna(row['max_high']) else 0
            max_dd = row['max_drawdown'] if pd.notna(row['max_drawdown']) else 0
            
            grade, emoji = grade_recommendation(final_return, max_dd)
            
            # Alpha check
            alpha = "⚡" if final_return > index_return else ""
            
            report += f"| {rec_date} | {stock_name} | {strategy} | {final_return:+.1f}%{alpha} | {index_return:+.1f}% | {max_high_pct:+.1f}% | {max_dd:.1f}% | {grade} |\n"
    
    # Strategy Analytics
    metrics = bt.calculate_strategy_metrics()
    
    if metrics:
        report += "\n## 📈 策略总评\n\n"
        
        for strategy, stats in metrics.items():
            win_rate = stats['win_rate']
            avg_return = stats['avg_return']
            
            # Recommendation based on performance
            if win_rate > 70 and avg_return > 10:
                recommendation = "✅ 建议：加大权重"
            elif win_rate > 50 and avg_return > 5:
                recommendation = "📊 建议：保持观察"
            else:
                recommendation = "⚠️ 建议：停用/修正参数"
            
            report += f"**[{strategy}] 策略**：\n"
            report += f"- 胜率：{win_rate:.1f}%\n"
            report += f"- 平均收益：{avg_return:+.1f}%\n"
            report += f"- 平均回撤：{stats['avg_drawdown']:.1f}%\n"
            report += f"- 金股率：{stats['gold_rate']:.1f}% | 银股率：{stats['silver_rate']:.1f}% | 失败率：{stats['trash_rate']:.1f}%\n"
            report += f"- {recommendation}\n\n"
    
    report += f"\n*报告生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}*\n"
    
    return report

def generate_html_report() -> str:
    """Generate HTML report for email integration"""
    
    # Get data
    active_df = bt.get_active_recommendations()
    closed_df = bt.get_closed_recommendations(days=10)
    
    html = '<div style="background: #f8fafc; padding: 20px; border-radius: 8px; font-family: -apple-system, sans-serif;">'
    
    # Active Recommendations - Show ALL
    if not active_df.empty:
        html += '<h3 style="color: #1e293b; margin-top: 0;">🔄 追踪中的推荐</h3>'
        html += '<table style="width: 100%; border-collapse: collapse; font-size: 13px; margin-bottom: 20px;">'
        html += '<thead><tr style="background-color: #e2e8f0; text-align: left;">'
        html += '<th style="padding: 10px;">推荐日期</th><th>标的</th><th>策略</th><th>今日</th><th>T+N累计</th><th>同期大盘</th><th>最高</th><th>回撤</th><th>评价</th>'
        html += '</tr></thead><tbody>'
        
        for _, row in active_df.iterrows():
            daily_chg = row['daily_change_pct'] if pd.notna(row['daily_change_pct']) else 0
            cum_return = row['cumulative_return'] if pd.notna(row['cumulative_return']) else 0
            index_return = row['index_return'] if pd.notna(row['index_return']) else 0
            max_high_pct = ((row['max_high'] - row['rec_price']) / row['rec_price'] * 100) if pd.notna(row['max_high']) else 0
            max_dd = row['max_drawdown'] if pd.notna(row['max_drawdown']) else 0
            days = int(row['days_tracked']) if pd.notna(row['days_tracked']) else 0
            
            grade, emoji = grade_recommendation(cum_return, max_dd)
            
            # Color coding
            cum_color = '#16a34a' if cum_return > 0 else '#dc2626'
            
            # Alpha check
            alpha_style = "color: #334155; font-weight: bold;" if index_return != 0 else "color: #94a3b8;"
            
            html += f'<tr style="border-bottom: 1px solid #f1f5f9;">'
            html += f'<td style="padding: 10px;">{row["rec_date"]}</td>'
            html += f'<td>{row["stock_name"]}</td>'
            html += f'<td style="font-size: 11px; color: #64748b;">{row["strategy_tag"] or "N/A"}</td>'
            html += f'<td style="color: {"#16a34a" if daily_chg > 0 else "#dc2626"};">{daily_chg:+.1f}%</td>'
            html += f'<td style="color: {cum_color}; font-weight: 600;">T+{days} {cum_return:+.1f}%</td>'
            html += f'<td style="{alpha_style}">{index_return:+.1f}%</td>'
            html += f'<td style="color: #16a34a;">{max_high_pct:+.1f}%</td>'
            html += f'<td style="color: #dc2626;">{max_dd:.1f}%</td>'
            html += f'<td>{grade}</td>'
            html += '</tr>'
        
        html += '</tbody></table>'
    else:
        html += '<p style="color: #64748b; font-style: italic;">暂无活跃追踪</p>'
    
    # Closed Recommendations Review - Show ALL (no filtering for transparency)
    if not closed_df.empty:
        html += '<h3 style="color: #1e293b; margin-top: 20px;">📁 10日追踪回顾</h3>'
        html += '<table style="width: 100%; border-collapse: collapse; font-size: 13px; margin-bottom: 20px;">'
        html += '<thead><tr style="background-color: #f1f5f9; text-align: left;">'
        html += '<th style="padding: 10px;">推荐日期</th><th>标的</th><th>策略</th><th>最终收益</th><th>同期大盘</th><th>最高触及</th><th>最大回撤</th><th>评价</th>'
        html += '</tr></thead><tbody>'
        
        for _, row in closed_df.iterrows():
            final_return = row['final_return'] if pd.notna(row['final_return']) else 0
            index_return = row['index_return'] if pd.notna(row['index_return']) else 0
            max_high_pct = ((row['max_high'] - row['rec_price']) / row['rec_price'] * 100) if pd.notna(row['max_high']) else 0
            max_dd = row['max_drawdown'] if pd.notna(row['max_drawdown']) else 0
            
            grade, emoji = grade_recommendation(final_return, max_dd)
            
            # Color based on performance
            if final_return > 15:
                bg_color = '#fffbeb'
                border_color = '#fef3c7'
            elif final_return > 0:
                bg_color = '#f0fdf4'
                border_color = '#dcfce7'
            else:
                bg_color = '#fef2f2'
                border_color = '#fee2e2'
            
            # Alpha calculation
            alpha_style = "font-weight: bold; color: #16a34a;" if final_return > index_return else "color: #64748b;"
            
            html += f'<tr style="border-bottom: 1px solid {border_color}; background-color: {bg_color};">'
            html += f'<td style="padding: 10px;">{row["rec_date"]}</td>'
            html += f'<td style="font-weight: 600;">{row["stock_name"]}</td>'
            html += f'<td style="font-size: 11px; color: #64748b;">{row["strategy_tag"] or "N/A"}</td>'
            html += f'<td style="color: {"#16a34a" if final_return > 0 else "#dc2626"}; font-weight: 700; font-size: 14px;">{final_return:+.1f}%</td>'
            html += f'<td style="{alpha_style}">{index_return:+.1f}%</td>'
            html += f'<td style="color: #16a34a;">{max_high_pct:+.1f}%</td>'
            html += f'<td style="color: #dc2626;">{max_dd:.1f}%</td>'
            html += f'<td>{grade}</td>'
            html += '</tr>'
        
        html += '</tbody></table>'
    
    
    # Strategy Summary - Simplified (Optional, can be removed if too much data)
    # Commenting out for now to keep report concise
    
    html += f'<p style="text-align: center; color: #94a3b8; font-size: 11px; margin-top: 20px;">报告生成时间：{datetime.now().strftime("%Y-%m-%d %H:%M")}</p>'
    html += '</div>'
    
    return html

if __name__ == "__main__":
    # Test report generation
    print(generate_markdown_report())
