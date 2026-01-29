from openai import OpenAI
import json
import os

# Config
API_KEY = "sk-ff1c3f6a304b456d8584291e76fb4742"
BASE_URL = "http://127.0.0.1:8045/v1"
MODEL_NAME = "gemini-2.5-flash"

def enrich_top_picks(stock_list):
    """
    Takes stock list. Returns enrichment dict.
    Fields: business, us_bench, target_price
    """
    data_map = {}
    
    # --- Expert Fallback Data (Historical + Current) ---
    fallback_data = {
        # Current Top Picks (Examples)
        "300373": {
            "business": "功率半导体IDM龙头，车规级产品放量。",
            "us_bench": "ON Semi (ON)",
            "target_price": "85.50 (前高压力)"
        },
        "002245": {
            "business": "圆柱电池与LED双轮驱动，消费电子复苏。",
            "us_bench": "Enovix (ENVX)",
            "target_price": "21.80 (箱体上沿)"
        },
        "600651": { # 飞乐音响
            "business": "老牌音响转型，国资背景下的资产整合。",
            "us_bench": "Sonos (SONO)",
            "target_price": "9.50 (补涨预期)"
        },
        
        # Historical Tracking Stocks (Visible in User Screenshot)
        "002230": { # 科大讯飞
            "business": "亚太人工智能计算领军，星火大模型赋能教育医疗。",
            "us_bench": "Nuance (NUAN) / Google",
            "target_price": "65.00"
        },
        "300738": { # 奥飞数据
            "business": "华南IDC龙头，液冷数据中心绑定互联网巨头。",
            "us_bench": "Equinix (EQIX)",
            "target_price": "25.00"
        },
        "688052": { # 纳芯微
            "business": "传感器与隔离芯片龙头，受益汽车电子国产化。",
            "us_bench": "Analog Devices (ADI)",
            "target_price": "210.00"
        },
        "600776": { # 东方通信
            "business": "专网通信老兵，国资云与算力新基建预期。",
            "us_bench": "Motorola Solutions (MSI)",
            "target_price": "23.50"
        },
        "603092": {
            "business": "风电齿轮箱精密制造，受益海上风电抢装。",
            "us_bench": "Vestas (VWS)",
            "target_price": "78.00"
        },
        "000100": { # TCL科技
            "business": "面板行业周期反转，OLED产能爬坡改善盈利。",
            "us_bench": "LG Display (LPL)",
            "target_price": "5.20"
        },
        "600563": { # 法拉电子
            "business": "薄膜电容全球龙头，新能源车/光伏双赛道驱动。",
            "us_bench": "Vishay (VSH)",
            "target_price": "125.00"
        }
    }
    
    if not stock_list: return {}
    
    print(f"🧠 Asking {MODEL_NAME} to enrich {len(stock_list)} stocks...")
    
    try:
        items_str = ""
        for s in stock_list:
            items_str += f"- {s['name']} ({s['code']})\n"
            
        prompt = f"""
        For these A-share stocks, provide VALID JSON ONLY (No Markdown, No ```):
        1. **business**: Core business highlight (Chinese, <20 chars).
        2. **us_bench**: US comparable ticker.
        3. **target_price**: A conservative technical target price estimation or key resistance level (Chinese, e.g., "around 50.0").
        
        Stocks:
        {items_str}
        
        Format: {{ "CODE": {{ "business": "...", "us_bench": "...", "target_price": "..." }} }}
        IMPORTANT: Ensure all property names are enclosed in double quotes. Escape any double quotes inside strings.
        """
        
        client = OpenAI(api_key=API_KEY, base_url=BASE_URL, timeout=30.0)
        response = client.chat.completions.create(
            model=MODEL_NAME, 
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3, # Lower temp for stability
            max_tokens=1000
        )
        content = response.choices[0].message.content.strip()
        print(f"DEBUG LLM OUTPUT: {content[:100]}...") # Debug log
        
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
            
        api_data = json.loads(content)
        data_map.update(api_data)
        
        # Merge fallback if missing only
        for k, v in fallback_data.items():
            if k not in data_map:
                data_map[k] = v
                
        return data_map
        
    except Exception as e:
        print(f"⚠️ Gemini Enrichment Failed: {e}")
        try:
            # 2. DeepSeek Fallback
            print("🔄 Attempting DeepSeek Fallback...")
            ds_key = os.getenv("LLM_API_KEY")
            if not ds_key: raise Exception("No LLM_API_KEY")
            
            client = OpenAI(api_key=ds_key, base_url="https://api.deepseek.com", timeout=30.0)
            response = client.chat.completions.create(
                model="deepseek-chat", messages=[{"role": "user", "content": prompt}]
            )
            content = response.choices[0].message.content.strip()
            if "```json" in content: content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content: content = content.split("```")[1].split("```")[0].strip()
            return json.loads(content)

        except Exception as e2:
            print(f"⚠️ AI Failed ({e2}). Attempting AkShare Deterministic Fallback...")
            
            # 3. AkShare Deterministic Fallback (CNINFO)
            import akshare as ak
            import time
            fallback_map = {}
            
            for stock in stock_list:
                code = stock['code']
                business_text = "Unknown"
                
                # Try CNINFO first (Robust)
                try:
                    df = ak.stock_profile_cninfo(symbol=code)
                    if not df.empty:
                        row = df.iloc[0]
                        ind = row.get('所属行业')
                        bus = row.get('主营业务')
                        if bus:
                            business_text = bus
                        elif ind:
                            business_text = f"属于 {ind} 行业"
                except Exception as e_cn:
                    print(f"    [Fallback] CNINFO failed for {code}: {e_cn}")
                    
                    # Try EM if CNINFO fails
                    try:
                        df_em = ak.stock_individual_info_em(symbol=code)
                        info = dict(zip(df_em['item'], df_em['value']))
                        ind = info.get('行业')
                        if ind: business_text = f"属于 {ind} 行业"
                    except:
                        pass
                
                fallback_map[code] = {
                    "business": business_text[:100], # Trucate
                    "us_bench": "-",
                    "target_price": "-"
                }
            
            # Merge with hardcoded data for any known ones
            for k, v in fallback_data.items():
                fallback_map[k] = v
                
            return fallback_map
