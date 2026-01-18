
import inspect
from tastytrade import Account
from tastytrade.dxfeed import Greeks
from tastytrade import metrics

print("=== Account.get_balances return type info ===")
# Accessing the return type hint if available, or just printing the class doc
try:
    print(inspect.getsource(Account.get_balances))
except Exception as e:
    print(f"Could not get source: {e}")

print("\n=== Account.get_positions return type info ===")
try:
    print(inspect.getsource(Account.get_positions))
except Exception as e:
    print(f"Could not get source: {e}")

print("\n=== DXFeed Greeks info ===")
print(inspect.getdoc(Greeks))
print(Greeks.__annotations__)

print("\n=== Metrics info ===")
print(dir(metrics))
