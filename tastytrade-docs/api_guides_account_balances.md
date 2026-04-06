<!-- Source: https://developer.tastytrade.com/api-guides/account-balances/ -->

# Account Balances


- [List Account Balances](/api-guides/account-balances/#list-account-balances)

- [List Account Balance Snapshots](/api-guides/account-balances/#list-account-balance-snapshots)


### List Account Balances


Each account has a single account balance object. This object describes the monetary values pertaining to the account, such as **cash-balance**, **cash-available-to-withdraw**, and **net-liquidating-value**.


**net-liquidating-value** is the total current value of the account. It basically shows how much cash you would end up with if you were to close all your positions.


**pending-cash** is cash that is in a holding period temporarily while a cash transfer is processed. You will see a value here when the customer has initiated a cash deposit or withdrawal. For deposits, the **pending-cash-effect** field will be `Credit`, meaning the account is about to be credited.


Fields like **long-equity-value** and **long-derivative-value** describe the value of your positions, where derivative means options. The account in the example below has equity positions valued at $24629.746 and cryptocurrency positions valued at $671.991. If the account were to buy a futures contract, you would see a value in the **long-futures-value** field.


You can see an account's buying power via the **equity-buying-power** and **derivative-buying-power** fields.


Path Parametersaccount_numberStringrequiredAccount number of the account
GET/accounts/{account_number}/balances

```json
{
"data": {
"account-number": "5WT00000",
"cash-balance": "7218.997",
"long-equity-value": "24629.746",
"short-equity-value": "0.0",
"long-derivative-value": "0.0",
"short-derivative-value": "0.0",
"long-futures-value": "0.0",
"short-futures-value": "0.0",
"long-futures-derivative-value": "0.0",
"short-futures-derivative-value": "0.0",
"long-margineable-value": "0.0",
"short-margineable-value": "0.0",
"margin-equity": "32520.734",
"equity-buying-power": "45657.048",
"derivative-buying-power": "22828.524",
"day-trading-buying-power": "0.0",
"futures-margin-requirement": "0.0",
"available-trading-funds": "0.0",
"maintenance-requirement": "9692.211",
"maintenance-call-value": "0.0",
"reg-t-call-value": "0.0",
"day-trading-call-value": "0.0",
"day-equity-call-value": "0.0",
"net-liquidating-value": "32520.734",
"cash-available-to-withdraw": "22828.53",
"day-trade-excess": "22828.53",
"pending-cash": "0.0",
"pending-cash-effect": "None",
"long-cryptocurrency-value": "671.991",
"short-cryptocurrency-value": "0.0",
"cryptocurrency-margin-requirement": "671.99207435",
"unsettled-cryptocurrency-fiat-amount": "0.0",
"unsettled-cryptocurrency-fiat-effect": "None",
"closed-loop-available-balance": "22828.53",
"equity-offering-margin-requirement": "0.0",
"long-bond-value": "0.0",
"bond-margin-requirement": "0.0",
"used-derivative-buying-power": "9692.211",
"snapshot-date": "2023-07-30",
"reg-t-margin-requirement": "9692.21066152",
"futures-overnight-margin-requirement": "0.0",
"futures-intraday-margin-requirement": "0.0",
"maintenance-excess": "22828.52392233",
"pending-margin-interest": "0.0",
"effective-cryptocurrency-buying-power": "22828.524",
"updated-at": "2023-07-30T01:10:30.928+00:00"
},
"context": "/accounts/5WT00000/balances"
}

```


### List Account Balance Snapshots


An account balance snapshot is created twice a day: once in the morning and once after the equities market closes.


This endpoint returns a single balance snapshot object and the most current account balance object.


You can optionally provide a **snapshot-date** parameter to fetch a snapshot for a specific date. You must also provide a **time-of-day** parameter to specify whether you want the snapshot created from the start or end of the day.


If no parameters are given, the most recent balance snapshot is returned.


Path Parametersaccount_numberStringrequiredAccount number of the account
Query Parameterssnapshot-dateDateDate of desired balance snapshotexample: 2023-01-01time-of-dayStringSnapshot time of day. Required if snapshot-date is provided.Values: BOD, EOD

| Time of Day | Meaning |
| --- | --- |
| BOD | Beginning of Day |
| EOD | End of Day |


GET/accounts/{account_number}/balance-snapshots

```json
{
"data": {
"items": [
{
"account-number": "5WT00001",
"cash-balance": "0.0",
"long-equity-value": "0.0",
"short-equity-value": "0.0",
"long-derivative-value": "0.0",
"short-derivative-value": "0.0",
"long-futures-value": "0.0",
"short-futures-value": "0.0",
"long-margineable-value": "0.0",
"short-margineable-value": "0.0",
"margin-equity": "0.0",
"equity-buying-power": "0.0",
"derivative-buying-power": "0.0",
"day-trading-buying-power": "0.0",
"futures-margin-requirement": "0.0",
"available-trading-funds": "0.0",
"maintenance-requirement": "0.0",
"maintenance-call-value": "0.0",
"reg-t-call-value": "0.0",
"day-trading-call-value": "0.0",
"day-equity-call-value": "0.0",
"net-liquidating-value": "0.0",
"day-trade-excess": "0.0",
"pending-cash": "0.0",
"pending-cash-effect": "None",
"snapshot-date": "2016-12-29",
"time-of-day": "EOD"
},
{
"account-number": "5WT00001",
"cash-balance": "7218.997",
"long-equity-value": "24629.746",
"short-equity-value": "0.0",
"long-derivative-value": "0.0",
"short-derivative-value": "0.0",
"long-futures-value": "0.0",
"short-futures-value": "0.0",
"long-futures-derivative-value": "0.0",
"short-futures-derivative-value": "0.0",
"long-margineable-value": "0.0",
"short-margineable-value": "0.0",
"margin-equity": "32520.734",
"equity-buying-power": "45657.048",
"derivative-buying-power": "22828.524",
"day-trading-buying-power": "0.0",
"futures-margin-requirement": "0.0",
"available-trading-funds": "0.0",
"maintenance-requirement": "9692.211",
"maintenance-call-value": "0.0",
"reg-t-call-value": "0.0",
"day-trading-call-value": "0.0",
"day-equity-call-value": "0.0",
"net-liquidating-value": "32520.734",
"cash-available-to-withdraw": "22828.53",
"day-trade-excess": "22828.53",
"pending-cash": "0.0",
"pending-cash-effect": "None",
"long-cryptocurrency-value": "671.991",
"short-cryptocurrency-value": "0.0",
"cryptocurrency-margin-requirement": "671.99207435",
"unsettled-cryptocurrency-fiat-amount": "0.0",
"unsettled-cryptocurrency-fiat-effect": "None",
"closed-loop-available-balance": "22828.53",
"equity-offering-margin-requirement": "0.0",
"long-bond-value": "0.0",
"bond-margin-requirement": "0.0",
"used-derivative-buying-power": "9692.211",
"snapshot-date": "2023-07-30"
}
]
},
"context": "/accounts/5WT00000/balance-snapshots"
}

```