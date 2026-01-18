
import os
from dotenv import load_dotenv
from tastytrade import Session, OAuthSession
from tastytrade.market_data import get_market_data_by_type
from tastytrade.instruments import NestedOptionChain

load_dotenv()

def test_delta():
    client_secret = os.getenv("TASTYTRADE_CLIENT_SECRET")
    refresh_token = os.getenv("TASTYTRADE_REFRESH_TOKEN")
    is_test = os.getenv("TASTYTRADE_IS_TEST", "False").lower() == "true"
    
    session = OAuthSession(client_secret, refresh_token, is_test=is_test)
    
    symbol = "SPY"
    chains = NestedOptionChain.get(session, symbol)
    if not chains:
        print("No chains found")
        return
        
    chain = chains[0]
    exp = chain.expirations[0]
    strike = exp.strikes[len(exp.strikes)//2] # Middle strike
    opt_symbol = strike.call.strip()
    
    print(f"Fetching market data for {opt_symbol}...")
    data = get_market_data_by_type(session, [opt_symbol])
    if data:
        d = data[0]
        print(f"Mark: {d.mark}")
        # Try to find delta in attributes
        for attr in dir(d):
            if 'delta' in attr.lower():
                print(f"{attr}: {getattr(d, attr)}")
    else:
        print("No market data returned")

if __name__ == "__main__":
    test_delta()
