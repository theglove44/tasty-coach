#!/usr/bin/env python3
"""
Position Monitor - Alert on actionable conditions during trading hours
Uses existing tasty-coach report and parses for actionable items
"""

import asyncio
import os
import re
import subprocess
import sys
from datetime import datetime
from dotenv import load_dotenv

# Thresholds
PROFIT_THRESHOLD = 0.40  # 40% of credit
LOSS_THRESHOLD = 1.00    # 100% of credit (max loss)

VENV_PYTHON = os.path.expanduser('~/Projects/tasty-coach/venv/bin/python')
REPORT_SCRIPT = os.path.expanduser('~/Projects/tasty-coach/main.py')


def is_trading_hours():
    """Check if we're in trading hours (9:30 AM - 4:00 PM ET, Mon-Fri)"""
    import pytz
    et = pytz.timezone('America/New_York')
    now_et = datetime.now(et)
    
    if now_et.weekday() >= 5:  # Weekend
        return False
    
    hour = now_et.hour
    minute = now_et.minute
    time_et = hour * 60 + minute
    
    market_open = 9 * 60 + 30  # 9:30 AM
    market_close = 16 * 60      # 4:00 PM
    
    return market_open <= time_et < market_close


def parse_report():
    """Run tasty-coach report and parse for positions"""
    env = os.environ.copy()
    env['PATH'] = f"{os.path.expanduser('~/Projects/tasty-coach/venv/bin')}:{env.get('PATH', '')}"
    
    result = subprocess.run(
        [VENV_PYTHON, REPORT_SCRIPT, '--report'],
        cwd=os.path.expanduser('~/Projects/tasty-coach'),
        capture_output=True,
        text=True,
        timeout=60,
        env=env
    )
    
    if result.returncode != 0:
        print(f"Report error: {result.stderr}")
        return None
    
    return result.stdout


def extract_positions(report_text):
    """Extract positions with P/L from report"""
    positions = []
    lines = report_text.split('\n')
    
    current_symbol = None
    
    for line in lines:
        # Check for symbol headers like "► ORCL" (may have leading space)
        if '►' in line:
            current_symbol = line.split('►')[1].strip()
            continue
        
        # Look for summary line with total P/L (has └──)
        if current_symbol and '└──' in line:
            # Parse P/L percentage - format: "    └── Iron Condor (Apr 17)   -13.50 | -10.3%"
            match = re.search(r'([\d.-]+)\s*\|\s*([\d.-]+)%', line)
            if match:
                pl_value = float(match.group(1))
                pl_pct = float(match.group(2))
                positions.append({
                    'symbol': current_symbol,
                    'pl_value': pl_value,
                    'pl_pct': pl_pct
                })
    
    return positions


def check_alerts(positions):
    """Check positions against thresholds"""
    alerts = []
    
    for pos in positions:
        pl = pos['pl_pct']
        
        # Check profit (positive P/L)
        if pl >= PROFIT_THRESHOLD * 100:
            alerts.append(f"✅ PROFIT: {pos['symbol']} at {pl:.0f}%")
        
        # Check loss (negative P/L)
        if pl <= -LOSS_THRESHOLD * 100:
            alerts.append(f"🔴 LOSS: {pos['symbol']} at {pl:.0f}%")
    
    return alerts


def send_telegram(message):
    """Send alert via Telegram"""
    import requests
    
    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID')
    if not token or not chat_id:
        print("Telegram not configured: set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID env vars")
        return False
    
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
    
    try:
        r = requests.post(url, data=data, timeout=10)
        return r.ok
    except Exception as e:
        print(f"Telegram error: {e}")
        return False


def main():
    # Override check if --force flag
    force = '--force' in sys.argv
    silent = '--silent' in sys.argv
    
    if not force and not is_trading_hours():
        et_now = datetime.now().strftime('%H:%M ET')
        print(f"[{datetime.now().strftime('%H:%M')}] Outside trading hours ({et_now}) - skipping")
        return
    
    print(f"[{datetime.now().strftime('%H:%M')}] Checking positions...")
    
    try:
        report = parse_report()
        if not report:
            print("Failed to get report")
            return
        
        positions = extract_positions(report)
        
        if not positions:
            print("No positions found")
            return
        
        alerts = check_alerts(positions)
        
        if alerts:
            alert_text = "\n".join([f"• {a}" for a in alerts])
            message = f"📊 *Position Monitor*\n\n{alert_text}"
            
            print(f"\n📊 POSITION ALERTS\n{alert_text}")
            
            # Send to Telegram if not silent
            if not silent:
                send_telegram(message)
                print("\n→ Telegram alert sent")
        else:
            print("No actionable alerts")
            
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    load_dotenv()
    main()
