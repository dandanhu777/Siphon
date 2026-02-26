import requests
from requests.sessions import Session
import warnings

# Suppress warnings
warnings.filterwarnings('ignore')

# --- Global Header Spoofing for Akshare (Anti-Bot Bypass) ---
# We patch Session.request because most libraries (including akshare) 
# eventually use a Session or the functional API which uses a default session.
original_session_request = Session.request

def spoofed_session_request(self, method, url, *args, **kwargs):
    headers = kwargs.get('headers', {})
    if not headers:
        headers = {}
    else:
        headers = headers.copy()
        
    if 'User-Agent' not in headers:
        # Standard realistic browser UA
        headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    
    # Extra browser headers for realism
    if 'Accept' not in headers:
        headers['Accept'] = 'application/json, text/plain, */*'
    if 'Accept-Language' not in headers:
        headers['Accept-Language'] = 'zh-CN,zh;q=0.9,en;q=0.8'
    if 'Connection' not in headers:
        headers['Connection'] = 'keep-alive'
    
    # Set a default timeout if not provided to prevent hanging
    if 'timeout' not in kwargs:
        kwargs['timeout'] = 30
    
    kwargs['headers'] = headers
    return original_session_request(self, method, url, *args, **kwargs)

# Functional API patch
original_api_request = requests.api.request
def spoofed_api_request(method, url, **kwargs):
    if 'headers' not in kwargs:
        kwargs['headers'] = {}
    else:
        kwargs['headers'] = kwargs['headers'].copy()
        
    if 'User-Agent' not in kwargs['headers']:
        kwargs['headers']['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    
    if 'timeout' not in kwargs:
        kwargs['timeout'] = 30
        
    return original_api_request(method, url, **kwargs)

def apply_patch():
    """Apply the request monkeypatch globally."""
    Session.request = spoofed_session_request
    requests.api.request = spoofed_api_request
    requests.request = spoofed_api_request
    # Also patch the shortcuts
    requests.get = lambda url, **kwargs: spoofed_api_request('GET', url, **kwargs)
    requests.post = lambda url, **kwargs: spoofed_api_request('POST', url, **kwargs)
    print("✅ Global Request Patch Applied (Header Spoofing & Timeouts Active)")

# Apply immediately on import
apply_patch()
