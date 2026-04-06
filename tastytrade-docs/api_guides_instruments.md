<!-- Source: https://developer.tastytrade.com/api-guides/instruments/ -->

# Instruments


The term "Instrument" refers to anything you can trade: Equities, Equity Options, Futures, Future Options, and Cryptocurrencies.


Each instrument has a unique symbol that serves as its primary identifier. In order to place a trade, you need to know an instrument's symbol.


Refer to our [symbology](/#tastytrade-symbology) guide for more information on tastytrade instrument symbol formats.


The sections below describe how to retrieve any instrument from tastytrade's API.


- [Equities](/api-guides/instruments/#equities)


- [List Equities](/api-guides/instruments/#list-equities)

- [List Active Equities](/api-guides/instruments/#list-active-equities)

- [Get Equity](/api-guides/instruments/#get-equity)

- [Equity Options](/api-guides/instruments/#equity-options)


- [List Nested Option Chains](/api-guides/instruments/#list-nested-option-chains)

- [List Detailed Option Chains](/api-guides/instruments/#list-option-chains)

- [List Compact Option Chains](/api-guides/instruments/#list-compact-option-chains)

- [List Equity Options](/api-guides/instruments/#list-equity-options)

- [Get Equity Option](/api-guides/instruments/#get-equity-option)

- [Futures](/api-guides/instruments/#futures)


- [List Futures](/api-guides/instruments/#list-futures)

- [Get Future](/api-guides/instruments/#get-future)

- [List Future Products](/api-guides/instruments/#list-future-products)

- [Get Future Product](/api-guides/instruments/#get-future-product)

- [Future Options](/api-guides/instruments/#future-options)


- [List Nested Futures Option Chains](/api-guides/instruments/#list-nested-futures-option-chains)

- [List Detailed Futures Option Chains](/api-guides/instruments/#list-futures-option-chains)

- [List Future Options](/api-guides/instruments/#list-future-options)

- [Get Future Option](/api-guides/instruments/#get-future-option)

- [List Future Option Products](/api-guides/instruments/#list-future-option-products)

- [Get Future Option Product](/api-guides/instruments/#get-future-option-product)

- [Cryptocurrencies](/api-guides/instruments/#cryptocurrencies)


- [List Cryptocurrencies](/api-guides/instruments/#list-cryptocurrencies)

- [Get Cryptocurrency](/api-guides/instruments/#get-cryptocurrency)

- [Warrants](/api-guides/instruments/#warrants)


- [List Warrants](/api-guides/instruments/#list-warrants)

- [Get Warrant](/api-guides/instruments/#get-warrant)

- [Quantity Decimal Precisions](/api-guides/instruments/#quantity-decimal-precisions)


- [List Quantity Decimal Precisions](/api-guides/instruments/#list-quantity-decimal-precisions)


## Equities


### List Equities


This endpoint allows you to list equities given one or more symbols. You can filter for equities that are categorized as indexes or ETFs. You can also filter by lendability.


Query ParameterssymbolArray[String]One or more equity symbolsexample: symbol[]=SPY&symbol[]=AAPLlendabilityStringLendability of the equitiesValues: Easy To Borrow, Locate Required, Preborrowis-indexBooleanFilter for index equitiesexample: trueis-etfBooleanFilter for ETF equitiesexample: true
GET/instruments/equities

```json
{
"data": {
"items": [
{
"id": 726,
"symbol": "AAPL",
"instrument-type": "Equity",
"cusip": "037833100",
"short-description": "APPLE INC",
"is-index": false,
"listed-market": "XNAS",
"description": "APPLE INC",
"lendability": "Easy To Borrow",
"borrow-rate": "0.0",
"market-time-instrument-collection": "Equity",
"is-closing-only": false,
"is-options-closing-only": false,
"active": true,
"is-fractional-quantity-eligible": true,
"is-illiquid": false,
"is-etf": false,
"streamer-symbol": "AAPL",
"tick-sizes": [
{
"value": "0.0001",
"threshold": "1.0"
},
{
"value": "0.01"
}
],
"option-tick-sizes": [
{
"value": "0.01",
"threshold": "3.0"
},
{
"value": "0.05"
}
]
},
{
"id": 17702,
"symbol": "SPX",
"instrument-type": "Equity",
"cusip": "648815108",
"short-description": "S & P 500 INDEX",
"is-index": true,
"listed-market": "OTC",
"description": "S & P 500 INDEX",
"lendability": "Locate Required",
"borrow-rate": "0.0",
"market-time-instrument-collection": "Equity Index",
"is-closing-only": false,
"is-options-closing-only": false,
"active": false,
"is-fractional-quantity-eligible": false,
"is-illiquid": false,
"is-etf": false,
"streamer-symbol": "SPX",
"option-tick-sizes": [
{
"value": "0.05",
"threshold": "3.0"
},
{
"value": "0.1"
}
]
}
]
},
"context": "/instruments/equities"
}

```


### List Active Equities


Returns a paginated list of active equities. You may optionally filter by lendability.


Query ParameterslendabilityStringLendability of the equitiesValues: Easy To Borrow, Locate Required, Preborrowper-pageIntegerdefault: 1000Number of paginated results to return at a timepage-offsetIntegerdefault: 0Page number to fetch
GET/instruments/equities/active

```json
{
"data": {
"items": [
{
"id": 22975,
"symbol": "XLI",
"instrument-type": "Equity",
"cusip": "81369Y704",
"short-description": "SELECT SECTOR S",
"is-index": false,
"listed-market": "ARCX",
"description": "SELECT SECTOR SPDR TRUST THE INDUSTRIAL SELECT SECTOR SPDR FUND",
"lendability": "Easy To Borrow",
"borrow-rate": "0.0",
"market-time-instrument-collection": "Equity Index",
"is-closing-only": false,
"is-options-closing-only": false,
"active": true,
"is-fractional-quantity-eligible": true,
"is-illiquid": false,
"is-etf": true,
"streamer-symbol": "XLI",
"tick-sizes": [
{
"value": "0.0001",
"threshold": "1.0"
},
{
"value": "0.01"
}
],
"option-tick-sizes": [
{
"value": "0.01",
"threshold": "3.0"
},
{
"value": "0.05"
}
]
}
]
},
"context": "/instruments/equities/active",
"pagination": {
"per-page": 1000,
"page-offset": 0,
"item-offset": 0,
"total-items": 11996,
"total-pages": 12,
"current-item-count": 1000,
"previous-link": null,
"next-link": null,
"paging-link-template": null
}
}

```


### Get Equity


Fetch a single equity object for a given symbol.


Path ParameterssymbolStringrequiredEquity symbolexample: SPY
GET/instruments/equities/{symbol}

```json
{
"data": {
"id": 27854,
"symbol": "SPY",
"instrument-type": "Equity",
"cusip": "78462F103",
"short-description": "SPDR S&P 500 ET",
"is-index": false,
"listed-market": "ARCX",
"description": "SPDR S&P 500 ETF TRUST",
"lendability": "Easy To Borrow",
"borrow-rate": "0.0",
"market-time-instrument-collection": "Equity Index",
"is-closing-only": false,
"is-options-closing-only": false,
"active": true,
"is-fractional-quantity-eligible": true,
"is-illiquid": false,
"is-etf": true,
"streamer-symbol": "SPY",
"tick-sizes": [
{
"value": "0.0001",
"threshold": "1.0"
},
{
"value": "0.01"
}
],
"option-tick-sizes": [
{
"value": "0.01"
}
]
},
"context": "/instruments/equities/SPY"
}

```


## Equity Options


### List Nested Option Chains


This returns a list of option chains with their expirations and strikes grouped together. Each expiration object provides its expiration date and expiration type.


Nested inside each expiration object is also a list of strikes. Each strike has a **call** and **put** value, which are the strike's call symbol and put symbol, respectively.


Path Parametersunderlying_symbolStringrequiredEquity symbol
GET/option-chains/{underlying_symbol}/nested

```json
{
"data": {
"items": [
{
"underlying-symbol": "SPY",
"root-symbol": "SPY",
"option-chain-type": "Standard",
"shares-per-contract": 100,
"expirations": [
{
"expiration-type": "Regular",
"expiration-date": "2022-09-16",
"days-to-expiration": 2,
"settlement-type": "PM",
"strikes": [
{
"strike-price": "370.0",
"call": "SPY 230706C00370000",
"call-streamer-symbol": ".SPY230706C370",
"put": "SPY 230706P00370000",
"put-streamer-symbol": ".SPY230706P370"
}
]
}
]
}
]
},
"context": "/option-chains/SPY/nested"
}

```


### List Detailed Option Chains


This endpoint returns a list of equity option instrument objects for the underlying symbol given in the path.


Each object is a full equity option json representation.


Path Parametersunderlying_symbolStringrequiredEquity symbol
GET/option-chains/{underlying_symbol}

```json
{
"data": {
"items": [
{
"symbol": "AAPL 220916C00040000",
"instrument-type": "Equity Option",
"active": true,
"strike-price": "40.0",
"root-symbol": "AAPL",
"underlying-symbol": "AAPL",
"expiration-date": "2022-09-16",
"exercise-style": "American",
"shares-per-contract": 100,
"option-type": "C",
"option-chain-type": "Standard",
"expiration-type": "Regular",
"settlement-type": "PM",
"stops-trading-at": "2022-09-16T20:00:00.000+00:00",
"market-time-instrument-collection": "Equity Option",
"days-to-expiration": 2,
"expires-at": "2022-09-16T20:00:00.000+00:00",
"is-closing-only": false
}
]
},
"context": "/option-chains/SPY"
}

```


### List Compact Option Chains


This endpoint concatenates all strike symbols across all expirations into a single array.


Path Parametersunderlying_symbolStringrequiredEquity symbol
GET/option-chains/{underlying_symbol}/compact

```json
{
"data": {
"items": [
{
"underlying-symbol": "SPY",
"root-symbol": "SPY",
"option-chain-type": "Standard",
"settlement-type": "PM",
"shares-per-contract": 100,
"expiration-type": "Weekly",
"deliverables": [
{
"id": 114830,
"root-symbol": "SPY",
"deliverable-type": "Shares",
"description": "100 shares of SPY",
"amount": "100.0",
"symbol": "SPY",
"instrument-type": "Equity",
"percent": "100"
}
],
"symbols": [
"SPY 230731C00370000",
"SPY 230731P00370000",
"SPY 230731C00380000",
"SPY 230731P00380000",
"SPY 230731C00383000",
"SPY 230731P00383000",
"SPY 230731C00384000",
"SPY 230731P00384000",
"SPY 230731C00385000",
"SPY 230731P00385000",
"SPY 230731C00386000",
"SPY 230731P00386000",
"SPY 230731C00387000",
"SPY 230731P00387000",
"SPY 230731C00388000",
"SPY 230731P00388000",
"SPY 230731C00389000",
"SPY 230731P00389000",
"SPY 230731C00390000",
"SPY 230731P00390000",
"SPY 230731C00391000",
"SPY 230731P00391000",
"SPY 230731C00392000",
"SPY 230731P00392000",
"SPY 230731C00393000"
]
}
]
},
"context": "/option-chains/SPY/compact"
}

```


### List Equity Options


This endpoint allows you to fetch one or more equity option objects given a set of symbols. The **active** parameter can be used to filter out any non-standard equity options.


Query ParameterssymbolArray[String]One or more equity option symbols using OCC Symbologyexample: symbol[]=SPY 230731C00393000activeBooleanWhether an option is available for trading with the brokerexample: truewith-expiredBooleanInclude expired optionsexample: true
GET/instruments/equity-options

```json
{
"data": {
"items": [
{
"symbol": "SPY 230731C00393000",
"instrument-type": "Equity Option",
"active": true,
"strike-price": "393.0",
"root-symbol": "SPY",
"underlying-symbol": "SPY",
"expiration-date": "2023-07-31",
"exercise-style": "American",
"shares-per-contract": 100,
"option-type": "C",
"option-chain-type": "Standard",
"expiration-type": "Weekly",
"settlement-type": "PM",
"stops-trading-at": "2023-07-31T20:15:00.000+00:00",
"market-time-instrument-collection": "Cash Settled Equity Option",
"days-to-expiration": 1,
"expires-at": "2023-07-31T20:15:00.000+00:00",
"is-closing-only": false,
"streamer-symbol": ".SPY230731C393"
}
]
},
"context": "/instruments/equity-options"
}

```


### Get Equity Option


This endpoint returns a single equity option instrument for a given symbol.


Path ParameterssymbolStringrequiredEquity option symbol in OCC formatexample: SPY 230731C00393000
GET/instruments/equity-options/{symbol}

```json
{
"data": {
"symbol": "SPY 230731C00393000",
"instrument-type": "Equity Option",
"active": true,
"strike-price": "393.0",
"root-symbol": "SPY",
"underlying-symbol": "SPY",
"expiration-date": "2023-07-31",
"exercise-style": "American",
"shares-per-contract": 100,
"option-type": "C",
"option-chain-type": "Standard",
"expiration-type": "Weekly",
"settlement-type": "PM",
"stops-trading-at": "2023-07-31T20:15:00.000+00:00",
"market-time-instrument-collection": "Cash Settled Equity Option",
"days-to-expiration": 1,
"expires-at": "2023-07-31T20:15:00.000+00:00",
"is-closing-only": false,
"streamer-symbol": ".SPY230731C393"
},
"context": "/instruments/equity-options/SPY%20%20%20230731C00393000"
}

```


## Futures


Futures symbols all start with a foward slash (/) character, like `/ESU3`. When including forward slashes in the url's path or query parameters, be sure to encode it properly.


For example, `/ESU3` should be encoded for urls as `%2FESU3`.


The examples below show the raw unencoded symbol including its forward slash.


This endpoint lists all of the active futures contracts that tastytrade currently offers. Each future returned includes its corresponding product info nested in the **future-product** attribute.


You can optionally filter by symbol or product code. You can get a list of product codes from the [List Future Products](/api-guides/instruments/#list-future-products) endpoint.


Query ParameterssymbolArray[String]One or more future contract symbolsexample: symbol[]=/ESU3product-codeArray[String]Product code of the future instrument. This allows you to filter for all active contracts belonging to a specific future product.example: ES
GET/instruments/futures

```json
{
"data": {
"items": [
{
"symbol": "/ESU3",
"product-code": "ES",
"contract-size": "50.0",
"tick-size": "0.25",
"notional-multiplier": "50.0",
"main-fraction": "0.0",
"sub-fraction": "0.0",
"display-factor": "0.01",
"last-trade-date": "2023-09-15",
"expiration-date": "2023-09-15",
"closing-only-date": "2023-09-15",
"active": true,
"active-month": true,
"next-active-month": false,
"is-closing-only": false,
"stops-trading-at": "2023-09-15T13:30:00.000+00:00",
"expires-at": "2023-09-15T13:30:00.000+00:00",
"product-group": "CME_ES",
"exchange": "CME",
"roll-target-symbol": "/ESZ3",
"streamer-exchange-code": "XCME",
"streamer-symbol": "/ESU23:XCME",
"back-month-first-calendar-symbol": true,
"is-tradeable": true,
"future-etf-equivalent": {
"symbol": "SPY",
"share-quantity": 506
},
"future-product": {
"root-symbol": "/ES",
"code": "ES",
"description": "E Mini S&P",
"clearing-code": "ES",
"clearing-exchange-code": "16",
"clearport-code": "ES",
"legacy-code": "ES",
"exchange": "CME",
"legacy-exchange-code": "CME",
"product-type": "Financial",
"listed-months": [
"H",
"M",
"U",
"Z"
],
"active-months": [
"H",
"M",
"U",
"Z"
],
"notional-multiplier": "50.0",
"tick-size": "0.25",
"display-factor": "0.01",
"streamer-exchange-code": "XCME",
"small-notional": false,
"back-month-first-calendar-symbol": true,
"first-notice": false,
"cash-settled": true,
"security-group": "ES",
"market-sector": "Equity Index",
"roll": {
"name": "equity_index",
"active-count": 3,
"cash-settled": true,
"business-days-offset": 4,
"first-notice": false
}
},
"tick-sizes": [
{
"value": "0.25"
}
],
"option-tick-sizes": [
{
"value": "0.05",
"threshold": "5.0"
},
{
"value": "0.25"
}
],
"spread-tick-sizes": [
{
"value": "0.05",
"symbol": "/ESH4"
},
{
"value": "0.05",
"symbol": "/ESZ3"
}
]
}
]
}
}

```


### Get Future


Path ParameterssymbolStringrequiredFuture symbolexample: /ESU3
GET/instruments/futures/{symbol}

```json
{
"data": {
"symbol": "/ESU3",
"product-code": "ES",
"contract-size": "50.0",
"tick-size": "0.25",
"notional-multiplier": "50.0",
"main-fraction": "0.0",
"sub-fraction": "0.0",
"display-factor": "0.01",
"last-trade-date": "2023-09-15",
"expiration-date": "2023-09-15",
"closing-only-date": "2023-09-15",
"active": true,
"active-month": true,
"next-active-month": false,
"is-closing-only": false,
"stops-trading-at": "2023-09-15T13:30:00.000+00:00",
"expires-at": "2023-09-15T13:30:00.000+00:00",
"product-group": "CME_ES",
"exchange": "CME",
"roll-target-symbol": "/ESZ3",
"streamer-exchange-code": "XCME",
"streamer-symbol": "/ESU23:XCME",
"back-month-first-calendar-symbol": true,
"is-tradeable": true,
"future-etf-equivalent": {
"symbol": "SPY",
"share-quantity": 504
},
"future-product": {
"root-symbol": "/ES",
"code": "ES",
"description": "E Mini S&P",
"clearing-code": "ES",
"clearing-exchange-code": "16",
"clearport-code": "ES",
"legacy-code": "ES",
"exchange": "CME",
"legacy-exchange-code": "CME",
"product-type": "Financial",
"listed-months": [
"H",
"M",
"U",
"Z"
],
"active-months": [
"H",
"M",
"U",
"Z"
],
"notional-multiplier": "50.0",
"tick-size": "0.25",
"display-factor": "0.01",
"streamer-exchange-code": "XCME",
"small-notional": false,
"back-month-first-calendar-symbol": true,
"first-notice": false,
"cash-settled": true,
"security-group": "ES",
"market-sector": "Equity Index",
"roll": {
"name": "equity_index",
"active-count": 3,
"cash-settled": true,
"business-days-offset": 4,
"first-notice": false
}
},
"tick-sizes": [
{
"value": "0.25"
}
],
"option-tick-sizes": [
{
"value": "0.05",
"threshold": "5.0"
},
{
"value": "0.25"
}
],
"spread-tick-sizes": [
{
"value": "0.05",
"symbol": "/ESH4"
},
{
"value": "0.05",
"symbol": "/ESZ3"
}
]
},
"context": "/instruments/futures/%2FESU3"
}

```


### List Future Products


This endpoint returns a list of the future products that tastytrade supports.


A future product is not an instrument. It is not tradeable. It simply describes attributes about the product itself like its contract code and the months of the year that contracts are listed.


For example, the E-mini S&P 500 product's code is `ES`. Every future contract for this product will start with `/ES`. This product offers contracts for March (H), June (M), September (U), and December (Z).


Nested inside each future product's json body are the **option-products** that relate to it. If this attribute is missing or empty, it means we don't offer options for that future product.


GET/instruments/future-products

```json
{
"data": {
"items": [
{
"root-symbol": "/ES",
"code": "ES",
"description": "E Mini S&P",
"clearing-code": "ES",
"clearing-exchange-code": "16",
"clearport-code": "ES",
"legacy-code": "ES",
"exchange": "CME",
"legacy-exchange-code": "CME",
"product-type": "Financial",
"listed-months": [
"H",
"M",
"U",
"Z"
],
"active-months": [
"H",
"M",
"U",
"Z"
],
"notional-multiplier": "50.0",
"tick-size": "0.25",
"display-factor": "0.01",
"streamer-exchange-code": "XCME",
"small-notional": false,
"back-month-first-calendar-symbol": true,
"first-notice": false,
"cash-settled": true,
"security-group": "ES",
"market-sector": "Equity Index",
"option-products": [
{
"root-symbol": "E1B",
"cash-settled": false,
"code": "E1B",
"legacy-code": "E1B",
"clearport-code": "E1B",
"clearing-code": "ER",
"clearing-exchange-code": "9C",
"clearing-price-multiplier": "1.0",
"display-factor": "0.01",
"exchange": "CME",
"product-type": "Physical",
"expiration-type": "Weekly",
"settlement-delay-days": 0,
"is-rollover": false,
"market-sector": "Equity Index"
},
{
"root-symbol": "E2B",
"cash-settled": false,
"code": "E2B",
"legacy-code": "E2B",
"clearport-code": "E2B",
"clearing-code": "ES",
"clearing-exchange-code": "9C",
"clearing-price-multiplier": "1.0",
"display-factor": "0.01",
"exchange": "CME",
"product-type": "Physical",
"expiration-type": "Weekly",
"settlement-delay-days": 0,
"is-rollover": false,
"market-sector": "Equity Index"
},
{
"root-symbol": "E3B",
"cash-settled": false,
"code": "E3B",
"legacy-code": "E3B",
"clearport-code": "E3B",
"clearing-code": "EU",
"clearing-exchange-code": "9C",
"clearing-price-multiplier": "1.0",
"display-factor": "0.01",
"exchange": "CME",
"product-type": "Physical",
"expiration-type": "Weekly",
"settlement-delay-days": 0,
"is-rollover": false,
"market-sector": "Equity Index"
},
{
"root-symbol": "E4B",
"cash-settled": false,
"code": "E4B",
"legacy-code": "E4B",
"clearport-code": "E4B",
"clearing-code": "EV",
"clearing-exchange-code": "9C",
"clearing-price-multiplier": "1.0",
"display-factor": "0.01",
"exchange": "CME",
"product-type": "Physical",
"expiration-type": "Weekly",
"settlement-delay-days": 0,
"is-rollover": true,
"market-sector": "Equity Index"
},
{
"root-symbol": "E5B",
"cash-settled": false,
"code": "E5B",
"legacy-code": "E5B",
"clearport-code": "E5B",
"clearing-code": "EW",
"clearing-exchange-code": "9C",
"clearing-price-multiplier": "1.0",
"display-factor": "0.01",
"exchange": "CME",
"product-type": "Physical",
"expiration-type": "Weekly",
"settlement-delay-days": 0,
"is-rollover": true,
"market-sector": "Equity Index"
}
],
"roll": {
"name": "equity_index",
"active-count": 3,
"cash-settled": true,
"business-days-offset": 4,
"first-notice": false
}
},
]
},
"context": "/instruments/future-products"
}

```


### Get Future Product


To get a single future product, include the **exchange** and **product-code** in the url.


Path ParametersexchangeStringrequiredExchange at which the future is tradedValues: CME, SMALLS, CFE, CBOEDcodeStringrequiredFuture product codeexample: CL
GET/instruments/future-products/{exchange}/{code}

```json
{
"data": {
"root-symbol": "/CL",
"code": "CL",
"description": "Light Sweet Crude Oil",
"clearing-code": "CU",
"clearing-exchange-code": "07",
"clearport-code": "CL",
"legacy-code": "CL",
"exchange": "CME",
"legacy-exchange-code": "NYM",
"product-type": "Physical",
"listed-months": [
"F",
"G",
"H",
"J",
"K",
"M",
"N",
"Q",
"U",
"V",
"X",
"Z"
],
"active-months": [
"F",
"G",
"H",
"J",
"K",
"M",
"N",
"Q",
"U",
"V",
"X",
"Z"
],
"notional-multiplier": "1000.0",
"tick-size": "0.01",
"display-factor": "0.01",
"streamer-exchange-code": "XNYM",
"small-notional": false,
"back-month-first-calendar-symbol": false,
"first-notice": false,
"cash-settled": false,
"security-group": "CL",
"market-sector": "Energy",
"option-products": [
{
"root-symbol": "ML1",
"cash-settled": false,
"code": "ML1",
"legacy-code": "ML1",
"clearport-code": "ML1",
"clearing-code": "(N",
"clearing-exchange-code": "07",
"clearing-price-multiplier": "1.0",
"display-factor": "0.01",
"exchange": "CME",
"product-type": "Physical",
"expiration-type": "Weekly",
"settlement-delay-days": 0,
"is-rollover": false,
"market-sector": "Energy"
},
{
"root-symbol": "ML2",
"cash-settled": false,
"code": "ML2",
"legacy-code": "ML2",
"clearport-code": "ML2",
"clearing-code": "(X",
"clearing-exchange-code": "07",
"clearing-price-multiplier": "1.0",
"display-factor": "0.01",
"exchange": "CME",
"product-type": "Physical",
"expiration-type": "Weekly",
"settlement-delay-days": 0,
"is-rollover": false,
"market-sector": "Energy"
},
{
"root-symbol": "ML3",
"cash-settled": false,
"code": "ML3",
"legacy-code": "ML3",
"clearport-code": "ML3",
"clearing-code": "(Y",
"clearing-exchange-code": "07",
"clearing-price-multiplier": "1.0",
"display-factor": "0.01",
"exchange": "CME",
"product-type": "Physical",
"expiration-type": "Weekly",
"settlement-delay-days": 0,
"is-rollover": false,
"market-sector": "Energy"
},
{
"root-symbol": "ML4",
"cash-settled": false,
"code": "ML4",
"legacy-code": "ML4",
"clearport-code": "ML4",
"clearing-code": "(Z",
"clearing-exchange-code": "07",
"clearing-price-multiplier": "1.0",
"display-factor": "0.01",
"exchange": "CME",
"product-type": "Physical",
"expiration-type": "Weekly",
"settlement-delay-days": 0,
"is-rollover": false,
"market-sector": "Energy"
},
{
"root-symbol": "ML5",
"cash-settled": false,
"code": "ML5",
"legacy-code": "ML5",
"clearport-code": "ML5",
"clearing-code": "(4",
"clearing-exchange-code": "07",
"clearing-price-multiplier": "1.0",
"display-factor": "0.01",
"exchange": "CME",
"product-type": "Physical",
"expiration-type": "Weekly",
"settlement-delay-days": 0,
"is-rollover": false,
"market-sector": "Energy"
}
],
"roll": {
"name": "energies",
"active-count": 7,
"cash-settled": false,
"business-days-offset": 5,
"first-notice": false
}
},
"context": "/instruments/future-products/CME/CL"
}

```


## Future Options


Future option symbols start with a dot and a forward slash (./). Like future instruments, you will need to encode any future option symbols before including them in the url.


For example, `./ESU3 E1DQ3 230803P3860` is UTF-8 encoded into `.%2FESU3%20E1DQ3%20230803P3860`.


The examples below display symbols in their raw unencoded format.


### List Nested Futures Option Chains


This returns a list of futures option chains for a given future product. The data is grouped into expirations and strikes. Each expiration object provides its expiration date and expiration type.


Nested inside each expiration object is also a list of strikes. Each strike has a **call** and **put** value, which are the strike's call symbol and put symbol, respectively.


The easiest way to obtain a future product code is from the [List Future Products](/api-guides/instruments/#list-future-products) endpoint. The `product-code` property can then be used to fetch all of a future product's options.


Path Parametersproduct_codeStringrequiredFuture product contract codeexample: ES
GET/futures-option-chains/{product_code}/nested

```json
{
"data": {
"futures": [
{
"symbol": "/ESU3",
"root-symbol": "/ES",
"expiration-date": "2023-09-15",
"days-to-expiration": 71,
"active-month": true,
"next-active-month": false,
"stops-trading-at": "2023-09-15T13:30:00.000+00:00",
"expires-at": "2023-09-15T13:30:00.000+00:00"
}
],
"option-chains": [
{
"underlying-symbol": "/ES",
"root-symbol": "/ES",
"exercise-style": "American",
"expirations": [
{
"underlying-symbol": "/ESU3",
"root-symbol": "/ES",
"option-root-symbol": "E3A",
"option-contract-symbol": "E3AN3",
"asset": "E3A",
"expiration-date": "2023-07-17",
"days-to-expiration": 11,
"expiration-type": "Weekly",
"settlement-type": "PM",
"notional-value": "0.5",
"display-factor": "0.01",
"strike-factor": "1.0",
"stops-trading-at": "2023-07-17T20:00:00.000+00:00",
"expires-at": "2023-07-17T20:00:00.000+00:00",
"tick-sizes": [
{
"value": "0.05",
"threshold": "5.0"
},
{
"value": "0.25"
}
],
"strikes": [
{
"strike-price": "5600.0",
"call": "./ESU3 E3AN3 230717C5600",
"call-streamer-symbol": "./E3AN23C5600:XCME",
"put": "./ESU3 E3AN3 230717P5600",
"put-streamer-symbol": "./E3AN23P5600:XCME"
},
{
"strike-price": "4825.0",
"call": "./ESU3 E3AN3 230717C4825",
"call-streamer-symbol": "./E3AN23C4825:XCME",
"put": "./ESU3 E3AN3 230717P4825",
"put-streamer-symbol": "./E3AN23P4825:XCME"
}
]
},
]
}
]
},
"context": "/futures-option-chains/ES/nested"
}

```


### List Detailed Futures Option Chains


This endpoint returns a list of future option instrument objects for the future product code given in the path.


Each object is a full future option json representation.


Path Parametersproduct_codeStringrequiredFuture product contract symbol
GET/futures-option-chains/{product_code}

```json
{
"data": {
"items": [
{
"symbol": "./ESU3 E1DQ3 230803P3860",
"underlying-symbol": "/ESU3",
"product-code": "ES",
"expiration-date": "2023-08-03",
"root-symbol": "/ES",
"option-root-symbol": "E1D",
"strike-price": "3860.0",
"exchange": "CME",
"exchange-symbol": "E1DQ3 P3860",
"streamer-symbol": "./E1DQ23P3860:XCME",
"option-type": "P",
"exercise-style": "American",
"is-vanilla": true,
"is-primary-deliverable": true,
"future-price-ratio": "1.0",
"multiplier": "1.0",
"underlying-count": "1.0",
"is-confirmed": true,
"notional-value": "0.5",
"display-factor": "0.01",
"security-exchange": "2",
"sx-id": "0",
"settlement-type": "Future",
"strike-factor": "1.0",
"maturity-date": "2023-08-03",
"is-exercisable-weekly": true,
"last-trade-time": "0",
"days-to-expiration": 4,
"is-closing-only": false,
"active": true,
"stops-trading-at": "2023-08-03T20:00:00.000+00:00",
"expires-at": "2023-08-03T20:00:00.000+00:00",
"future-option-product": {
"root-symbol": "E1D",
"cash-settled": false,
"code": "E1D",
"legacy-code": "E1D",
"clearport-code": "E1D",
"clearing-code": "EX",
"clearing-exchange-code": "9C",
"clearing-price-multiplier": "1.0",
"display-factor": "0.01",
"exchange": "CME",
"product-type": "Physical",
"expiration-type": "Weekly",
"settlement-delay-days": 0,
"is-rollover": false,
"market-sector": "Equity Index"
}
}
]
},
"context": "/futures-option-chains/ES"
}

```


### List Future Options


This endpoint returns a list of future option objects given an array of one or more symbols.


You may optionally filter by **option-root-symbol**, **expiration-date**, **option-type**, and **strike-price**. These attributes must be included together or not at all. A request to filter by **expiration-date** only will be rejected with an HTTP 400.


**symbol** and **option-root-symbol** are mutually exclusive, meaning you may only include one or the other.


Option root symbol is the future option product identifier found in the **root-symbol** field of the [List Future Option Products](/api-guides/instruments/#list-future-option-products) endpoint.


Query ParameterssymbolArray[String]One or more future option symbolsexample: symbol[]=./ESU3 E1DQ3 230803P3860option-root-symbolStringFuture option product contract symbolexpiration-dateDateFilter by expiration dateexample: 2023-08-18option-typeStringCall or PutValues: C, Pstrike-priceDecimalOption strike priceexample: 97.50
GET/instruments/future-options

```json
{
"data": {
"items": [
{
"symbol": "./ESZ9 EW4U9 190927P2975",
"underlying-symbol": "/ESZ9",
"product-code": "ES",
"expiration-date": "2019-09-27",
"root-symbol": "/ES",
"option-root-symbol": "EW4",
"strike-price": "2975.0",
"exchange": "CME",
"exchange-symbol": "EW4U9 P2975",
"option-type": "P",
"exercise-style": "American",
"is-vanilla": true,
"is-primary-deliverable": true,
"future-price-ratio": "1.0",
"multiplier": "1.0",
"underlying-count": "1.0",
"is-confirmed": true,
"notional-value": "0.5",
"display-factor": "0.01",
"security-exchange": "2",
"sx-id": "0",
"settlement-type": "Future",
"strike-factor": "1.0",
"maturity-date": "2019-09-27",
"is-exercisable-weekly": true,
"last-trade-time": "0",
"days-to-expiration": -1,
"is-closing-only": false,
"active": false,
"stops-trading-at": "2019-09-27T20:00:00.000+00:00",
"expires-at": "2019-09-27T20:00:00.000+00:00",
"future-option-product": {
"root-symbol": "EW4",
"cash-settled": false,
"code": "EW4",
"legacy-code": "EW4",
"clearport-code": "EW4",
"clearing-code": "W4",
"clearing-exchange-code": "9C",
"clearing-price-multiplier": "1.0",
"display-factor": "0.01",
"exchange": "CME",
"product-type": "Physical",
"expiration-type": "Weekly",
"settlement-delay-days": 0,
"is-rollover": true,
"market-sector": "Equity Index"
}
}
]
},
"context": "/instruments/future-options"
}

```


### Get Future Option


Returns a future option for a given symbol.


Path ParameterssymbolStringrequiredFuture option symbolexample: ./ESZ9 EW4U9 190927P2975
GET/instruments/future-options/{symbol}

```json
{
"data": {
"symbol": "./ESZ9 EW4U9 190927P2975",
"underlying-symbol": "/ESZ9",
"product-code": "ES",
"expiration-date": "2019-09-27",
"root-symbol": "/ES",
"option-root-symbol": "EW4",
"strike-price": "2975.0",
"exchange": "CME",
"exchange-symbol": "EW4U9 P2975",
"option-type": "P",
"exercise-style": "American",
"is-vanilla": true,
"is-primary-deliverable": true,
"future-price-ratio": "1.0",
"multiplier": "1.0",
"underlying-count": "1.0",
"is-confirmed": true,
"notional-value": "0.5",
"display-factor": "0.01",
"security-exchange": "2",
"sx-id": "0",
"settlement-type": "Future",
"strike-factor": "1.0",
"maturity-date": "2019-09-27",
"is-exercisable-weekly": true,
"last-trade-time": "0",
"days-to-expiration": -1,
"is-closing-only": false,
"active": false,
"stops-trading-at": "2019-09-27T20:00:00.000+00:00",
"expires-at": "2019-09-27T20:00:00.000+00:00",
"future-option-product": {
"root-symbol": "EW4",
"cash-settled": false,
"code": "EW4",
"legacy-code": "EW4",
"clearport-code": "EW4",
"clearing-code": "W4",
"clearing-exchange-code": "9C",
"clearing-price-multiplier": "1.0",
"display-factor": "0.01",
"exchange": "CME",
"product-type": "Physical",
"expiration-type": "Weekly",
"settlement-delay-days": 0,
"is-rollover": true,
"market-sector": "Equity Index"
}
},
"context": "/instruments/future-options/./ESZ9%20EW4U9%20190927P2975"
}

```


### List Future Option Products


This endpoint returns a list of the future option products that tastytrade supports.


A future option product is not an instrument. It is not tradeable. It simply describes attributes about the option product itself like its option contract symbol (root-symbol) and the expiration type.


For example, the E-mini S&P 500 outright future product's code is `ES`. You can trade many different future option products related to this outright future, each of which has its own root symbol (contract code). If you only wanted to trade /ES future options that expire on the first friday of the month, you would use the `EW1` product.


Nested inside each future option product's json body is the **future-product** that it is associated to. If this attribute will always be present since you can't have a future option product without a parent future product.


GET/instruments/future-option-products

```json
{
"data": {
"items": [
{
"root-symbol": "EW1",
"cash-settled": false,
"code": "EW1",
"legacy-code": "EW1",
"clearport-code": "EW1",
"clearing-code": "W1",
"clearing-exchange-code": "9C",
"clearing-price-multiplier": "1.0",
"display-factor": "0.01",
"exchange": "CME",
"product-type": "Physical",
"expiration-type": "Weekly",
"settlement-delay-days": 0,
"is-rollover": false,
"market-sector": "Equity Index",
"future-product": {
"root-symbol": "/ES",
"code": "ES",
"description": "E Mini S&P",
"clearing-code": "ES",
"clearing-exchange-code": "16",
"clearport-code": "ES",
"legacy-code": "ES",
"exchange": "CME",
"legacy-exchange-code": "CME",
"product-type": "Financial",
"listed-months": [
"H",
"M",
"U",
"Z"
],
"active-months": [
"H",
"M",
"U",
"Z"
],
"notional-multiplier": "50.0",
"tick-size": "0.25",
"display-factor": "0.01",
"streamer-exchange-code": "XCME",
"small-notional": false,
"back-month-first-calendar-symbol": true,
"first-notice": false,
"cash-settled": true,
"security-group": "ES",
"market-sector": "Equity Index",
"roll": {
"name": "equity_index",
"active-count": 3,
"cash-settled": true,
"business-days-offset": 4,
"first-notice": false
}
}
},
{
"root-symbol": "EW2",
"cash-settled": false,
"code": "EW2",
"legacy-code": "EW2",
"clearport-code": "EW2",
"clearing-code": "W2",
"clearing-exchange-code": "9C",
"clearing-price-multiplier": "1.0",
"display-factor": "0.01",
"exchange": "CME",
"product-type": "Physical",
"expiration-type": "Weekly",
"settlement-delay-days": 0,
"is-rollover": false,
"market-sector": "Equity Index",
"future-product": {
"root-symbol": "/ES",
"code": "ES",
"description": "E Mini S&P",
"clearing-code": "ES",
"clearing-exchange-code": "16",
"clearport-code": "ES",
"legacy-code": "ES",
"exchange": "CME",
"legacy-exchange-code": "CME",
"product-type": "Financial",
"listed-months": [
"H",
"M",
"U",
"Z"
],
"active-months": [
"H",
"M",
"U",
"Z"
],
"notional-multiplier": "50.0",
"tick-size": "0.25",
"display-factor": "0.01",
"streamer-exchange-code": "XCME",
"small-notional": false,
"back-month-first-calendar-symbol": true,
"first-notice": false,
"cash-settled": true,
"security-group": "ES",
"market-sector": "Equity Index",
"roll": {
"name": "equity_index",
"active-count": 3,
"cash-settled": true,
"business-days-offset": 4,
"first-notice": false
}
}
},
{
"root-symbol": "EW3",
"cash-settled": false,
"code": "EW3",
"legacy-code": "EW3",
"clearport-code": "EW3",
"clearing-code": "W3",
"clearing-exchange-code": "9C",
"clearing-price-multiplier": "1.0",
"display-factor": "0.01",
"exchange": "CME",
"product-type": "Physical",
"expiration-type": "Weekly",
"settlement-delay-days": 0,
"is-rollover": false,
"market-sector": "Equity Index",
"future-product": {
"root-symbol": "/ES",
"code": "ES",
"description": "E Mini S&P",
"clearing-code": "ES",
"clearing-exchange-code": "16",
"clearport-code": "ES",
"legacy-code": "ES",
"exchange": "CME",
"legacy-exchange-code": "CME",
"product-type": "Financial",
"listed-months": [
"H",
"M",
"U",
"Z"
],
"active-months": [
"H",
"M",
"U",
"Z"
],
"notional-multiplier": "50.0",
"tick-size": "0.25",
"display-factor": "0.01",
"streamer-exchange-code": "XCME",
"small-notional": false,
"back-month-first-calendar-symbol": true,
"first-notice": false,
"cash-settled": true,
"security-group": "ES",
"market-sector": "Equity Index",
"roll": {
"name": "equity_index",
"active-count": 3,
"cash-settled": true,
"business-days-offset": 4,
"first-notice": false
}
}
},
{
"root-symbol": "EW4",
"cash-settled": false,
"code": "EW4",
"legacy-code": "EW4",
"clearport-code": "EW4",
"clearing-code": "W4",
"clearing-exchange-code": "9C",
"clearing-price-multiplier": "1.0",
"display-factor": "0.01",
"exchange": "CME",
"product-type": "Physical",
"expiration-type": "Weekly",
"settlement-delay-days": 0,
"is-rollover": true,
"market-sector": "Equity Index",
"future-product": {
"root-symbol": "/ES",
"code": "ES",
"description": "E Mini S&P",
"clearing-code": "ES",
"clearing-exchange-code": "16",
"clearport-code": "ES",
"legacy-code": "ES",
"exchange": "CME",
"legacy-exchange-code": "CME",
"product-type": "Financial",
"listed-months": [
"H",
"M",
"U",
"Z"
],
"active-months": [
"H",
"M",
"U",
"Z"
],
"notional-multiplier": "50.0",
"tick-size": "0.25",
"display-factor": "0.01",
"streamer-exchange-code": "XCME",
"small-notional": false,
"back-month-first-calendar-symbol": true,
"first-notice": false,
"cash-settled": true,
"security-group": "ES",
"market-sector": "Equity Index",
"roll": {
"name": "equity_index",
"active-count": 3,
"cash-settled": true,
"business-days-offset": 4,
"first-notice": false
}
}
}
]
},
"context": "/instruments/future-option-products"
}

```


### Get Future Option Product


Fetch a future option product by a given exchange and root symbol.


Path ParametersexchangeStringrequiredExchange at which the future option product is tradedValues: CME, SMALLS, CFE, CBOEDroot_symbolStringrequiredFuture option root symbol, sometimes referred to as the contract symbolexample: EW1
GET/instruments/future-option-products/{exchange}/{root_symbol}

```json
{
"data": {
"root-symbol": "EW1",
"cash-settled": false,
"code": "EW1",
"legacy-code": "EW1",
"clearport-code": "EW1",
"clearing-code": "W1",
"clearing-exchange-code": "9C",
"clearing-price-multiplier": "1.0",
"display-factor": "0.01",
"exchange": "CME",
"product-type": "Physical",
"expiration-type": "Weekly",
"settlement-delay-days": 0,
"is-rollover": false,
"market-sector": "Equity Index",
"future-product": {
"root-symbol": "/ES",
"code": "ES",
"description": "E Mini S&P",
"clearing-code": "ES",
"clearing-exchange-code": "16",
"clearport-code": "ES",
"legacy-code": "ES",
"exchange": "CME",
"legacy-exchange-code": "CME",
"product-type": "Financial",
"listed-months": [
"H",
"M",
"U",
"Z"
],
"active-months": [
"H",
"M",
"U",
"Z"
],
"notional-multiplier": "50.0",
"tick-size": "0.25",
"display-factor": "0.01",
"streamer-exchange-code": "XCME",
"small-notional": false,
"back-month-first-calendar-symbol": true,
"first-notice": false,
"cash-settled": true,
"security-group": "ES",
"market-sector": "Equity Index",
"roll": {
"name": "equity_index",
"active-count": 3,
"cash-settled": true,
"business-days-offset": 4,
"first-notice": false
}
}
},
"context": "/instruments/future-option-products/CME/EW1"
}

```


## Cryptocurrencies


Cryptocurrency symbols have a forward slash in them (/) that you will have to encode before including them in any urls.


For example, the symbol `BTC/USD` should be UTF-8 encoded into `BTC%2FUSD`.


### List Cryptocurrencies


Returns a list of active cryptocurrency instruments.


GET/instruments/cryptocurrencies

```json
{
"data": {
"items": [
{
"id": 1,
"symbol": "BTC/USD",
"instrument-type": "Cryptocurrency",
"short-description": "Bitcoin",
"description": "Bitcoin to USD",
"is-closing-only": false,
"active": true,
"tick-size": "0.01",
"streamer-symbol": "BTC/USD:CXTALP",
"destination-venue-symbols": [
{
"id": 1,
"symbol": "BTC",
"destination-venue": "CITADEL_CRYPTOCURRENCY",
"max-quantity-precision": 8,
"max-price-precision": 8,
"routable": true
}
]
},
{
"id": 2,
"symbol": "BCH/USD",
"instrument-type": "Cryptocurrency",
"short-description": "Bitcoin Cash",
"description": "Bitcoin Cash to USD",
"is-closing-only": false,
"active": true,
"tick-size": "0.01",
"streamer-symbol": "BCH/USD:CXTALP",
"destination-venue-symbols": [
{
"id": 2,
"symbol": "BCH",
"destination-venue": "CITADEL_CRYPTOCURRENCY",
"max-quantity-precision": 8,
"max-price-precision": 8,
"routable": true
}
]
}
]
},
"context": "/instruments/cryptocurrencies"
}

```


### Get Cryptocurrency


Returns a cryptocurrency instrument from a given symbol.


Path ParameterssymbolStringrequiredCryptocurrency symbolexample: BTC/USD
GET/instruments/cryptocurrencies/{symbol}

```json
{
"data": {
"id": 1,
"symbol": "BTC/USD",
"instrument-type": "Cryptocurrency",
"short-description": "Bitcoin",
"description": "Bitcoin to USD",
"is-closing-only": false,
"active": true,
"tick-size": "0.01",
"streamer-symbol": "BTC/USD:CXTALP",
"destination-venue-symbols": [
{
"id": 1,
"symbol": "BTC",
"destination-venue": "CITADEL_CRYPTOCURRENCY",
"max-quantity-precision": 8,
"max-price-precision": 8,
"routable": true
}
]
},
"context": "/instruments/cryptocurrencies/BTC%2FUSD"
}

```


## Warrants


### List Warrants


Returns a list of active warrant objects.


You may optionally filter by one or more symbols.


Query ParameterssymbolArray[String]One or more warran symbolsexample: symbol[]=ATMCW&symbol[]=HSPOW
GET/instruments/warrants

```json
{
"data": {
"items": [
{
"symbol": "ATMCW",
"instrument-type": "Warrant",
"listed-market": "XNAS",
"description": "AlphaTime Acquisition Corp - Warrant",
"is-closing-only": false,
"active": true
},
{
"symbol": "HSPOW",
"instrument-type": "Warrant",
"listed-market": "XNAS",
"description": "Horizon Space Acquisition I Corp. - Warrant",
"is-closing-only": false,
"active": true
}
]
},
"context": "/instruments/warrants"
}

```


### Get Warrant


Returns a single warrant instrument for a given symbol.


Path ParameterssymbolStringrequiredWarrant symbolexample: SEPAW
GET/instruments/warrants/{symbol}

```json
{
"data": {
"symbol": "SEPAW",
"instrument-type": "Warrant",
"listed-market": "XNAS",
"description": "SEP Acquisition Corp - Warrants",
"is-closing-only": false,
"active": false
},
"context": "/instruments/warrants/SEPAW"
}

```


## Quantity Decimal Precisions


A quantity decimal precision object defines the level of precision to use for a particular instrument's quantity. This concept mostly applies to cryptocurrency instruments since they are most often traded in fractional quantities. However, there are some equity instruments that can be traded in fractional quantities via [Notional Market](/order-submission/#order-type-notional-market) orders.


For example, the cryptocurrency instrument BTC/USD has a quantity decimal precision value of 8, meaning you are allowed to trade in quantities out to the 8th decimal place. A buy order for 0.12345678 BTC/USD is acceptable, but 0.123456789 exceeds the 8 decimal place precision limit. You can of course trade in lower precision quantities, like 0.123 or 0.5.


A quantity decimal precision value of 0 means the instrument or symbol must be traded in whole number quantity (integer).


GET/instruments/quantity-decimal-precisions

```json
{
"data": {
"items": [
{
"instrument-type": "Cryptocurrency",
"symbol": "BTC/USD",
"value": 8,
"minimum-increment-precision": 8
},
{
"instrument-type": "Equity",
"value": 5,
"minimum-increment-precision": 0
}
]
},
"context": "/instruments/quantity-decimal-precisions"
}

```