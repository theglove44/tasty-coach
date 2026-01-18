
import os
from dotenv import load_dotenv
from tastytrade import Session, OAuthSession
from tastytrade.instruments import get_option_chain

load_dotenv()

def test_chain():
    client_secret = os.getenv("TASTYTRADE_CLIENT_SECRET")
    refresh_token = os.getenv("TASTYTRADE_REFRESH_TOKEN")
    is_test = os.getenv("TASTYTRADE_IS_TEST", "False").lower() == "true"
    
    session = OAuthSession(client_secret, refresh_token, is_test=is_test)
    
    symbol = "SPY"
    print(f"Fetching option chain for {symbol}...")
    chain = get_option_chain(session, symbol)
    print(f"Total expirations: {len(chain)}")
    if chain:
        first_exp = list(chain.keys())[0]
        print(f"First expiration: {first_exp}")
        first_strike = chain[first_exp][0]
        print(f"First strike data type: {type(first_strike)}")
        print(f"First strike data: {first_strike}")

if __name__ == "__main__":
    test_chain()
