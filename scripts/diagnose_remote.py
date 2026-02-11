
import requests
import json

BASE_URL = "http://39.97.254.198:8045" # specific OneAPI base, usually port 3000 but here 8045
API_KEY = "sk-ff1c3f6a304b456d8584291e76fb4742"

def diagnose():
    print(f"Diagnosing {BASE_URL} with key prefix {API_KEY[:8]}...")
    
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }

    # 1. Check User Status (Balance, Quota, Groups)
    try:
        url = f"{BASE_URL}/api/user/self"
        print(f"\n--- Checking User Status ({url}) ---")
        resp = requests.get(url, headers=headers, timeout=5)
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            if data.get('success'):
                user = data.get('data', {})
                print(f"User: {user.get('username')}")
                print(f"Role: {user.get('role')} (100=Admin, 10=User, 1=Guest)")
                print(f"Group: {user.get('group')}")
                print(f"Quota: {user.get('quota')} (Used: {user.get('used_quota')})")
                print(f"Balance: {user.get('balance')}")
            else:
                print("Failed:", data.get('message'))
        else:
            print(f"Not reachable: {resp.text}")
    except Exception as e:
        print(f"Error checking user: {e}")

    # 2. Check Channels (Requires Admin)
    try:
        url = f"{BASE_URL}/api/channel/" 
        # Note: OneAPI usually requires params like ?p=0&size=10
        print(f"\n--- Checking Channels (Admin Only) ---")
        resp = requests.get(f"{url}?p=0&size=20", headers=headers, timeout=5)
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            if data.get('success'):
                channels = data.get('data', [])
                print(f"Found {len(channels)} channels.")
                for c in channels:
                    print(f"[{c['id']}] {c['name']} ({c['type']}) - Status: {c['status']} - ResponseTime: {c['response_time']}ms")
                    if c.get('test_time'):
                         print(f"    Last Test: {c.get('test_time')}")
            else:
                print("Failed to list channels:", data.get('message'))
        else:
            print("Access Denied (Not Admin or API not exposed)")
    except Exception as e:
        print(f"Error checking channels: {e}")

if __name__ == "__main__":
    diagnose()
