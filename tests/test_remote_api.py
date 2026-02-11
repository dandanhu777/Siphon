
import requests
import json
import time

BASE_URL = "http://39.97.254.198:8045/v1"
API_KEY = "sk-ff1c3f6a304b456d8584291e76fb4742"  # Using the key seen in previous files

def test_connectivity():
    print(f"Testing connectivity to {BASE_URL}...")
    
    # 1. Test /models endpoint (Standard OpenAI)
    try:
        url = f"{BASE_URL}/models"
        print(f"GET {url}")
        resp = requests.get(url, headers={"Authorization": f"Bearer {API_KEY}"}, timeout=5)
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
            print("✅ Models endpoint accessible.")
            print("Models:", json.dumps(resp.json(), indent=2)[:200] + "...")
        else:
            print(f"❌ Failed to list models. Response: {resp.text}")
    except Exception as e:
        print(f"❌ Connection Error (Models): {e}")

    # 2. Test Chat Completion
    try:
        url = f"{BASE_URL}/chat/completions"
        payload = {
            "model": "gemini-2.5-flash", # or gpt-3.5-turbo, trying generic
            "messages": [{"role": "user", "content": "Hello, are you working?"}],
            "max_tokens": 10
        }
        print(f"\nPOST {url}")
        resp = requests.post(url, json=payload, headers={"Authorization": f"Bearer {API_KEY}"}, timeout=10)
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
            print("✅ key Chat completion success.")
            print("Response:", resp.json())
        else:
            print(f"❌ Chat completion failed. Response: {resp.text}")
            
    except Exception as e:
        print(f"❌ Connection Error (Chat): {e}")

if __name__ == "__main__":
    test_connectivity()
