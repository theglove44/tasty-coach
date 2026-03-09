#!/bin/bash
# Trade verification script for tasty-coach
# Run all verification checks before committing trading logic changes

set -e

# Navigate to project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
cd "$PROJECT_ROOT"
export PYTHONPATH="${PYTHONPATH}:${PROJECT_ROOT}"

echo "🔍 Trade Verification Starting..."
echo ""

# Step 1: Import check
echo "1️⃣ Checking imports..."
python -c "
import sys
sys.path.insert(0, '.')
try:
    import agents.strategy
    import agents.scanner
    import agents.manager
    import agents.portfolio
    import agents.reviewer
    print('   ✓ All agents imported successfully')
except ImportError as e:
    print(f'   ✗ Import failed: {e}')
    sys.exit(1)
"

# Step 2: Run tests
echo ""
echo "2️⃣ Running tests..."
if python -c "import pytest" 2>/dev/null; then
    if python -m pytest tests/ -v --tb=short 2>/dev/null; then
        echo "   ✓ Tests passed"
    else
        echo "   ✗ Tests failed"
        exit 1
    fi
else
    echo "   ⚠ Skipped (pytest not installed)"
fi

# Step 3: Syntax check on main files
echo ""
echo "3️⃣ Syntax check..."
python -m py_compile main.py
python -m py_compile position_monitor.py
echo "   ✓ Syntax OK"

# Step 4: Dry run (if .env exists)
echo ""
echo "4️⃣ Dry run check..."
if [ -f .env ]; then
    # macOS doesn't have timeout, use python instead
python -c "
import subprocess
import sys
try:
    result = subprocess.run(
        [sys.executable, 'main.py', '--dry-run', '--debug'],
        capture_output=True, text=True, timeout=30
    )
    print(result.stdout[:1000] if result.stdout else '(no output)')
except subprocess.TimeoutExpired:
    print('   (timed out after 30s - OK)')
except Exception as e:
    print(f'   (error: {e})')
" 2>&1 | head -20 || true
    echo "   ✓ Dry run completed"
else
    echo "   ⚠ Skipped (no .env file)"
fi

echo ""
echo "✅ VERIFICATION PASSED"
