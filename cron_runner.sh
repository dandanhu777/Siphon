#!/bin/bash
# ===========================================
# Daily Siphon Auto-Runner
# Runs at 14:40 CST on weekdays only (optimal V10 T+2 entry time)
# Skips weekends (Sat/Sun) — no trading
# ===========================================

# Get day of week (1=Mon ... 7=Sun)
DOW=$(date +%u)

# Skip weekends
if [ "$DOW" -eq 6 ] || [ "$DOW" -eq 7 ]; then
    echo "$(date): Weekend — skipping." >> /Users/ddhu/stock_recommendation/logs/cron.log
    exit 0
fi

# Navigate to project
cd /Users/ddhu/stock_recommendation

# Ensure log directory exists
mkdir -p logs

# Run with timestamp logging
echo "========================================" >> logs/cron.log
echo "$(date): Cron triggered (DOW=$DOW)" >> logs/cron.log
echo "========================================" >> logs/cron.log

# Execute main pipeline, capture all output
./run.sh >> logs/cron.log 2>&1
EXIT_CODE=$?

echo "$(date): run.sh exited with code $EXIT_CODE" >> logs/cron.log
echo "" >> logs/cron.log
