
import os
from dotenv import load_dotenv
from tastytrade import Session, OAuthSession
from tastytrade.metrics import get_market_metrics
from tastytrade.instruments import NestedOptionChain

load_dotenv()

def test_metrics():
    client_secret = os.getenv("TASTYTRADE_CLIENT_SECRET")
    refresh_token = os.getenv("TASTYTRADE_REFRESH_TOKEN")
    is_test = os.getenv("TASTYTRADE_IS_TEST", "False").lower() == "true"
    
    session = OAuthSession(client_secret, refresh_token, is_test=is_test)
    
    symbol = "SPY"
    chains = NestedOptionChain.get(session, symbol)
    chain = chains[0]
    exp = chain.expirations[0]
    opt_symbol = exp.strikes[0].call.strip()
    
    print(f"Fetching metrics for {opt_symbol}...")
    try:
        metrics = get_market_metrics(session, [opt_symbol])
        print(f"Metrics: {metrics}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_metrics()
