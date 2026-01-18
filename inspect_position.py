
from tastytrade import Account
from tastytrade.account import CurrentPosition

# Print fields of CurrentPosition
print("=== CurrentPosition fields ===")
try:
    print(CurrentPosition.model_fields.keys())
except:
    print(dir(CurrentPosition))
