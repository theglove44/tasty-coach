<!-- Source: https://developer.tastytrade.com/faq/ -->

# Frequently Asked Questions

### Why am I suddenly getting `unconfirmed_user` errors?

All users must confirm their email address within 3 days of signing up. This includes sandbox users.

To confirm your email address, you must request a confirmation email:

```sh
curl -X POST https://api.cert.tastyworks.com/confirmation -H "Content-Type: application/json" -d '{ "email": "<insert your user email here>" }'

```

Check your inbox for a link to confirm your email address. Once you've clicked the link and see a success message, you are good to go.

### Why do I keep getting `invalid_credentials` errors?

This error occurs when you are entering your username/password wrong during login. Be sure that you are hitting the correct environment. We have a sandbox environment and a production environment. Each environment requires you to have a separate set of credentials (username and password). If you hit the production environment with your sandbox credentials, you'll likely see this `invalid_credentials` error.

To diagnose which environment you are hitting, check the url of your request. The sandbox environment's base URL is `https://api.cert.tastyworks.com`. The **production** environment's base URL is different: `https://api.tastyworks.com`. Check

If needed, you can reset your production password at [tastytrade.com](https://tastytrade.com/).

### Why am I getting a 401 when my credentials are valid?

tastytrade has specific requirements around the `User-Agent` header. The format should be `<product>/<version>`, otherwise you'll get a 401 with a response like this:

```xml
<html>

<head>
  <title>401 Authorization Required</title>
</head>

<body>
  <center>
    <h1>401 Authorization Required</h1>
  </center>
  <hr>
  <center>nginx</center>
</body>

</html>

```

Head to our [API Conventions](https://developer.tastytrade.com/faq/api-overview/#api-conventions-rest-json) section for more info.

### Why are my http requests suddenly timing out?

tastytrade will block your IP address outright if we receive too many failed login attempts within a short period of time. We do this to protect our users' accounts from being brute forced.

The IP address block typically lasts 8 hours. During that time, you won't be able to connect to any of our endpoints. Instead, your request will time out.

You can contact [](mailto:api.support@tastytrade.com)[api.support@tastytrade.com](mailto:api.support@tastytrade.com) to ask to be unblocked.

### How do I reset my sandbox user password?

Head to the [Sandbox page](https://developer.tastytrade.com/faq/sandbox) and look for the "Reset it here" link under the sign in button. Enter your email address in the provided field and check your inbox for further instructions.

### Can I delete my sandbox user?

No, you cannot delete your sandbox user. If you no longer have access to the email account, please contact [](mailto:api.support@tastytrade.com)[api.support@tastytrade.com](mailto:api.support@tastytrade.com).

### Why am I getting `unauthorized` errors?

This error occurs when you don't have a valid access token. Access tokens last 15 minutes and must be sent with every request in the `Authorization` header. See our [Auth Patterns](https://developer.tastytrade.com/faq/api-overview/#auth-patterns) section for more info. You need to generate an access token and include the access token as the value of the `Authorization` header in every subsequent request.

### I can't access your sandbox environment

If you see errors like `Failed to resolve` or `ENOTFOUND`, be sure you are using the correct URL. Our sandbox environment's URL is `api.cert.tastyworks.com`. To fetch your accounts, you would need to hit `api.cert.tastyworks.com/customers/me/accounts`, for example.

### I am having trouble getting quotes

Head to our [Streaming Market Data](https://developer.tastytrade.com/faq/streaming-market-data/) section for instructions on how to stream quotes. It is a multi-step process, starting with fetching an api quote token from tastytrade and using that token to authenticate with our quote provider - DxLink.

### Do you have any sample code I can use to get started?

Head to the [SDKs page](https://developer.tastytrade.com/faq/sdk) to see if we offer anything in your preferred language.

We also have a public Postman workspace that anyone can use to start sending api requests to our sandbox environment. You can find it [here.](https://www.postman.com/tastytradeapi/workspace/tastytrade-api)

© 2017–2026 tastytrade, Inc.

tastytrade, Inc., member [FINRA](http://www.finra.org/) | [SIPC](https://www.sipc.org/) | [NFA](https://www.nfa.futures.org/)

By using tastytrade's API, you agree to our [API Terms of Service](https://assets.tastyworks.com/production/documents/USA/open%5Fapi%5Fterms%5Fand%5Fconditions.pdf).

[FINRA Broker Check](https://brokercheck.finra.org/)

[Disclosures](https://tastytrade.com/disclosures/)

Options involve risk and are not suitable for all investors as the special risks inherent to options trading may expose investors to potentially significant losses. Please read [Characteristics and Risks of Standardized Options](https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document) before deciding to invest in options.

Futures accounts are not protected by the Securities Investor Protection Corporation (SIPC). All customer futures accounts’ positions and cash balances are segregated by Apex Clearing Corporation. Futures and futures options trading is speculative and is not suitable for all investors. Please read the [Futures & Exchange-Traded Options Risk Disclosure Statement](https://assets.tastyworks.com/production/documents/USA/futures%5Fexchange%5Ftraded%5Foptions%5Frisk%5Fdisclosure%5Fagreement.pdf) prior to trading futures products.

Cryptocurrency transaction and custody services are powered by Zero Hash LLC and Zero Hash Liquidity Services LLC. Cryptocurrency assets are held and custodied by Zero Hash LLC, not tastytrade. Zero Hash LLC and Zero Hash Liquidity Services are licensed to engage in Virtual Currency Business Activity by the New York State Department of Financial Services. Cryptocurrency assets are not subject to Federal Deposit Insurance Corporation (FDIC) or Securities Investor Protection Corporation (SIPC) coverage. Cryptocurrency trading is not suitable for all investors due to the number of risks involved. The value of any cryptocurrency, including digital assets pegged to fiat currency, commodities, or any other asset, may go to zero.