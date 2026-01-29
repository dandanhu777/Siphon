#!/bin/bash

# Navigate to script directory
cd "$(dirname "$0")"

echo "========================================"
echo "🚀 Starting Daily Siphon System v4.1"
echo "========================================"
echo "Date: $(date)"

# 1. Run Data Strategy (Fetch Fresh Data)
echo "Step 1: Running Strategy (Fetching Data)..."
python3 siphon_strategy.py

if [ $? -eq 0 ]; then
    echo "✅ Strategy Execution Success."
else
    echo "❌ Strategy Execution Failed."
    exit 1
fi

# 2. Generate and Send Report
echo "Step 2: Generating Report..."
python3 fallback_email_sender.py

if [ $? -eq 0 ]; then
    echo "========================================"
    echo "✅ Report Sent Successfully."
    echo "========================================"
else
    echo "========================================"
    echo "❌ Report Generation Failed."
    echo "========================================"
fi
