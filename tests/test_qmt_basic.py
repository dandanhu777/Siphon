# test_qmt_basic.py
# 用于测试 QMT (MiniQMT) 连接和数据获取
# 请确保在安装了 xtquant 的环境（通常是 Windows + QMT 内置 Python 或独立 Python）中运行

import sys
import time
import datetime

def log(msg):
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}")

log("🚀 启动 QMT 连接测试...")

try:
    from xtquant import xtdata
    log("✅ 成功导入 xtquant 模块")
except ImportError:
    log("❌ 无法导入 xtquant。请检查：")
    log("   1. 是否在 QMT 的 Python 环境中运行？")
    log("   2. 是否已 pip install xtquant？")
    log("   3. (Mac) 本脚本需要在 Windows 虚拟机中运行。")
    sys.exit(1)

def test_market_data():
    log("\n--- 测试行情连接 (xtdata) ---")
    
    # 茅台
    code = '600519.SH'
    
    try:
        log(f"📡 正在订阅 {code} 行情...")
        xtdata.subscribe_quote(code, period='1d', start_time='', end_time='', count=0, callback=None)
        
        # Give it a moment to connect
        time.sleep(2)
        
        log(f"📥 获取全推数据...")
        full_tick = xtdata.get_full_tick([code])
        
        if full_tick and code in full_tick:
            data = full_tick[code]
            log(f"✅ 获取成功！")
            log(f"   Name: 贵州茅台")
            log(f"   Price: {data.get('lastPrice')} (Is valid: {data.get('lastPrice') > 0})")
            log(f"   Time: {data.get('time')}")
        else:
            log("⚠️ 未获取到数据。可能是：")
            log("   1. QMT 客户端未启动")
            log("   2. QMT 客户端未登录行情")
            log("   3. 需开启 '极速行情' 权限")

        # Test History K-line (Download)
        log("\n--- 测试历史数据下载 ---")
        xtdata.download_history_data(code, period='1d', start_time='20240101', end_time='20240110')
        kline = xtdata.get_market_data(field_list=[], stock_list=[code], period='1d', start_time='20240101', end_time='20240110')
        if not kline.empty:
             log(f"✅ 历史 K 线获取成功 ({len(kline)} 条记录)")
        else:
             log("⚠️ 历史 K 线为空")

    except Exception as e:
        log(f"❌ 行情测试出错: {e}")

if __name__ == "__main__":
    test_market_data()
    log("\n🏁 测试结束")
