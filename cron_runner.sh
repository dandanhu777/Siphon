#!/bin/bash
# ===========================================
# cron_runner.sh — 阿里云定时任务入口
# 由 crontab 调用，负责：
#   1. 设置环境
#   2. 检查交易日
#   3. 执行策略 + 发送报告
# ===========================================

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

# 日志
LOG_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/cron_$(date +%Y%m%d_%H%M).log"

exec > "$LOG_FILE" 2>&1

echo "=========================================="
echo "🕐 Cron Runner Start: $(date '+%Y-%m-%d %H:%M:%S')"
echo "=========================================="

# 1. 激活虚拟环境
source "$PROJECT_DIR/venv/bin/activate"

# 2. 加载环境变量
if [ -f "$PROJECT_DIR/.env" ]; then
    set -a && source "$PROJECT_DIR/.env" && set +a
    echo "✅ .env loaded"
fi

# 3. 检查交易日
echo "📅 Checking trading day..."
python "$PROJECT_DIR/scripts/check_trading_day.py"
if [ $? -ne 0 ]; then
    echo "⏸️ Not a trading day. Exiting."
    exit 0
fi

# 4. 运行策略
echo ""
echo "📊 Running Siphon Strategy..."
python "$PROJECT_DIR/siphon_strategy.py"

if [ $? -ne 0 ]; then
    echo "❌ Strategy failed!"
    exit 1
fi
echo "✅ Strategy complete."

# 5. 同步追踪数据库
echo ""
echo "💾 Syncing tracker..."
python "$PROJECT_DIR/boomerang_tracker.py" --sync
python "$PROJECT_DIR/boomerang_tracker.py" --update

# 6. 发送报告
echo ""
echo "📧 Sending report..."
python "$PROJECT_DIR/fallback_email_sender.py"

if [ $? -eq 0 ]; then
    echo ""
    echo "=========================================="
    echo "✅ Report Sent Successfully! $(date '+%H:%M:%S')"
    echo "=========================================="
else
    echo "❌ Report failed!"
    exit 1
fi
