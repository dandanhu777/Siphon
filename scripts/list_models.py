
import requests
import json

BASE_URL = "http://39.97.254.198:8045/v1"
API_KEY = "sk-ff1c3f6a304b456d8584291e76fb4742"

def list_models():
    print(f"Listing models from {BASE_URL}...")
    try:
        url = f"{BASE_URL}/models"
        resp = requests.get(url, headers={"Authorization": f"Bearer {API_KEY}"}, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            models = data.get('data', [])
            print(f"Found {len(models)} models:")
            for m in models:
                print(f" - {m['id']}")
        else:
            print(f"Failed: {resp.status_code} {resp.text}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    list_models()
