
import sys
import os
from tastytrade import Account

def inspect_account_methods():
    print("=== Account Class Methods ===")
    for method in dir(Account):
        if not method.startswith('_'):
            print(method)

if __name__ == "__main__":
    inspect_account_methods()
