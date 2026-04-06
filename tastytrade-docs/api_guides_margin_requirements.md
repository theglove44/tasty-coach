<!-- Source: https://developer.tastytrade.com/api-guides/margin-requirements/ -->

# Margin requirements


- [Get Account Margin Requirements](/api-guides/margin-requirements/#get-account-margin-requirements)

- [Margin Requirements Dry Run](/api-guides/margin-requirements/#margin-requirements-dry-run)


### Get Account Margin Requirements


This endpoint lists out the margin requirements of your account grouped by underlying symbol.


Query Parametersaccount_numberStringrequiredThe account number


GET/margin/accounts/{account_number}/requirements

```json
{
"data": {
"account-number": "5WT00001",
"description": "Total",
"margin-calculation-type": "Reg T",
"option-level": "No Restrictions",
"margin-requirement": "4337.831401355",
"margin-requirement-effect": "Debit",
"maintenance-requirement": "3559.174330645",
"maintenance-requirement-effect": "Debit",
"margin-equity": "500007967.877802711",
"margin-equity-effect": "Credit",
"option-buying-power": "499976836.546401355",
"option-buying-power-effect": "Credit",
"reg-t-margin-requirement": "1557.31414142",
"reg-t-margin-requirement-effect": "Debit",
"reg-t-option-buying-power": "500006410.563661291",
"reg-t-option-buying-power-effect": "Credit",
"maintenance-excess": "499977615.203472065",
"maintenance-excess-effect": "Credit",
"groups": [
{
"description": "AAPL",
"code": "AAPL",
"underlying-symbol": "AAPL",
"underlying-type": "Equity",
"margin-calculation-type": "Reg T",
"margin-requirement": "4012.831401355",
"margin-requirement-effect": "Debit",
"maintenance-requirement": "3396.674330645",
"maintenance-requirement-effect": "Debit",
"buying-power": "4012.831401355",
"buying-power-effect": "Credit",
"groups": [
{
"description": "LONG_UNDERLYING",
"margin-requirement": "1232.31414142",
"margin-requirement-effect": "Debit",
"maintenance-requirement": "616.15707071",
"maintenance-requirement-effect": "Debit",
"includes-working-order": false,
"buying-power": "1232.31414142",
"buying-power-effect": "Credit",
"position-entries": [
{
"instrument-symbol": "AAPL",
"instrument-type": "Equity",
"quantity": "355.0",
"close-price": "0.0",
"fixing-price": "NaN"
}
]
}
],
"price-increase-percent": "0.5",
"price-decrease-percent": "-0.5"
},
{
"description": "UA",
"code": "UA",
"underlying-symbol": "UA",
"underlying-type": "Equity",
"margin-calculation-type": "Reg T",
"margin-requirement": "325.0",
"margin-requirement-effect": "Debit",
"maintenance-requirement": "162.5",
"maintenance-requirement-effect": "Debit",
"buying-power": "325.0",
"buying-power-effect": "Credit",
"groups": [
{
"description": "LONG_UNDERLYING",
"margin-requirement": "325.0",
"margin-requirement-effect": "Debit",
"maintenance-requirement": "162.5",
"maintenance-requirement-effect": "Debit",
"includes-working-order": true,
"buying-power": "325.0",
"buying-power-effect": "Credit",
"position-entries": [
{
"instrument-symbol": "UA",
"instrument-type": "Equity",
"quantity": "100.0",
"close-price": "0.0",
"fixing-price": "0.0"
}
]
}
],
"price-increase-percent": "0.5",
"price-decrease-percent": "-0.5"
}
],
"last-state-timestamp": 1690830411014
}
}

```


### Margin Requirements Dry Run


This endpoint allows you to test an order to see a detailed overview of the impact it will make on your account in terms of margin.


The order JSON should look identical to the JSON you send to the [Submit Order](/order-management/#submit-order) endpoint, with 3 additional attributes:


Body Parameters (in addition to normal order parameters)account-numberStringrequiredThe account numberunderlying-symbolStringrequiredThis is the stock symbol (for Equity and Equity Option orders), Future symbol (for Future and Future Option orders), or the crypto symbolunderlying-instrument-typeStringrequiredThe instrument type of the underlying symbolValues: Equity, Equity Option, Future, Future Option, Cryptocurrency


Query Parametersaccount_numberStringrequiredThe account number


Example Dry Run Json

```json
{
"account-number": "5WT00001",
"time-in-force": "Day",
"order-type": "Limit",
"price": "186.99",
"price-effect": "Debit",
"underlying-symbol": "AAPL",
"underlying-instrument-type": "Equity",
"legs": [
{
"instrument-type": "Equity",
"symbol": "AAPL",
"quantity": 1,
"action": "Buy to Open"
}]
}

```


POST/margin/accounts/{account_number}/dry-run

```json
{
"data": {
"orders": [
{
"id": "dry-run-0",
"account-number": "5WT00001",
"time-in-force": "Day",
"order-type": "Limit",
"size": "0",
"price": "186.99",
"price-effect": "Debit",
"value": "0.0",
"value-effect": "None",
"cancellable": false,
"editable": false,
"underlying-symbol": "AAPL",
"legs": [
{
"symbol": "AAPL",
"instrument-type": "Equity",
"quantity": "1",
"remaining-quantity": "0",
"action": "Buy to Open"
}
]
}
],
"last-results": {
"code": "AAPL",
"description": "AAPL",
"entity-count": 14,
"underlying-symbol": "AAPL",
"underlying-type": "Equity",
"underlying-price": "194.54",
"margin-requirement": "4012.831401355",
"margin-requirement-effect": "Debit",
"maintenance-requirement": "3396.674330645",
"maintenance-requirement-effect": "Debit",
"buying-power-impact": "21947.668598645",
"buying-power-impact-effect": "Debit",
"base-margin-requirement": "4012.831401355",
"base-margin-requirement-effect": "Debit",
"margin-calculation-type": "Reg T",
"cash-adjustment": "25960.5",
"cash-adjustment-effect": "Debit",
"working-margin": "2780.517259936",
"working-margin-effect": "Debit",
"position-margin": "1232.31414142",
"position-margin-effect": "Debit",
"position-equity-adjustment": "8025.662802711",
"position-equity-adjustment-effect": "Credit",
"cash-settlement-value": "0.0",
"cash-settlement-value-effect": "None",
"long-equity-value": "2464.628282839",
"long-equity-value-effect": "Credit",
"short-equity-value": "0.0",
"short-equity-value-effect": "None",
"long-derivative-value": "0.0",
"short-derivative-value": "0.0",
"long-cryptocurrency-value": "0.0",
"short-cryptocurrency-value": "0.0",
"group-results": [
{
"group": {
"margin-strategy": "LONG_UNDERLYING",
"underlying-entry": {
"instrument-symbol": "AAPL",
"instrument-type": "Equity",
"quantity": "355.0",
"close-price": "0.0",
"fixing-price": "NaN"
}
},
"margin": "1232.31414142",
"maintenance-requirement": "616.15707071",
"maintenance-requirement-effect": "Debit",
"net-liq-result": {
"long-equity-value": "2464.628282839",
"short-equity-value": "0.0",
"long-derivative-value": "0.0",
"short-derivative-value": "0.0",
"long-cryptocurrency-value": "0.0",
"short-cryptocurrency-value": "0.0"
}
}
],
"order-ids": [
"68783",
"69367",
"69368",
"69637",
"69830",
"70168",
"71326",
"72254",
"72255",
"72259",
"72264",
"89414",
"89421"
],
"calculated-at": "2023-07-26T16:49:14.315-04:00",
"marks": {
"AAPL": "194.51"
}
},
"base-results": {
"code": "AAPL",
"description": "AAPL",
"entity-count": 14,
"underlying-symbol": "AAPL",
"underlying-type": "Equity",
"underlying-price": "196.035",
"margin-requirement": "4012.831401355",
"margin-requirement-effect": "Debit",
"maintenance-requirement": "3396.674330645",
"maintenance-requirement-effect": "Debit",
"buying-power-impact": "22094.668598645",
"buying-power-impact-effect": "Debit",
"base-margin-requirement": "4012.831401355",
"base-margin-requirement-effect": "Debit",
"margin-calculation-type": "Reg T",
"cash-adjustment": "26107.5",
"cash-adjustment-effect": "Debit",
"working-margin": "2780.517259936",
"working-margin-effect": "Debit",
"position-margin": "1232.31414142",
"position-margin-effect": "Debit",
"position-equity-adjustment": "8025.662802711",
"position-equity-adjustment-effect": "Credit",
"cash-settlement-value": "0.0",
"cash-settlement-value-effect": "None",
"long-equity-value": "2464.628282839",
"long-equity-value-effect": "Credit",
"short-equity-value": "0.0",
"short-equity-value-effect": "None",
"long-derivative-value": "0.0",
"short-derivative-value": "0.0",
"long-cryptocurrency-value": "0.0",
"short-cryptocurrency-value": "0.0",
"group-results": [
{
"group": {
"margin-strategy": "LONG_UNDERLYING",
"underlying-entry": {
"instrument-symbol": "AAPL",
"instrument-type": "Equity",
"quantity": "355.0",
"close-price": "0.0",
"fixing-price": "NaN"
}
},
"margin": "1232.31414142",
"maintenance-requirement": "616.15707071",
"maintenance-requirement-effect": "Debit",
"net-liq-result": {
"long-equity-value": "2464.628282839",
"short-equity-value": "0.0",
"long-derivative-value": "0.0",
"short-derivative-value": "0.0",
"long-cryptocurrency-value": "0.0",
"short-cryptocurrency-value": "0.0"
}
}
],
"order-ids": [],
"calculated-at": "2023-07-31T15:07:24.921-04:00",
"marks": {
"AAPL": "196.03"
}
},
"new-order-results": {
"code": "AAPL",
"description": "AAPL",
"entity-count": 14,
"underlying-symbol": "AAPL",
"underlying-type": "Equity",
"underlying-price": "196.035",
"margin-requirement": "4012.831401355",
"margin-requirement-effect": "Debit",
"maintenance-requirement": "3396.674330645",
"maintenance-requirement-effect": "Debit",
"buying-power-impact": "22094.668598645",
"buying-power-impact-effect": "Debit",
"base-margin-requirement": "4012.831401355",
"base-margin-requirement-effect": "Debit",
"margin-calculation-type": "Reg T",
"cash-adjustment": "26107.5",
"cash-adjustment-effect": "Debit",
"working-margin": "2780.517259936",
"working-margin-effect": "Debit",
"position-margin": "1232.31414142",
"position-margin-effect": "Debit",
"position-equity-adjustment": "8025.662802711",
"position-equity-adjustment-effect": "Credit",
"cash-settlement-value": "0.0",
"cash-settlement-value-effect": "None",
"long-equity-value": "2464.628282839",
"long-equity-value-effect": "Credit",
"short-equity-value": "0.0",
"short-equity-value-effect": "None",
"long-derivative-value": "0.0",
"short-derivative-value": "0.0",
"long-cryptocurrency-value": "0.0",
"short-cryptocurrency-value": "0.0",
"group-results": [
{
"group": {
"margin-strategy": "LONG_UNDERLYING",
"underlying-entry": {
"instrument-symbol": "AAPL",
"instrument-type": "Equity",
"quantity": "355.0",
"close-price": "0.0",
"fixing-price": "0.0"
}
},
"margin": "1232.31414142",
"maintenance-requirement": "616.15707071",
"maintenance-requirement-effect": "Debit",
"net-liq-result": {
"long-equity-value": "2464.628282839",
"short-equity-value": "0.0",
"long-derivative-value": "0.0",
"short-derivative-value": "0.0",
"long-cryptocurrency-value": "0.0",
"short-cryptocurrency-value": "0.0"
}
}
],
"order-ids": [],
"calculated-at": "2023-07-31T15:07:24.925-04:00",
"marks": {
"AAPL": "196.03"
}
},
"change-in-margin-requirement": "0.0",
"change-in-margin-requirement-effect": "None",
"change-in-buying-power": "0.0",
"change-in-buying-power-effect": "None",
"current-buying-power": "499976872.546401356",
"current-buying-power-effect": "Credit",
"new-buying-power": "499976872.546401356",
"new-buying-power-effect": "Credit",
"isolated-order-margin-requirement": "0.0",
"isolated-order-margin-requirement-effect": "None",
"isolated-order-buying-power-effect": "0.0",
"isolated-order-buying-power-effect-effect": "None",
"is-spread": false,
"order-ids": [
"dry-run-0"
]
}
}

```