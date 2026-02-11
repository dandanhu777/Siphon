
import requests
import socket

REMOTE_IP = "39.97.254.198"
PROXY_PORT = 7890 # Default Mihomo/Clash port

def test_proxy_exposure():
    print(f"Testing remote proxy port {REMOTE_IP}:{PROXY_PORT}...")
    
    # 1. TCP Connect Test
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(3)
    result = sock.connect_ex((REMOTE_IP, PROXY_PORT))
    sock.close()
    
    if result == 0:
        print(f"✅ Port {PROXY_PORT} is OPEN. Attempting to use it as proxy...")
        
        proxies = {
            "http": f"http://{REMOTE_IP}:{PROXY_PORT}",
            "https": f"http://{REMOTE_IP}:{PROXY_PORT}"
        }
        
        try:
            # Try to fetch Google via this proxy
            resp = requests.get("https://www.google.com", proxies=proxies, timeout=5)
            print(f"Status: {resp.status_code}")
            if resp.status_code == 200:
                print("✅ Remote Proxy works! (Google Accessible)")
            else:
                print(f"❌ Connected to headers, but Google return {resp.status_code}")
        except Exception as e:
            print(f"❌ Proxy Connect Failed: {e}")
            
    else:
        print(f"❌ Port {PROXY_PORT} is CLOSED (Connection Refused/Timeout).")
        print("Mihomo is likely listening on 127.0.0.1 only, or firewall blocked.")

if __name__ == "__main__":
    test_proxy_exposure()
