# tasty-coach: Best Trades Today Acceptance Checklist

## User-facing behaviour
- [ ] User can ask for the best trades from the watchlist in one command
- [ ] Tool returns the top 3 trades only
- [ ] Each trade includes a score and a plain-English reason
- [ ] Rejected symbols/candidates show why they were rejected
- [ ] Output is fast enough to use daily

## Market quality gates
- [ ] Earnings/event risk is checked
- [ ] Liquidity / spread quality is checked
- [ ] Volatility / expected move context is used
- [ ] Bad market session conditions are handled
- [ ] Obvious junk setups are filtered out before ranking

## Account-aware checks
- [ ] Tool reads current positions
- [ ] Tool reads NLV, cash, BP usage, delta, theta
- [ ] Tool checks concentration / overlap risk
- [ ] Tool down-ranks or blocks trades that add too much exposure
- [ ] Tool explains when a trade is good in general but bad for this account

## Scoring and explainability
- [ ] Scores are visible out of 100
- [ ] Score includes a component breakdown
- [ ] Rank order is stable and reproducible
- [ ] Reasons are understandable without reading code
- [ ] Bad scores are explainable, not mysterious

## Logging and learning
- [ ] Entry context is logged
- [ ] Exit context is logged
- [ ] P/L and hold time are saved
- [ ] Lesson tags are attached to outcomes
- [ ] History is stored in a predictable file structure
- [ ] Future ranking can read past results for pattern learning

## Engineering quality
- [ ] New command is wired into CLI/help text
- [ ] Unit tests cover the scanner, gates, scoring, and output
- [ ] Existing functionality still works
- [ ] No silent failure when market data is missing
- [ ] The implementation is modular, not a giant ball of spaghetti

## Definition of done
- [ ] I can ask for the best trades today
- [ ] The tool runs the gates automatically
- [ ] It gives me the top 3 with reasons and scores
- [ ] It checks my account before recommending anything
- [ ] It logs what happened so the next run can learn from it
