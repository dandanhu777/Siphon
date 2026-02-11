import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
import os
import datetime
import pandas as pd

class EmailNotifier:
    def __init__(self, smtp_server=None, smtp_port=None, sender_email=None, password=None):
        # Load from env if not provided. Defaulting to Brevo SMTP.
        self.smtp_server = smtp_server or os.getenv('SMTP_SERVER', 'smtp-relay.brevo.com')
        # Brevo usually uses 587 for TLS
        self.smtp_port = smtp_port or int(os.getenv('SMTP_PORT', 587))
        self.sender_email = sender_email or os.getenv('SENDER_EMAIL')
        self.password = password or os.getenv('SENDER_PASSWORD')
        
    def send_recommendation_report(self, receivers, golden_stock, stock_df):
        """
        Sends the stock recommendation report with Golden Stock and Highlights.
        receivers: str or list of str
        """
        if isinstance(receivers, str):
            receivers = [receivers]

        if stock_df is not None and not stock_df.empty:
            count = len(stock_df)
            today_str = datetime.date.today().strftime("%Y-%m-%d")
            
            # Subject (Chinese)
            stock_name = golden_stock['Name'] if golden_stock else "N/A"
            subject = f"每日金股推荐: {stock_name} + {count}只潜力标的 ({today_str})"
            
            # Improved CSS Styles
            style = """
            <style>
            body {font-family: 'Helvetica Neue', Helvetica, 'PingFang SC', 'Microsoft YaHei', '微软雅黑', Arial, sans-serif; color: #333; line-height: 1.6; max-width: 800px; margin: 0 auto; padding: 20px;}
            .header {text-align: center; margin-bottom: 30px;}
            .gold-box {background: linear-gradient(135deg, #fff8e1 0%, #fffdf5 100%); border: 1px solid #ffd54f; padding: 25px; border-radius: 12px; margin-bottom: 30px; box-shadow: 0 4px 6px rgba(0,0,0,0.05);}
            .gold-title {color: #b76e00; font-size: 22px; font-weight: bold; margin-bottom: 15px; border-bottom: 2px solid #ffd54f; padding-bottom: 10px; display: inline-block;}
            .gold-metric {display: inline-block; background: #fff; padding: 5px 10px; border-radius: 4px; margin-right: 15px; border: 1px solid #eee; font-size: 14px;}
            .section-title {color: #2c3e50; font-size: 18px; border-left: 5px solid #3498db; padding-left: 10px; margin-top: 30px; margin-bottom: 15px;}
            
            /* Table Styling */
            .table-container {overflow-x: auto; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.05);}
            .table {border-collapse: collapse; width: 100%; font-size: 13px; background: #fff;}
            .table th {background-color: #3498db; color: white; padding: 12px 8px; font-weight: 600; text-align: center; white-space: nowrap;}
            .table td {border-bottom: 1px solid #eee; padding: 10px 8px; text-align: center;}
            .table tr:last-child td {border-bottom: none;}
            .table tr:hover {background-color: #f8f9fa;}
            
            .highlight-row {background-color: #ffe6e6 !important;} /* Red Highlight for Startup Phase */
            .badge-startup {background-color: #ff4757; color: white; padding: 3px 8px; border-radius: 10px; font-size: 11px;}
            
            .logic-footer {background-color: #f8f9fa; padding: 20px; border-radius: 8px; margin-top: 40px; font-size: 13px; color: #666; border: 1px solid #eee;}
            .logic-bullet {margin-bottom: 8px;}
            </style>
            """
            
            # Golden Stock Section
            if golden_stock:
                gold_section = f"""
                <div class="gold-box">
                    <div class="header">
                         <div class="gold-title">🏆 当日金股: {golden_stock['Name']} ({golden_stock['Symbol']})</div>
                    </div>
                    <div style="margin-bottom: 15px;">
                        <span class="gold-metric">💰 价格: {golden_stock['Price']}</span>
                        <span class="gold-metric">🏭 行业: {golden_stock['Industry']}</span>
                    </div>
                    <p><strong>💡 选择逻辑:</strong> {golden_stock['Logic']}</p>
                    <p><strong>💎 标的优势:</strong> {golden_stock['Advantage']}</p>
                    <p><strong>🚀 推荐理由:</strong> {golden_stock['Why']}</p>
                </div>
                """
            else:
                gold_section = "<div class='gold-box'>今日未筛选出符合严苛标准的金股。</div>"

            # Table Header
            table_header = """
            <tr>
                <th>代码</th><th>名称</th><th>行业</th><th>价格</th><th>动态市盈</th><th>增长率</th><th>量比</th><th>PEG</th><th>状态</th><th>5日涨幅</th><th>推荐理由</th>
            </tr>
            """
            
            # Table Rows
            rows = ""
            for _, row in stock_df.iterrows():
                # Highlight if Startup Phase
                is_startup = row.get('Is_Startup', False)
                row_class = "highlight-row" if is_startup else ""
                startup_flag = "<span class='badge-startup'>🚀 启动</span>" if is_startup else "-"
                
                # Sector Hot Flag
                industry_text = row['Industry']
                if row.get('Is_Hot_Sector', False):
                    industry_text += " 🔥" # Fire icon for hot sector
                
                # Safe formatting for potential None values
                pe_ttm_val = row.get('PE_TTM')
                pe_ttm_str = f"{pe_ttm_val:.1f}" if pd.notnull(pe_ttm_val) else "N/A"
                
                peg_val = row.get('PEG')
                peg_str = f"{peg_val:.2f}" if pd.notnull(peg_val) else "N/A"
                
                vol_val = row.get('Volume_Ratio')
                vol_str = f"{vol_val:.1f}" if pd.notnull(vol_val) else "N/A"
                
                pchg_val = row.get('Price_Change_5D', 0)
                pchg_str = f"{pchg_val:.1f}%" if pd.notnull(pchg_val) else "0.0%"
                
                remark = row.get('Remark', '')

                rows += f"""
                <tr class="{row_class}">
                    <td>{row['Symbol']}</td>
                    <td>{row['Name']}</td>
                    <td>{industry_text}</td>
                    <td>{row['Price']}</td>
                    <td>{pe_ttm_str}</td>
                    <td>{row['Growth_Rate']}%</td>
                    <td>{vol_str}</td>
                    <td>{peg_str}</td>
                    <td>{startup_flag}</td>
                    <td>{pchg_str}</td>
                    <td style="font-size:12px; color:#555;">{remark}</td>
                </tr>
                """
            
            html_table = f"<div class='table-container'><table class='table'>{table_header}{rows}</table></div>"
            
            # Logic Explanation Footer
            logic_footer = """
            <div class="logic-footer">
                <h4 style="margin-top:0; color:#444;">🧠 智能选股策略说明 (Top 3 精选)</h4>
                <div class="logic-bullet"><strong>1. 硬科技赛道 (Hard Tech):</strong> 仅聚焦于电子、半导体、人工智能、新能源等战略性产业。</div>
                <div class="logic-bullet"><strong>2. 困境翻转 (Turnaround):</strong> 净利润增速 > 50% 且 估值大幅修复。</div>
                <div class="logic-bullet"><strong>3. 资金异动 (High Volume):</strong> 量比 > 1.5，主力资金显著流入。</div>
                <div class="logic-bullet"><strong>4. 蓄势待发 (Pre-Breakout):</strong> <span style="background:#e6f3ff; padding:0 3px;">蓝色高亮</span> 挖掘低位潜伏标的。逻辑：5日涨幅在 -3%~8% 之间（未暴涨），股价回踩 MA20 支撑有效，且 MACD 指标金叉向上，爆发潜力大。</div>
                <div class="logic-bullet"><strong>5. 启动阶段 (Startup Phase):</strong> <span style="background:#ffe6e6; padding:0 3px;">红色高亮</span> 代表技术面呈现 "缩量回调后放量上攻" 形态。</div>
                <div style="margin-top:15px; border-top:1px solid #ddd; padding-top:10px; font-size:12px;">
                    免责声明: 本报告由 AI 系统自动生成，仅用于辅助研究，不构成投资建议。<br>
                    数据来源: AkShare / 东方财富 / 腾讯财经
                </div>
            </div>
            """
            
            content = f"""
            <html>
            <head>{style}</head>
            <body>
            {gold_section}
            <h3 class="section-title">📊 潜力机会清单</h3>
            {html_table}
            {logic_footer}
            </body>
            </html>
            """
        else:
            subject = f"每日金股推荐 ({datetime.date.today()}): 暂无标的"
            content = "<p>今日未筛选出符合条件的标的。</p>"

        # Send to all receivers
        if self.sender_email and self.password and receivers:
            
            # Connect once
            try:
                if self.smtp_port == 465:
                    server = smtplib.SMTP_SSL(self.smtp_server, self.smtp_port)
                else:
                    server = smtplib.SMTP(self.smtp_server, self.smtp_port)
                    server.starttls()
                server.login(self.sender_email, self.password)
                
                for receiver in receivers:
                    print(f"Sending email to {receiver}...")
                    try:
                        message = MIMEMultipart()
                        message['From'] = Header(self.sender_email, 'utf-8')
                        message['To'] = Header(receiver, 'utf-8')
                        message['Subject'] = Header(subject, 'utf-8')
                        message.attach(MIMEText(content, 'html', 'utf-8'))
                        
                        server.sendmail(self.sender_email, receiver, message.as_string())
                    except Exception as e:
                        print(f"Failed to send to {receiver}: {e}")
                        
                server.quit()
                print("All emails sent.")
                
            except Exception as e:
                print(f"SMTP Error: {e}")
        else:
            print("--- DRY RUN (Missing Credentials) ---")
            print(f"Subject: {subject}")
            print(f"Receivers: {receivers}")
            print("Content Snippet:")
            print(content[:500] + "...")
            print("--- END DRY RUN ---")
            print("content truncated")
            print("--- END DRY RUN ---")
            print("--- DRY RUN (Missing Credentials) ---")
            print(f"Subject: {subject}")
            print(f"Receiver: {receiver_email or 'Not Scecisied'}")
            print("Content Snippet:")
            print(content[:500] + "...")
            print("--- END DRY RUN ---")
            return True

if __name__ == "__main__":
    # Test
    import pandas as pd
    df = pd.DataFrame({
        'Symbol': ['000001', '600519'],
        'Name': ['Test Stock A', 'Test Stock B'],
        'Price': [10.5, 1500.0],
        'PEG': [0.5, 0.8]
    })
    notifier = EmailNotifier()
    notifier.send_recommendation_report(None, df)
