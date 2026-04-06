<!-- Source: https://developer.tastytrade.com/api-guides/customer-account-info/ -->

# Customer Account Information


- [Get Customer Information](/api-guides/customer-account-info/#get-customer)

- [List Customer Accounts](/api-guides/customer-account-info/#list-customer-accounts)

- [Get An Account](/api-guides/customer-account-info/#get-an-account)


### Get Customer Information


For simplicity as well as security, we don't expose a customer's internal identifier via the API. You can use `me` in place of the `customer_id` path parameter for all customer endpoints.


Path Parameterscustomer_idStringrequiredOnly a value of 'me' is allowed
GET/customers/me

```js
{
"data": {
"id": "me",
"first-name": "John",
"last-name": "Doe",
"address": {
"street-one": "1234 Fake St.",
"city": "Chicago",
"state-region": "IL",
"postal-code": "12345",
"country": "USA",
"is-foreign": false,
"is-domestic": true
},
"mailing-address": {
"street-one": "1234 Fake St.",
"city": "Chicago",
"state-region": "IL",
"postal-code": "12345",
"country": "USA",
"is-foreign": false,
"is-domestic": true
},
"customer-suitability": {
"id": 3,
"marital-status": "MARRIED",
"number-of-dependents": 4,
"employment-status": "EMPLOYED",
"occupation": "Technology",
"employer-name": "tastytrade",
"job-title": "Developer",
"annual-net-income": 1000000,
"net-worth": 10000000,
"liquid-net-worth": 2000000,
"stock-trading-experience": "EXTENSIVE",
"covered-options-trading-experience": "EXTENSIVE",
"uncovered-options-trading-experience": "EXTENSIVE",
"futures-trading-experience": "EXTENSIVE"
},
"usa-citizenship-type": "Citizen",
"is-foreign": false,
"mobile-phone-number": "+11231234567",
"email": "johndoe@nowhere.com",
"tax-number-type": "SSN",
"tax-number": "*****1234",
"birth-date": "2000-01-01",
"external-id": "C0000037211",
"citizenship-country": "USA",
"subject-to-tax-withholding": false,
"agreed-to-margining": true,
"agreed-to-terms": true,
"has-industry-affiliation": false,
"has-political-affiliation": false,
"has-listed-affiliation": false,
"is-professional": false,
"has-delayed-quotes": false,
"has-pending-or-approved-application": true,
"identifiable-type": "Person",
"person": {
"external-id": "P0002173211",
"first-name": "John",
"last-name": "Doe",
"birth-date": "2000-01-01",
"citizenship-country": "USA",
"usa-citizenship-type": "Citizen",
"marital-status": "MARRIED",
"number-of-dependents": 4,
"employment-status": "EMPLOYED",
"occupation": "Technology",
"employer-name": "tastytrade",
"job-title": "Developer"
}
},
"context": "/customers/me"
}

```


### List Customer Accounts


After a successful authentication request, the first thing a client application should do is to retrieve the list of accounts that this customer has access to. This endpoint returns a list of such accounts for the customer (user) linked to the supplied access token.


Every customer has an **authority-level** over their associated accounts. Authority levels are as follows:


| Authority Level | Meaning |
| --- | --- |
| owner | Has full privileges over the account |
| trade-only | Can submit and manage trades, cannot do things like deposit/withdraw cash |
| read-only | Can hit all GET endpoints for an account |


Path Parameterscustomer_idStringrequiredOnly a value of 'me' is allowed
GET/customers/me/accounts

```json
{
"data": {
"items": [
{
"account": {
"account-number": "5WT00001",
"external-id": "A0000196557",
"opened-at": "2019-03-14T15:39:31.265+00:00",
"nickname": "Individual",
"account-type-name": "Individual",
"day-trader-status": false,
"is-closed": false,
"is-firm-error": false,
"is-firm-proprietary": false,
"is-futures-approved": true,
"is-test-drive": false,
"margin-or-cash": "Margin",
"is-foreign": false,
"funding-date": "2017-01-02",
"investment-objective": "SPECULATION",
"futures-account-purpose": "SPECULATING",
"suitable-options-level": "No Restrictions",
"created-at": "2019-03-14T15:39:31.265+00:00"
},
"authority-level": "owner"
},
{
"account": {
"account-number": "5WT00002",
"external-id": "A0000196558",
"opened-at": "2019-03-14T15:39:31.265+00:00",
"nickname": "Individual",
"account-type-name": "Individual",
"day-trader-status": false,
"is-closed": false,
"is-firm-error": false,
"is-firm-proprietary": false,
"is-futures-approved": true,
"is-test-drive": false,
"margin-or-cash": "Margin",
"is-foreign": false,
"funding-date": "2017-01-02",
"investment-objective": "SPECULATION",
"futures-account-purpose": "SPECULATING",
"suitable-options-level": "No Restrictions",
"created-at": "2019-03-14T15:39:31.265+00:00"
},
"authority-level": "owner"
}
]
},
"context": "/customers/me/accounts"
}

```


### Get An Account


You can hit this endpoint to retrieve a single account by including the **account-number** in the url.


Path Parameterscustomer_idStringrequiredOnly a value of 'me' is allowedaccount_numberStringrequiredThe account number of the account
GET/customers/me/accounts/{account_number}

```json
{
"data": {
"account-number": "5WT00001",
"external-id": "A0000196557",
"opened-at": "2019-03-14T15:39:31.265+00:00",
"nickname": "Individual",
"account-type-name": "Individual",
"day-trader-status": false,
"is-closed": false,
"is-firm-error": false,
"is-firm-proprietary": false,
"is-futures-approved": true,
"is-test-drive": false,
"margin-or-cash": "Margin",
"is-foreign": false,
"funding-date": "2017-01-02",
"investment-objective": "SPECULATION",
"futures-account-purpose": "SPECULATING",
"suitable-options-level": "No Restrictions",
"created-at": "2019-03-14T15:39:31.265+00:00"
},
"context": "/customers/me/accounts/5WT0001"
}

```