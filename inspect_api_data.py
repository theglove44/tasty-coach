
import sys
import os
import logging
from tastytrade import Account
sys.path.append(os.getcwd())
from utils.tasty_client import TastyClient

def inspect_data():
    client = TastyClient()
    session = client.get_session()
    if not session:
        print("Failed to get session")
        return

    account = client.get_account()
    print(f"Inspecting account: {account.account_number}")

    # Inspect Balances
    try:
        balances = account.get_balances(session)
        print("\n--- Balance Fields ---")
        # vars() or .dict() depending on the object type (pydantic or regular class)
        # We'll try to convert to dict or print dir() excluding privates
        params = vars(balances) if hasattr(balances, '__dict__') else balances.dict() if hasattr(balances, 'dict') else {}
        if not params:
            # Fallback if it's a pydantic model v2 or something else
            params = {k: getattr(balances, k) for k in dir(balances) if not k.startswith('_') and not callable(getattr(balances, k))}
        
        for k, v in params.items():
            print(f"{k}: {type(v).__name__}")
            
    except Exception as e:
        print(f"Error fetching balances: {e}")

    # Inspect Positions
    try:
        positions = account.get_positions(session)
        print(f"\n--- Position Fields (found {len(positions)} positions) ---")
        if positions:
            pos = positions[0]
            params = vars(pos) if hasattr(pos, '__dict__') else pos.dict() if hasattr(pos, 'dict') else {}
            if not params:
                params = {k: getattr(pos, k) for k in dir(pos) if not k.startswith('_') and not callable(getattr(pos, k))}
            
            for k, v in params.items():
                print(f"{k}: {type(v).__name__}")
    except Exception as e:
        print(f"Error fetching positions: {e}")

if __name__ == "__main__":
    inspect_data()
