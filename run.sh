#!/bin/bash

# Navigate to script directory
cd "$(dirname "$0")"

echo "=========================================="
VERSION=$(cat VERSION)
echo "🚀 Daily Siphon System v$VERSION"
echo "=========================================="
echo "Date: $(date)"
echo ""

# Ensure no test mode override
unset MAIL_RECEIVER

# 0. Activate virtual environment
echo "📦 Step 0: Activating virtual environment..."
source venv/bin/activate
echo "✅ Virtual environment activated."

# Load environment variables from .env
if [ -f .env ]; then
    set -a && source .env && set +a
    echo "✅ Environment variables loaded from .env"
fi

# 0.1: Disable proxy for domestic sites (eastmoney, sina, etc)
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY
echo "✅ Proxy disabled for data fetching."
echo ""

# 0.5: Trading Day Check
echo "📅 Step 0.5: Checking if today is a trading day..."
python scripts/check_trading_day.py
if [ $? -ne 0 ]; then
    echo "⏸️  Not a trading day (Holiday/Weekend). Exiting..."
    exit 0
fi
echo ""

# 1. Run Siphon Strategy v5.0 (Composite Scoring)
echo "📊 Step 1: Running Strategy v5.0 (Composite Scoring)..."
python siphon_strategy.py

if [ $? -eq 0 ]; then
    echo "✅ Strategy Execution Success."
else
    echo "❌ Strategy Execution Failed."
    exit 1
fi

# 1.2: Data Freshness Check
echo ""
echo "🔍 Step 1.2: Verifying Data Freshness..."
CSV_DATE=$(stat -f "%Sm" -t "%Y-%m-%d" siphon_strategy_results.csv 2>/dev/null || date +%Y-%m-%d)
TODAY=$(date +%Y-%m-%d)
if [ "$CSV_DATE" != "$TODAY" ]; then
    echo "⚠️ Warning: CSV date ($CSV_DATE) != Today ($TODAY)"
    echo "   Data may be stale. Continuing anyway..."
else
    echo "✅ Data Fresh (Updated: $TODAY)"
fi

# 1.5: Sync to Tracking Database (Boomerang)
echo ""
echo "💾 Step 1.5: Syncing to Tracking Database..."
python boomerang_tracker.py --sync
python boomerang_tracker.py --update  # New: Fetch fresh prices for all tracked items

if [ $? -eq 0 ]; then
    echo "✅ Database Sync & Update Complete."
else
    echo "⚠️ Database Sync Warning (non-fatal)."
fi

# 2. Generate and Send Report (with Data Inspector)
echo ""
echo "📧 Step 2: Generating Report (Inspector Active)..."
python fallback_email_sender.py

if [ $? -eq 0 ]; then
    echo ""
    echo "=========================================="
    echo "✅ v$VERSION Report Sent Successfully!"
    echo "=========================================="
else
    echo ""
    echo "=========================================="
    echo "❌ Report Generation Failed."
    echo "=========================================="
    exit 1
fi
