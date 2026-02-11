
from openai import OpenAI
import time

# Remote Configuration
API_KEY = "sk-ff1c3f6a304b456d8584291e76fb4742"
BASE_URL = "http://39.97.254.198:8045/v1"
MODEL_NAME = "gpt-4o-mini"

def test_commander_logic():
    print(f"📡 Connecting to Remote Commander at {BASE_URL}...")
    
    client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    
    # 模拟 Siphon Strategy 传入的数据
    scout_data = """
    Index | Name | Code | Industry | Price | Range% | Ratio | Logic
    --------------------------------------------------------------------------------
    1 | 贵州茅台 | 600519 | 酿酒行业 | 1750.00 | +1.20% | 8.5 | RelStr VCP
    2 | 比亚迪 | 002594 | 汽车整车 | 260.50 | -0.50% | 7.2 | VCP
    """
    
    top_pick_data = """
    标的名称: 贵州茅台 (600519)
    当前价格: 1750.00
    Siphon Score: 8.5
    特征: RelStr VCP
    量能分析: VolRatio:0.8x, VCP(Contraction)
    """
    
    system_prompt = """
    You are the "Commander" of the Siphon Trading Team.
    Your job is to review the "Scout's" daily candidates and write a brief, professional HTML email body.
    
    Output Format:
    Return ONLY the HTML code for the analysis body (<div>...</div>). Do NOT include <html> or <body> tags.
    """
    
    user_prompt = f"""
    Here is the Scout Data:
    {scout_data}
    
    Top Pick Context:
    {top_pick_data}
    
    Please write a rigorous review.
    """
    
    try:
        start_time = time.time()
        print("🤔 Asking Commander for analysis...")
        
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.7,
            timeout=60
        )
        
        duration = time.time() - start_time
        content = response.choices[0].message.content
        
        print(f"\n✅ Commander Responded in {duration:.2f}s!")
        print("--- Response Preview ---")
        print(content[:500] + "...")
        print("------------------------")
        
        if "div" in content and "贵州茅台" in content:
            print("🎉 Validation Success: Content looks like valid HTML analysis.")
        else:
            print("⚠️ Validation Warning: Content might be malformed.")
            
    except Exception as e:
        print(f"❌ Commander Failed: {e}")

if __name__ == "__main__":
    test_commander_logic()
