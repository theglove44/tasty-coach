<!-- Source: https://developer.tastytrade.com/release-notes/ -->

# Release Notes


Release notes regarding new api versions. See the [Api Versions](/api-overview/#api-versions) section for info on targeting new api versions.


##20260211
Legacy /sessions authentication has been fully decommissioned. If you are still using POST /sessions for your API application you likely are experiencing login issues. Please switch over to OAuth2 immediately to continue using your API application without issue.
OAuth2 documentation is found at [OAuth2](https://developer.tastytrade.com/oauth/)


## 20240501


### GET /accounts/:account_number/balances


Converted the response structure from a single `data` key to an `items` list.


Old Response

```json
{
"data": {
"account-number": "12345",
...
}
}

```


New Response

```json
{
"data": {
"items": [
{
"account-number": "12345"
...
}
]
}
}

```


## 20250715


Response data is now paginated for the following endpoints:


- GET /instruments/equities

- GET /instruments/equity-deliverables

- GET /instruments/equity-options

- GET /instruments/future-option-products

- GET /instruments/future-options

- GET /instruments/future-products

- GET /instruments/future-spreads

- GET /instruments/futures


You can find more info on all these endpoints in the [Instruments page](/open-api-spec/instruments/).


Paginated Response Structure

```json
{
"data": {
"items": [{...}]
},
"pagination": {
"per-page": 1000,
"page-offset": 0,
"item-offset": 0,
"total-items": 25719,
"total-pages": 26,
"current-item-count": 1000,
}
}

```


## 20250813


Response data is now paginated for the following endpoint:


- GET /accounts/:account_number/orders/live


You can find more info on this endpoint in the [Orders page](/open-api-spec/orders/).


Paginated Response Structure

```json
{
"data": {
"items": [{...}]
},
"pagination": {
"per-page": 1000,
"page-offset": 0,
"item-offset": 0,
"total-items": 25719,
"total-pages": 26,
"current-item-count": 1000,
}
}

```