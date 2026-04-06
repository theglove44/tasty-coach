<!-- Source: https://developer.tastytrade.com/api-guides/market-data/ -->

# Market Data


tastytrade offers REST endpoints for fetching market data. These endpoints are available to funded account holders. We do not provide REST endpoints for delayed quotes.


For streaming market data asynchronously in real-time, head to our [Streaming Market Data](/streaming-market-data/) section.


### Fetch Quote By Type


This endpoint allows you to fetch a quote for several securities at once. You need to pass in the type and a comma-delimited list of symbols in the query string of the request. The security type is the query string parameter key and the value is the comma-delimited list of symbols.


Query ParameterscryptocurrencyStringComma-separated list of cryptocurrency symbolsexample: BTC/USDequityStringComma-separated list of equity symbolsexample: AAPLequity-optionStringComma-separated list of equity option symbolsexample: SPY 250428P00355000indexStringComma-separated list of index symbolsexample: SPXfutureStringComma-separated list of future symbolsexample: /CLM5future-optionStringComma-separated list of future option symbolsexample: /MESU5EX3M5 250620C6450
GET/market-data/by-type?equity=AAPL,TSLA&cryptocurrency=BTC/USD

```json
{
"data": {
"items": [
{
"symbol": "BTC/USD",
"instrument-type": "Cryptocurrency",
"updated-at": "2025-04-29T21:33:25.130Z",
"bid": "94005.47",
"bid-size": "0.022",
"ask": "94966.14",
"ask-size": "0.0",
"mid": "94485.805",
"mark": "94485.805",
"last": "94485.81",
"last-mkt": "94485.81",
"open": "94393.9",
"day-high-price": "95421.055",
"day-low-price": "94227.015",
"close-price-type": "Regular",
"prev-close": "94393.845",
"prev-close-price-type": "Regular",
"summary-date": "2025-04-29",
"prev-close-date": "2025-04-28",
"is-trading-halted": false,
"halt-start-time": -1,
"halt-end-time": -1,
"year-low-price": "49149.415",
"year-high-price": "109558.42"
},
{
"symbol": "AAPL",
"instrument-type": "Equity",
"updated-at": "2025-04-29T21:33:25.535Z",
"bid": "210.55",
"bid-size": "2.0",
"ask": "210.6",
"ask-size": "1.0",
"mid": "210.575",
"mark": "210.55",
"last": "210.511",
"last-mkt": "211.21",
"beta": "1.260672228",
"dividend-amount": "0.25",
"dividend-frequency": "4.0",
"open": "208.693",
"day-high-price": "212.24",
"day-low-price": "208.37",
"close": "211.21",
"close-price-type": "Final",
"prev-close": "210.14",
"prev-close-price-type": "Final",
"summary-date": "2025-04-29",
"prev-close-date": "2025-04-28",
"low-limit-price": "189.77",
"high-limit-price": "231.94",
"is-trading-halted": false,
"halt-start-time": -1,
"halt-end-time": -1,
"year-low-price": "169.11",
"year-high-price": "260.1",
"volume": "35348839.0"
},
{
"symbol": "TSLA",
"instrument-type": "Equity",
"updated-at": "2025-04-29T21:33:25.157Z",
"bid": "289.44",
"bid-size": "3.0",
"ask": "289.49",
"ask-size": "2.0",
"mid": "289.465",
"mark": "289.44",
"last": "289.44",
"last-mkt": "292.03",
"beta": "2.203685106",
"open": "285.5",
"day-high-price": "293.32",
"day-low-price": "279.4695",
"close": "292.03",
"close-price-type": "Final",
"prev-close": "285.88",
"prev-close-price-type": "Final",
"summary-date": "2025-04-29",
"prev-close-date": "2025-04-28",
"low-limit-price": "262.13",
"high-limit-price": "320.38",
"is-trading-halted": false,
"halt-start-time": -1,
"halt-end-time": -1,
"year-low-price": "167.41",
"year-high-price": "488.5399",
"volume": "108172092.0"
}
]
},
"pagination": null
}

```