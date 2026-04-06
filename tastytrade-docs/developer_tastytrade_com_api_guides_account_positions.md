<!-- Source: https://developer.tastytrade.com/api-guides/account-positions/ -->

# Account Positions

### List Account Positions

A position with a quantity of 0 is considered closed. We purge these positions overnight.

Equity option positions will also include an **expires-at** timestamp.

For profit/loss calculations, you should rely on the live quote data as much as possible to ensure up-to-date calculations (see [Streaming Market Data](https://developer.tastytrade.com/api-guides/account-positions/streaming-market-data/)).

Path Parameters

account\_number

String

required

Account number of the account

GET

/accounts/{account\_number}/positions

```json
{
    "data": {
        "items": [
            {
                "account-number": "5WT00000",
                "symbol": "AAPL",
                "instrument-type": "Equity",
                "underlying-symbol": "AAPL",
                "quantity": "100",
                "quantity-direction": "Long",
                "close-price": "282.48",
                "average-open-price": "288.7",
                "average-yearly-market-close-price": "123.18",
                "average-daily-market-close-price": "282.48",
                "multiplier": 1,
                "cost-effect": "Credit",
                "is-suppressed": false,
                "is-frozen": false,
                "restricted-quantity": "0.0",
                "realized-day-gain": "0.0",
                "realized-day-gain-effect": "None",
                "realized-day-gain-date": "2022-11-01",
                "realized-today": "0.0",
                "realized-today-effect": "None",
                "realized-today-date": "2022-11-01",
                "created-at": "2022-08-22T17:56:51.872+00:00",
                "updated-at": "2022-11-01T21:49:54.095+00:00"
            }
        ]
    },
    "context": "/accounts/5WT00000/positions"
}

```

Response Data Definitions

account-number

String

Your account number

average-daily-market-close-price

Decimal

Cost basis for unrealized day gain calculation

average-open-price

Decimal

A running average of the open price of the position. Cost basis for unrealized gain since open calculation

average-yearly-market-close-price

Decimal

Cost basis for unrealized year gain calculation

close-price

Decimal

Price of the instrument at market close yesterday

cost-effect

String

A tastytrade-specific value to categorize the cost of the position

Values: 

Credit, Debit, None

example: 

Credit

expires-at

DateTime

The date and time at which the position expires. Applies to futures and options.

example: 

2024-12-20T21:15:00.000+00:00

instrument-type

String

The instrument type of the position

Values: 

Equity, Equity Option, Future, Future Option, Cryptocurrency

example: 

Future Option

is-frozen

Boolean

Indicates the rare case when an admin has taken action to freeze this position. Tastytrade will do this to protect a compromised account. Frozen positions are not adjustable/tradeable.

is-suppressed

Boolean

This field is not in use anymore and can be ignored

multiplier

Integer

Indicates the notional multiplier of the position based on what is delivered if the position gets exercised/assigned. For example, equity options usually have a multiplier of \`100\`, meaning the option contract delivers 100 shares upon exercise.

quantity

Decimal

The quantity of your position. Some stocks can be traded in fractional quantities.

example: 

10

quantity-direction

String

Indicates the side or direction of the position. Zero means the position is closed.

Values: 

Long, Short, Zero

realized-day-gain

Decimal

An aggregate amount of profit or loss on a realized (already closed) position for the current trading day. This number is based on the position’s opening mark for the day.

realized-day-gain-date

Date

Indicates the date of realized day gain

example: 

2024-09-18

realized-day-gain-effect

String

The direction of the realized day gain. Credit means positive gain. Debit means loss.

Values: 

Credit, Debit, None

realized-today

Decimal

The total profit or loss realized from a position since it was opened.

realized-today-date

Date

Indicates the date of the realized today value.

example: 

2024-09-18

realized-today-effect

String

The direction of the realized today value. Credit means positive gain. Debit means loss.

Values: 

Credit, Debit, None

restricted-quantity

Integer

The quantity that cannot be traded or modified due to something like an expected assignment

symbol

String

Symbol of the position

example: 

./ESZ4 EW3U4 240920P5650

underlying-symbol

String

The symbol of the underlying instrument, if applicable

example: 

/ESZ4

## Profit/Loss Calculations

The following are some high-level calculations you can do to see the profit/loss of your positions. These are not intended to be a copy-paste answer to all your P/L questions. The numbers you see may be slightly different from what you see when using the tastytrade application. This may be due to many factors, including which language you are using, the speed of your internet connection, the interval at which you receive quote data, etc. Please understand that the formulas we provide below are very basic, but will fit most people's needs.

You'll also find the terms _realized_ and _unrealized_ in the sections below. _Realized profit/loss_ occurs when you close a position. _Unrealized profit/loss_ occurs on any open positions. For example, suppose you are long 100 shares of ABCD stock that you bought for $10 each, and the current price of ABCD is $11\. This means you have $100 of _unrealized gain_ on the position ($1 per share). You haven't sold the shares yet, so you haven't _realized_ the profit. Once you sell the shares, your realized gain on the position will be $100 and your unrealized gain will be $0\. In other words, the unrealized gain becomes realized gain once you close some or all of the position.

In the previous example, if you were to sell only 25 of your shares at $11, your realized gain would be $25 and your unrealized gain would be $75.

### Basic Formula

The basic math behind a profit/loss calculation is as follows:

For long positions

```mipsasm
(mark - cost basis) * quantity * multiplier

```

For short positions

```mipsasm
(mark - cost basis) * quantity * multiplier

```

The cost basis of the formula will differ depending on what type of gain you are calculating. Continue reading below for a description of each of these terms and a few helpful profit/loss formulas.

### Mark

This is the current market value of a single unit of your position. You can think of this as the market value per unit. For long positions, you can use the `quote.bid`. For short positions, you can use the `quote.ask`. If you don't want to worry about long or short, you can use the mid price, which is calculated by `(quote.bid + quote.ask) / 2`. The `quote.last` price works too if you can't get a bid or ask.

You can get **bidPrice** & **askPrice** from the DXLink `Quote` market event (see [Streaming Market Data](https://developer.tastytrade.com/api-guides/account-positions/streaming-market-data/)).

### Cost Basis

The cost basis will differ depending on what you are calculating. There are several cost basis values that tasty provides:

**position.average-open-price** \- Cost basis for one unit of your position since it was opened. This is used in the _Unrealized Gain_ calculation.

For example, if you buy 100 shares of ABCD for $10 each, your `average-open-price` would be $10\. If you then bought 100 more shares for $11 each, your `average-open-price` would increase to $10.50.

**position.average-daily-market-close-price** \- Cost basis for one unit of your position since yesterday. This is used in the _Unrealized Day Gain_ calculation.

**position.average-yearly-market-close-price** \- Cost basis for one unit of your position since the end of last year. This is used in the _Unrealized Year Gain_ calculation.

### Unrealized Gain

The unrealized profit/loss on the position since it was opened.

For long positions

```arduino
(mark - position.average-open-price) * position.quantity * position.multiplier

```

For short positions

```arduino
(position.average-open-price - mark) * position.quantity * position.multiplier

```

### Unrealized Day Gain

The unrealized profit/loss on the position today.

For long positions

```arduino
(mark - position.average-daily-market-close-price) * position.quantity * position.multiplier

```

For short positions

```arduino
(position.average-daily-market-close-price - mark) * position.quantity * position.multiplier

```

### Realized Gain

The profit/loss made from closing some or all of the position since it was opened.

```arcade
position.realized-today

```

**realized-today-date** is the date any profit/loss was realized. If it is not today's date, you can ignore the `realized-today` value.

### Realized Day Gain

The profit/loss from closing some or all of a position today.

```applescript
position.realized-day-gain

```

**realized-day-gain-date** is the date any profit/loss was realized. If it is not today's date, you can ignore the `realized-day-gain` value.

### P/L Open

The total (realized + unrealized) profit/loss on the position since it was opened.

```arduino
unrealized gain since position open + realized gain since position open

```

### P/L Day

The total (realized + unrealized) profit/loss on the position today.

```applescript
unrealized day gain + realized day gain

```

### Position Current Value

The net liquidating value of the position, or the value you'd receive/pay if you closed it.

```css
mark * position.quantity * multiplier * direction

```

`direction` should be -1 for a short position because you have to pay money to close it out (i.e. you need to pay to buy it back). For long positions, `direction` should be 1.

For example, assume you have 2 equity positions: Long 100 shares of ABC and Short 100 shares of XYZ. Mark for ABC is $100\. Mark for XYZ if $50.

_Current value of ABC:_ $100 \* 100 \* 1 \* 1 = $10,000

_Current value of XYZ:_ $50 \* 100 \* 1 \* -1 = -$5,000

In other words, closing out your ABC shares would credit you $10,000\. Closing out your XYZ shares would debit you $5,000.

`multiplier` is found on the position returned from the tastytrade api when you [fetch your account positions](https://developer.tastytrade.com/api-guides/account-positions/open-api-spec/balances-and-positions/#/positions/getAccountsAccountNumberPositions).

Your position value will change as the mark changes. We recommend reading through the [Streaming Market Data](https://developer.tastytrade.com/api-guides/account-positions/streaming-market-data/) section to monitor quote changes and recalculate your position's value. Some quotes change very rapidly, so it's a good idea to throttle your calculations to once per second.

### Account Current Value (Account Net Liq)

The net liquidating value of your account, or the amount of cash you can expect to have if you were to close all of your positions right now.

```stylus
(sum of current value of account positions) + accountBalance.cash-balance + accountBalance.pending-cash

```

Pending cash means incoming or outgoing cash that hasn't cleared yet. Most of the time your `pending-cash` will be zero. However, if you recently initiated a cash deposit or withdrawal for your account, you may see a non-zero value in your balance's `pending-cash` field. In this case, you need to determine whether the value is positive or negative by checking the `pending-cash-effect` field. `Credit` means positive cash that hasn't yet cleared with the banks yet (like a cash deposit). `Debit` means negative cash (like a withdrawal). Once the deposit/withdrawal clears, the pending cash will be zeroed out and your `cash-balance` will be updated.

`cash-balance` may be positive or negative. To see how your positions affect your cash balance, refer to the [help center article here.](https://support.tastytrade.com/support/s/solutions/articles/43000435348)

For more information on calculating your account net liq, refer to the [help center article here.](https://support.tastytrade.com/support/s/solutions/articles/43000478111)

If we use the example above to calculate our account net liq, we'd add the current value of both ABC and XYZ positions together to get $5,000 ($10,000 ABC value + -$5,000 XYZ value). If our account has $1,000 cash and $0 pending cash in its balance, our total account net liq would be $6,000.

Suppose we then initiated a $500 cash withdrawal. This would show up in the `pending-cash` field as a $500 Debit to our balance. Our account net liq would reduce to $5,500.

© 2017–2026 tastytrade, Inc.

tastytrade, Inc., member [FINRA](http://www.finra.org/) | [SIPC](https://www.sipc.org/) | [NFA](https://www.nfa.futures.org/)

By using tastytrade's API, you agree to our [API Terms of Service](https://assets.tastyworks.com/production/documents/USA/open%5Fapi%5Fterms%5Fand%5Fconditions.pdf).

[FINRA Broker Check](https://brokercheck.finra.org/)

[Disclosures](https://tastytrade.com/disclosures/)

Options involve risk and are not suitable for all investors as the special risks inherent to options trading may expose investors to potentially significant losses. Please read [Characteristics and Risks of Standardized Options](https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document) before deciding to invest in options.

Futures accounts are not protected by the Securities Investor Protection Corporation (SIPC). All customer futures accounts’ positions and cash balances are segregated by Apex Clearing Corporation. Futures and futures options trading is speculative and is not suitable for all investors. Please read the [Futures & Exchange-Traded Options Risk Disclosure Statement](https://assets.tastyworks.com/production/documents/USA/futures%5Fexchange%5Ftraded%5Foptions%5Frisk%5Fdisclosure%5Fagreement.pdf) prior to trading futures products.

Cryptocurrency transaction and custody services are powered by Zero Hash LLC and Zero Hash Liquidity Services LLC. Cryptocurrency assets are held and custodied by Zero Hash LLC, not tastytrade. Zero Hash LLC and Zero Hash Liquidity Services are licensed to engage in Virtual Currency Business Activity by the New York State Department of Financial Services. Cryptocurrency assets are not subject to Federal Deposit Insurance Corporation (FDIC) or Securities Investor Protection Corporation (SIPC) coverage. Cryptocurrency trading is not suitable for all investors due to the number of risks involved. The value of any cryptocurrency, including digital assets pegged to fiat currency, commodities, or any other asset, may go to zero.