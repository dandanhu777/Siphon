#!/bin/bash
# ===========================================
# 阿里云部署脚本 — Stock Recommendation System v9.0
# 一键安装依赖 + 配置定时任务
# ===========================================

set -e

echo "🚀 Deploying Siphon System to Alibaba Cloud..."

# 1. 系统依赖
echo "📦 Step 1: Installing system dependencies..."
sudo apt-get update -y && sudo apt-get install -y python3 python3-pip python3-venv git cron
# CentOS/Alinux: sudo yum install -y python3 python3-pip git cronie && sudo systemctl enable crond && sudo systemctl start crond

# 2. 项目目录
PROJECT_DIR="/home/$(whoami)/stock_recommendation"
echo "📂 Step 2: Setting up project at $PROJECT_DIR"

if [ ! -d "$PROJECT_DIR" ]; then
    echo "⚠️ Project directory not found. Please clone or upload your code first:"
    echo "   git clone <your-repo-url> $PROJECT_DIR"
    echo "   or: scp -r ./stock_recommendation user@server:~/"
    exit 1
fi

cd "$PROJECT_DIR"

# 3. Python 虚拟环境
echo "🐍 Step 3: Setting up Python venv..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
echo "✅ Dependencies installed."

# 4. 环境变量
echo "🔐 Step 4: Checking .env..."
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "⚠️ Created .env from template. Please edit it:"
    echo "   nano $PROJECT_DIR/.env"
    echo ""
    echo "   Required variables:"
    echo "   MAIL_USER=your_gmail@gmail.com"
    echo "   MAIL_PASS=your_app_password"
    echo "   MAIL_RECEIVERS_LIST=user1@qq.com,user2@gmail.com"
    echo ""
    echo "   After editing, re-run this script."
    exit 1
fi
echo "✅ .env found."

# 5. 日志目录
mkdir -p logs

# 6. 权限
chmod +x run.sh cron_runner.sh

# 7. 修复 cron_runner.sh 中的 macOS stat 语法
# Linux stat 语法不同，但 cron_runner.sh 不使用 stat，所以无需改动。
# run.sh 中的 stat 命令需要修复：
if grep -q 'stat -f' run.sh; then
    echo "🔧 Step 7: Fixing macOS stat syntax for Linux..."
    sed -i 's/stat -f "%Sm" -t "%Y-%m-%d"/stat -c "%y" | cut -d" " -f1/g' run.sh
    # Simpler: just use date from file modification time
    sed -i 's|CSV_DATE=.*|CSV_DATE=$(date -r siphon_strategy_results.csv +%Y-%m-%d 2>/dev/null \|\| date +%Y-%m-%d)|' run.sh
    echo "✅ Fixed."
fi

# 8. 安装 Crontab
echo "⏰ Step 8: Installing crontab (14:00 CST weekdays)..."
CRON_LINE="0 14 * * 1-5 $PROJECT_DIR/cron_runner.sh"

# Check if already installed
(crontab -l 2>/dev/null | grep -v "cron_runner.sh"; echo "$CRON_LINE") | crontab -
echo "✅ Crontab installed:"
crontab -l

# 9. 验证
echo ""
echo "=========================================="
echo "✅ Deployment Complete!"
echo "=========================================="
echo ""
echo "📋 Checklist:"
echo "  1. [确认] .env 已配置: cat $PROJECT_DIR/.env"
echo "  2. [测试] 手动运行一次: cd $PROJECT_DIR && ./run.sh"
echo "  3. [确认] 服务器时区为 CST: date"
echo "     如不是，执行: sudo timedatectl set-timezone Asia/Shanghai"
echo "  4. [确认] cron 服务运行中:"
echo "     systemctl status cron    (Ubuntu/Debian)"
echo "     systemctl status crond   (CentOS/Alinux)"
echo "  5. [监控] 查看日志: tail -f $PROJECT_DIR/logs/cron.log"
echo ""
