<!-- Source: https://developer.tastytrade.com/api-guides/account-transactions/ -->

# Account Transactions


A transaction is any event that causes a change in an account's balances or positions. Things like orders, cash transfers, position transfers, dividend reinvestments, and credits on interest are all recorded in an accounts transactions ledger.


- [List Transactions](/api-guides/account-transactions/#list-transactions)

- [Get Transaction](/api-guides/account-transactions/#get-transaction)

- [Get Total Fees](/api-guides/account-transactions/#get-total-fees)


### List Transactions


Returns a paginated list of transaction objects.


**types** and **type** are mutually exclusive, meaning you can only include one or the other.


Query ParameterssortStringdefault: DescThe order to sort the results inValues: Asc, DesctypeStringTransaction typeValues: Administrative Transfer, Money Movement, Receive Deliver, Tradesub-typeArray[String]Transaction sub-typeValues: ACAT, Assignment, Balance Adjustment, Cash Merger, Cash Settled Assignment, Cash Settled Exercise, Credit Interest, Debit Interest, Deposit, Dividend, Exercise, Expiration, Fee, Forward Split, Fully Paid Stock Lending Income, Futures Settlement, Mark to Market, Maturity, Reverse Split, Reverse Split Removal, Special Dividend, Stock Merger, Stock Merger Removal, Symbol Change, Transfer, WithdrawaltypesArray[String]Allows filtering on multiple transaction typesValues: Administrative Transfer, Money Movement, Receive Deliver, Tradestart-dateDateQuery transactions starting on a given dateexample: 2023-01-01end-dateDateQuery transactions up to a given dateexample: 2023-01-14instrument-typeStringThe instrument type associated with the transactionValues: Bond, Cryptocurrency, Equity, Equity Offering, Equity Option, Future, Future Option, Index, Unknown, WarrantsymbolStringThe symbol associated with a transactionexample: AAPLunderlying-symbolStringThe underlying symbol associated with a transaction. For future options, search by the underlying contract symbol. For futures, search by the contract codeexample: /ESactionStringThe action associated with a transactionValues: Buy, Buy to Close, Buy to Open, Sell, Sell to Close, Sell to Openpartition-keyStringThe account partition keyfutures-symbolStringThe full futures symbol for any transactions related to futures tradesexample: /ESU9start-atDateTimeQuery transactions starting on a given date at a given timeexample: 2023-01-01T01:00:00end-atDateTimeQuery transactions ending on a given date at a given timeexample: 2023-01-05T01:00:00
Path Parametersaccount-numberStringrequiredThe account number for the associated transactions
GET/accounts/{account_number}/transactions

```json
{
"data": {
"items": [
{
"id": 252640963,
"account-number": "5WT0001",
"symbol": "KBWD",
"instrument-type": "Equity",
"underlying-symbol": "KBWD",
"transaction-type": "Receive Deliver",
"transaction-sub-type": "Dividend",
"description": "Received 1.68074 Long KBWD via Dividend",
"action": "Buy to Open",
"quantity": "1.68074",
"price": "16.46",
"executed-at": "2023-07-28T21:00:00.000+00:00",
"transaction-date": "2023-07-28",
"value": "0.0",
"value-effect": "None",
"net-value": "0.0",
"net-value-effect": "None",
"is-estimated-fee": true
},
{
"id": 252640962,
"account-number": "5WT0001",
"symbol": "PGX",
"instrument-type": "Equity",
"underlying-symbol": "PGX",
"transaction-type": "Receive Deliver",
"transaction-sub-type": "Dividend",
"description": "Received 0.55928 Long PGX via Dividend",
"action": "Buy to Open",
"quantity": "0.55928",
"price": "11.28",
"executed-at": "2023-07-28T21:00:00.000+00:00",
"transaction-date": "2023-07-28",
"value": "0.0",
"value-effect": "None",
"net-value": "0.0",
"net-value-effect": "None",
"is-estimated-fee": true
},
{
"id": 252634233,
"account-number": "5WT0001",
"symbol": "KBWD",
"instrument-type": "Equity",
"underlying-symbol": "KBWD",
"transaction-type": "Money Movement",
"transaction-sub-type": "Dividend",
"description": "INVESCO EXCHANGE TRADED FD TR",
"executed-at": "2023-07-28T21:00:00.000+00:00",
"transaction-date": "2023-07-28",
"value": "27.74",
"value-effect": "Credit",
"net-value": "27.74",
"net-value-effect": "Credit",
"is-estimated-fee": true
}
]
},
"api-version": "v1",
"context": "/accounts/5WT0001/transactions",
"pagination": {
"per-page": 250,
"page-offset": 0,
"item-offset": 0,
"total-items": 1622,
"total-pages": 7,
"current-item-count": 250,
"previous-link": null,
"next-link": null,
"paging-link-template": null
}
}

```


### Get Transaction


Returns a single transaction object.


Path Parametersaccount-numberStringrequiredThe account number for the associated transactionidIntegerrequiredTransaction id
GET/accounts/{account_number}/transactions/{id}

```json
{
"data": {
"id": 250411000,
"account-number": "5WT00001",
"symbol": "DIV",
"instrument-type": "Equity",
"underlying-symbol": "DIV",
"transaction-type": "Receive Deliver",
"transaction-sub-type": "Dividend",
"description": "Received 0.99302 Long DIV via Dividend",
"action": "Buy to Open",
"quantity": "0.99302",
"price": "17.0",
"executed-at": "2023-07-14T21:00:00.000+00:00",
"transaction-date": "2023-07-14",
"value": "0.0",
"value-effect": "None",
"net-value": "0.0",
"net-value-effect": "None",
"is-estimated-fee": true
},
"context": "/accounts/5WT00001/transactions/250411001"
}

```


### Get Total Fees


Returns the total fees for an account for a given day.


Query ParametersdateDatedefault: TodayThe date to get fees forexample: 2023-01-01
Path Parametersaccount-numberStringrequiredThe account number
GET/accounts/{account_number}/transactions/total-fees

```json
{
"data": {
"total-fees": "100.0",
"total-fees-effect": "Debit"
},
"context": "/accounts/5WT00001/transactions/total-fees"
}

```