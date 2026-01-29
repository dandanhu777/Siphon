import requests
import time

STOCKS = ["sh600651", "sz002230", "sz300373"]

print("=== Debugging Direct Sina Connection ===")

def get_sina_price(code_list):
    # Format: sh600651,sz002230
    list_str = ",".join(code_list)
    url = f"http://hq.sinajs.cn/list={list_str}"
    print(f"Requesting: {url}")
    
    try:
        headers = {'Referer': 'https://finance.sina.com.cn/'}
        resp = requests.get(url, headers=headers, timeout=5)
        print(f"Status Code: {resp.status_code}")
        content = resp.text
        print(f"Content Preview: {content[:100]}...")
        
        # Parse
        lines = content.strip().split('\n')
        for line in lines:
            if not line: continue
            # var hq_str_sh600651="飞乐音响,8.290,..."
            parts = line.split('=')
            if len(parts) < 2: continue
            
            code_part = parts[0].split('_')[-1] # sh600651
            data_part = parts[1].replace('"', '')
            data_fields = data_part.split(',')
            
            if len(data_fields) > 3:
                name = data_fields[0]
                open_p = data_fields[1]
                prev_close = data_fields[2]
                current = data_fields[3]
                print(f"✅ Success: {code_part} | {name} | Cur: {current}")
            else:
                print(f"⚠️ Empty Data for {code_part}")
                
    except Exception as e:
        print(f"❌ Connection Failed: {e}")

if __name__ == "__main__":
    get_sina_price(STOCKS)
