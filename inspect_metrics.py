
from tastytrade import metrics
from tastytrade.metrics import MarketMetricInfo

print("=== MarketMetricInfo fields ===")
try:
    print(MarketMetricInfo.model_fields.keys())
except:
    print(dir(MarketMetricInfo))
