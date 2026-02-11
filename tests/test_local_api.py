
import requests
import json
import time

BASE_URL = "http://127.0.0.1:8045/v1"
API_KEY = "sk-ff1c3f6a304b456d8584291e76fb4742"

def test_local_connectivity():
    print(f"Testing connectivity to LOCAL PROXY {BASE_URL}...")
    
    # 1. Test /models endpoint
    try:
        url = f"{BASE_URL}/models"
        print(f"GET {url}")
        resp = requests.get(url, headers={"Authorization": f"Bearer {API_KEY}"}, timeout=5)
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
            print("✅ Local Models endpoint accessible.")
        else:
            print(f"❌ Failed to list local models. Response: {resp.text}")
    except Exception as e:
        print(f"❌ Local Connection Error (Models): {e}")

    # 2. Test Chat Completion
    try:
        url = f"{BASE_URL}/chat/completions"
        payload = {
            "model": "gemini-2.5-flash", 
            "messages": [{"role": "user", "content": "Hello, are you working locally?"}],
            "max_tokens": 10
        }
        print(f"\nPOST {url}")
        resp = requests.post(url, json=payload, headers={"Authorization": f"Bearer {API_KEY}"}, timeout=10)
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
            print("✅ Local Chat completion success.")
            print("Response:", resp.json())
        else:
            print(f"❌ Local Chat completion failed. Response: {resp.text}")
            
    except Exception as e:
        print(f"❌ Local Connection Error (Chat): {e}")

if __name__ == "__main__":
    test_local_connectivity()
