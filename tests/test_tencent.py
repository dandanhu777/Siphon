
import requests

def test_tencent():
    url = "http://qt.gtimg.cn/q=sh600519"
    resp = requests.get(url)
    content = resp.text
    # v_sh600519="1~名字~..."
    if '="' in content:
        data = content.split('="')[1].strip('";')
        parts = data.split('~')
        for i, val in enumerate(parts):
            print(f"Index {i}: {val}")

if __name__ == "__main__":
    test_tencent()
