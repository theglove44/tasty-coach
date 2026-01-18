
import sys
import os
from tastytrade import Account
sys.path.append(os.getcwd())
try:
    from utils.tasty_client import TastyClient
except ImportError:
    # If we are in the root dir, this might work if we set PYTHONPATH or just rely on cwd
    pass

def inspect_margin():
    client = TastyClient()
    session = client.get_session()
    account = client.get_account()
    
    print(f"Inspecting margin reqs for: {account.account_number}")
    try:
        # Try both methods if they exist
        if hasattr(account, 'get_margin_requirements'):
            mr = account.get_margin_requirements(session)
            print("\n--- Margin Requirements ---")
            print(mr)
            
        if hasattr(account, 'get_effective_margin_requirements'):
            emr = account.get_effective_margin_requirements(session, account.symbol) if hasattr(account, 'symbol') else None
            # Actually get_effective likely needs a symbol, which implies it's per-symbol, not portfolio-wide
            print("\n(Skipping effective margin as it likely requires a symbol argument)")
            
    except Exception as e:
        print(f"Error fetching margin: {e}")

if __name__ == "__main__":
    inspect_margin()
