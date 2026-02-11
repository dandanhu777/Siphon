
import requests
import json

BASE_URL = "http://39.97.254.198:8045/v1"
API_KEY = "sk-ff1c3f6a304b456d8584291e76fb4742"

MODELS_TO_TEST = [
    "claude-3-5-sonnet-20240620",
    "gpt-3.5-turbo",
    "gpt-4o",
    "gemini-2.0-flash-exp"
]

def test_models():
    print(f"Testing models on {BASE_URL}...")
    
    for model in MODELS_TO_TEST:
        print(f"\n--- Testing {model} ---")
        try:
            resp = requests.post(
                f"{BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {API_KEY}"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "Hello, are you working?"}]
                },
                timeout=10
            )
            
            if resp.status_code == 200:
                content = resp.json()['choices'][0]['message']['content']
                print(f"Response: {content}")
                if "Antigravity is no longer supported" not in content:
                    print(f"🎉 SUCCESS! Model {model} is WORKING!")
                    return
            else:
                print(f"Error {resp.status_code}: {resp.text}")
                
        except Exception as e:
            print(f"Exception: {e}")

    print("\n❌ All tested models returned the error or failed.")

if __name__ == "__main__":
    test_models()
