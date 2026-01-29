
from openai import OpenAI
import smtplib
from email.mime.text import MIMEText
from email.header import Header
from email.mime.multipart import MIMEMultipart
import datetime
import os

# ================= 必须配置区 (USER CONFIG) =================
# 1. API Configuration (Local Proxy)
API_KEY = "sk-ff1c3f6a304b456d8584291e76fb4742"
BASE_URL = "http://127.0.0.1:8045/v1"
MODEL_NAME = "gemini-2.5-flash"

# 2. 邮箱配置 (SMTP)
MAIL_HOST = "smtp.gmail.com"
MAIL_PORT = 465
MAIL_USER = "leavertondrozdowskisu239@gmail.com"     # 发件人账号
MAIL_PASS = "saimfxiilntucmph"          # 邮箱授权码
MAIL_RECEIVERS = [
     "28595591@qq.com",
     "89299772@qq.com",
     "milsica@gmail.com",
     "tosinx@gmail.com",
     "32598630@qq.com",
     "840276240@qq.com"
]

# 3. 公开研报背景 (Public Context)
PUBLIC_CONTEXT = """
【角色设定】
你是一位客观、严谨的各种A股市场独立分析师。
你的职责是为大众投资者提供不带偏见、基于数据和逻辑的每日行情研判。
所有分析必须基于“独立抗重力”算法逻辑，不考虑任何特定个人的持仓。
"""
# =======================================================

def analyze_and_report(scout_data: str, top_pick_data: str = None, attachment_path=None):
    """
    Takes the stock list found by the Scout Agent, sends it to Gemini Commander via Local Proxy, 
    and emails the final order to the user.
    """
    print(f"🔄 正在呼叫指挥官审查数据 (Via Proxy: {BASE_URL})...")
    
    # --- 步骤 1: 调用 API 进行审查 (OpenAI Protocol) ---
    try:
        client = OpenAI(api_key=API_KEY, base_url=BASE_URL, timeout=5.0)
        
        prompt = f"""
        {PUBLIC_CONTEXT}

        【任务: Project Siphon v3.0 (The Pre-Breakout Hunter)】
        你正在分析一份基于“v3.0 潜伏虹吸”算法筛选的名单。
        核心逻辑：**寻找尚未大涨、正在“静默吸筹”的标的，坚决回避已大涨的热门股。**
        
        请重点解读 Top 1 标的：
        
        1. **👑 核心指令：Top 1 潜伏深度研判 (Pre-Breakout Analysis)**
           - **反追高核查 (Anti-Chase)**：确认该标的近期没有经历>15%的暴涨，属于“底部/腰部启动前夕”。
           - **虹吸特征 (Siphon)**：它是如何在大盘疲软时（Market Weak）保持价格坚挺或小幅攀升的？
           - **量能压缩 (VCP)**：是否存在“缩量回调”或“极致缩量”的洗盘迹象？（关注成交量变化）
           - **研判结论**：给出潜伏价值评估（极高/中等/观察）。

        2. **全员扫描**
           - 简要点评其他候选（重点寻找各行业的“补涨龙”）。

        【侦察兵 Top 1 详细情报 (v2.0 Data)】
        {top_pick_data if top_pick_data else "无特别详细数据，请基于列表第一名分析"}

        【侦察兵原始名单】
        {scout_data}

        【输出格式】
        **重要：直接输出内容，不要有任何角色扮演的开场白（如“作为分析师...”）。**
        请以“公开市场研报”格式输出：
        1. **👑 Siphon v3.0 冠军深度剖析**：(直击要点，逻辑严密)
        2. **📋 候选标的快速点评**：(如有)
        """
        
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "You are a specialized financial trading assistant. You are decisive, strategic, and ruthless."},
                {"role": "user", "content": prompt}
            ]
        )
        commander_review = response.choices[0].message.content
        
    except Exception as e:
        print(f"API Error: {e}")
        commander_review = f"分析失败 (API Error): {str(e)}\n\n(请检查代理连接)"

    # --- 步骤 2: 发送邮件 (DISABLED in v4.1) ---
    print("📧 Legacy Email Sending Disabled (v4.1 uses fallback_email_sender.py)")
    return

    # print(f"📧 正在发送研报邮件 (To {len(MAIL_RECEIVERS)} Recipients)...")
    # current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    
    # message = MIMEMultipart()
    # message['From'] = Header("The Gemini Commander", 'utf-8')
    # message['To'] = Header("Siphon Squad", 'utf-8')
    # subject_text = f"Project Siphon v3.0 Daily Report ({current_time})"
    # message['Subject'] = Header(subject_text, 'utf-8')
    
    # # Email Body
    # body_text = f"""
    # {commander_review}

    # [Scout Data Reference]
    # {scout_data}
    # """
    # message.attach(MIMEText(body_text, 'plain', 'utf-8'))
    
    # # Attachment
    # if attachment_path and os.path.exists(attachment_path):
    #     att = MIMEText(open(attachment_path, 'rb').read(), 'base64', 'utf-8')
    #     att["Content-Type"] = 'application/octet-stream'
    #     att["Content-Disposition"] = f'attachment; filename="siphon_results.csv"'
    #     message.attach(att)

    # try:
    #     smtp_obj = smtplib.SMTP_SSL(MAIL_HOST, MAIL_PORT)
    #     smtp_obj.login(MAIL_USER, MAIL_PASS)
    #     smtp_obj.sendmail(MAIL_USER, MAIL_RECEIVERS, message.as_string())
    #     smtp_obj.quit()
    #     print("✅ 研报已发送 (Sent).")
    # except smtplib.SMTPException as e:
    #     print(f"❌ 邮件发送失败: {e}")
