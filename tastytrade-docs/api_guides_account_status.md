<!-- Source: https://developer.tastytrade.com/api-guides/account-status/ -->

# Account Trading Status


Your account trading status affects whether or not you are allowed to place trades. If your account is closed or frozen, you will be blocked from placing trades.


If your account is not in good standing with tastytrade, it may be marked "closing only," meaning you will only be allowed to place trades to close out any positions you hold.


Other attributes on your trading status affect which trading features you have access to. Cryptocurrency, for example, is allowed if **is-cryptocurrency-enabled** is true.


You can also find your account's **day-trade-count** here, which is a live number that gets updated throughout the day.


### Get Trading Status


Path Parametersaccount-numberStringrequiredThe account number
GET/accounts/{account_number}/trading-status

```json
{
"data": {
"account-number": "5WT00001",
"day-trade-count": 0,
"equities-margin-calculation-type": "Reg T",
"fee-schedule-name": "default",
"futures-margin-rate-multiplier": "0.0",
"has-intraday-equities-margin": false,
"id": 15,
"is-aggregated-at-clearing": false,
"is-closed": false,
"is-closing-only": false,
"is-cryptocurrency-closing-only": false,
"is-cryptocurrency-enabled": true,
"is-frozen": false,
"is-full-equity-margin-required": false,
"is-futures-closing-only": false,
"is-futures-intra-day-enabled": false,
"is-futures-enabled": true,
"is-in-day-trade-equity-maintenance-call": false,
"is-in-margin-call": false,
"is-pattern-day-trader": false,
"is-risk-reducing-only": false,
"is-small-notional-futures-intra-day-enabled": false,
"is-roll-the-day-forward-enabled": true,
"are-far-otm-net-options-restricted": true,
"options-level": "No Restrictions",
"short-calls-enabled": true,
"small-notional-futures-margin-rate-multiplier": "0.0",
"is-equity-offering-enabled": false,
"is-equity-offering-closing-only": false,
"enhanced-fraud-safeguards-enabled-at": "2016-12-29T22:51:13.729+00:00",
"updated-at": "2023-06-29T20:51:57.617+00:00"
},
"context": "/accounts/5WT00001/trading-status"
}

```