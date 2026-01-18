
import inspect
from tastytrade import Account
# It seems CurrentPosition is defined inside account.py or imported. 
# The previous output showed: return [CurrentPosition(**i) for i in data["items"]]
# So it must be available in account module or imported.

from tastytrade.account import CurrentPosition, AccountBalance

print("=== CurrentPosition fields ===")
try:
    print(inspect.getsource(CurrentPosition))
except:
    # If it's a Pydantic model
    print(CurrentPosition.model_fields.keys())

print("\n=== AccountBalance fields ===")
try:
    print(inspect.getsource(AccountBalance))
except:
    print(AccountBalance.model_fields.keys())
