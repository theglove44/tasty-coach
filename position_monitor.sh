#!/bin/bash
# Position Monitor - Alert on actionable conditions
# Runs hourly during trading hours

SCRIPT_DIR="$HOME/Projects/tasty-coach"
LOG_FILE="$HOME/.openclaw/logs/position-monitor.log"

# Config
PROFIT_THRESHOLD=0.40  # 40% of credit
LOSS_THRESHOLD=1.00     # 100% of credit (max loss)
ROLL_DTE_THRESHOLD=21   # Alert for rolls if DTE <= 21

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# Check if we're in trading hours (9:30 AM - 4:00 PM ET, Mon-Fri)
is_trading_hours() {
    # Get current time in ET
    ET_NOW=$(TZ="America/New_York" date +%H%M)
    DOW=$(date +%u)  # 1=Monday, 5=Friday
    
    # Trading hours: 0930-1600 ET, Mon-Fri
    if [ "$DOW" -ge 1 ] && [ "$DOW" -le 5 ]; then
        if [ "$ET_NOW" -ge "0930" ] && [ "$ET_NOW" -lt "1600" ]; then
            return 0
        fi
    fi
    return 1
}

if ! is_trading_hours; then
    log "Outside trading hours - skipping"
    exit 0
fi

log "Running position check..."

# Get positions via tasty-coach
cd "$SCRIPT_DIR"
source venv/bin/activate

# Get account positions as JSON
POSITIONS=$(python -c "
import asyncio
import os
import sys
from dotenv import load_dotenv
sys.path.insert(0, '.')
from utils.tasty_client import TastyClient

async def main():
    client = await TakyClient.create()
    portfolio = await client.get_portfolio()
    positions = await portfolio.get_positions()
    
    for pos in positions:
        print(f'{pos.symbol}|{pos.quantity}|{pos.realized_pl}')
" 2>&1)

if [ $? -ne 0 ] || [ -z "$POSITIONS" ]; then
    log "Failed to get positions"
    exit 1
fi

ALERT_MSG=""

# Check each position for actionable conditions
while IFS='|' read -r symbol quantity pl; do
    # Get position details
    DETAILS=$(python -c "
import asyncio
import os
import sys
from dotenv import load_dotenv
sys.path.insert(0, '.')
from utils.tasty_client import TastyClient
import json

async def main():
    client = await TakyClient.create()
    # This is simplified - we'd need actual position data
    print('{}')
" 2>&1)
    
done <<< "$POSITIONS"

# This approach won't work easily - let's simplify and use the existing report

python -c "
import asyncio
import os
import sys
from dotenv import load_dotenv
sys.path.insert(0, '.')
from utils.tasty_client import TastyClient

async def main():
    client = await TakyClient.create()
    account = await client.get_account()
    positions = await account.get_positions(session=client.session)
    
    alerts = []
    
    for p in positions:
        # Get trade price and current value
        entry_cost = abs(p.cost) if p.cost else 0
        current_value = abs(p.market_value) if p.market_value else 0
        
        # Calculate P/L percentage of credit
        if entry_cost > 0:
            pl_pct = (current_value - entry_cost) / entry_cost
            
            # Check profit threshold (40%)
            if pl_pct >= $PROFIT_THRESHOLD:
                alerts.append(f'PROFIT: {p.symbol} at {pl_pct:.0%} of entry')
            
            # Check loss threshold (100%)
            if pl_pct <= -$LOSS_THRESHOLD:
                alerts.append(f'LOSS: {p.symbol} at {pl_pct:.0%} of entry')
    
    if alerts:
        print('\\n'.join(alerts))
    else:
        print('NO_ALERTS')
" 2>&1

