
import requests
import json
import socket
import urllib.parse

REMOTE_IP = "39.97.254.198"
API_PORT = 9090
SECRET = "996633"

def control_mihomo():
    base_url = f"http://{REMOTE_IP}:{API_PORT}"
    print(f"Connecting to Mihomo Controller at {base_url}...")
    
    headers = {
        "Authorization": f"Bearer {SECRET}" if SECRET else ""
    }

    try:
        resp = requests.get(f"{base_url}/proxies", headers=headers, timeout=5)
        print(f"GET /proxies Status: {resp.status_code}")
        
        if resp.status_code == 200:
            data = resp.json()
            proxies = data.get('proxies', {})
            
            # Target the specific group
            selector_name = '🔰 节点选择'
            
            if selector_name in proxies:
                selector = proxies[selector_name]
                print(f"\nSelector Group: [{selector_name}]")
                print(f"Current Node: {selector['now']}")
                print(f"Available Nodes: {len(selector['all'])}")
                
                # Check Delay
                now_node = proxies.get(selector['now'], {})
                history = now_node.get('history', [])
                last_delay = history[-1]['delay'] if history else "Unknown"
                print(f"Current Delay: {last_delay} ms")
                
                # List candidates
                print("--- Candidate Nodes ---")
                real_candidates = []
                for n in selector['all']:
                    # Filter out non-nodes, metadata, and Auto groups
                    if n not in ['DIRECT', 'REJECT', 'COMPATIBLE', 'PASS', selector['now']]:
                         if "有效期" not in n and "剩余" not in n: 
                             if "优选" not in n and "自动" not in n: # Exclude Auto groups
                                 real_candidates.append(n)
                
                # Prioritize US
                target_node = None
                for n in real_candidates:
                    if "US" in n or "美国" in n:
                        target_node = n
                        break
                if not target_node:
                    for n in real_candidates:
                        if "HK" in n or "香港" in n:
                             target_node = n
                             break
                if not target_node and real_candidates:
                     target_node = real_candidates[0]
                
                print("Filtered Candidates (First 5):", real_candidates[:5])
                print("-----------------------")
                
                # Switch Logic
                if target_node:
                    print(f"\n🔄 Attempting switch {selector_name} to: {target_node}")
                    
                    encoded_name = urllib.parse.quote(selector_name)
                    put_url = f"{base_url}/proxies/{encoded_name}"
                    
                    put_resp = requests.put(put_url, json={"name": target_node}, headers=headers)
                    if put_resp.status_code == 204:
                         print(f"✅ Switched successfully to {target_node}")
                    else:
                         print(f"❌ Switch failed: {put_resp.status_code} {put_resp.text}")
                else:
                     print("❌ No other real candidates found to switch to.")
            else:
                print(f"❌ Group {selector_name} not found.")
                print("Top Level Groups:", [k for k,v in proxies.items() if v['type'] == 'Selector'])
                
        elif resp.status_code == 401:
            print("❌ Access Denied.")
        else:
            print(f"❌ API Error: {resp.text}")
            
    except Exception as e:
        print(f"❌ Connection Error: {e}")

if __name__ == "__main__":
    control_mihomo()
