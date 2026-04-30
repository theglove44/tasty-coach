# tasty-coach: Best Trades Today Task Breakdown

> Bite-sized implementation plan for Codex / Claude Code.

## Task 1: Add the new CLI entry point
**Objective:** Create a command that triggers the watchlist-wide trade ranking flow.

**Files:**
- Modify: `main.py`
- Modify: `utils/launcher_ui.py` if the launcher exposes commands there
- Test: `tests/test_launcher_ui.py` or a new CLI test file

**Work:**
- Add a new command name such as `--best-trades` or `--rank-trades`.
- Wire it to a new ranking function rather than reusing single-symbol review.
- Make sure it can run without user interaction.

**Verify:**
- `./venv/bin/python main.py --help`
- confirm the new command appears

---

## Task 2: Build watchlist scanning
**Objective:** Read all watchlist symbols and collect the market inputs needed for ranking.

**Files:**
- Create: `agents/trade_ranker.py` or similar
- Modify: `agents/options_researcher.py` if it already has useful chain logic
- Modify: `utils/tasty_client.py` if any missing market-data helpers are needed
- Test: `tests/test_trade_ranker.py`

**Work:**
- Load the watchlist symbols.
- For each symbol, gather:
  - price
  - option chain
  - bid/ask/spread info
  - IV / IVR / expected move if available
  - earnings/event proximity
  - basic trend or regime inputs
- Return a normalised per-symbol data object.

**Verify:**
- unit test that a watchlist symbol becomes a candidate data object
- unit test that a broken symbol does not crash the scan

---

## Task 3: Add candidate generation per symbol
**Objective:** Turn scanned symbols into valid trade candidates.

**Files:**
- Create/modify: `agents/trade_ranker.py`
- Test: `tests/test_trade_ranker.py`

**Work:**
- Generate candidate structures only when they make sense for the symbol and data.
- Candidate types may include:
  - credit spread
  - iron condor
  - strangle
  - other structures already supported by the app
- Keep candidate generation deterministic and testable.

**Verify:**
- given sample market data, candidate generation returns expected structures
- invalid structures are not created

---

## Task 4: Add hard quality gates
**Objective:** Reject obviously bad trades before scoring.

**Files:**
- Create/modify: `agents/trade_ranker.py`
- Test: `tests/test_trade_ranker.py`

**Work:**
- Implement filters for:
  - earnings too close
  - poor liquidity
  - huge spreads
  - oversized risk vs NLV
  - concentration overlap
  - event risk
  - broken pricing / market closed conditions
- Return rejection reasons, not just a boolean.

**Verify:**
- unit tests for each gate
- rejected candidates include human-readable reasons

---

## Task 5: Add scoring with explanations
**Objective:** Score surviving trades and explain the score.

**Files:**
- Create/modify: `agents/trade_ranker.py`
- Test: `tests/test_trade_ranker.py`

**Work:**
- Score candidates out of 100.
- Include component scores such as:
  - regime fit
  - liquidity
  - volatility edge
  - event risk
  - structure quality
  - account fit
  - concentration penalty
- Return score breakdown plus summary text.

**Verify:**
- unit test score ordering
- unit test breakdown sums sensibly to total score

---

## Task 6: Make the ranking account-aware
**Objective:** Compare candidates against the live account before final ranking.

**Files:**
- Create/modify: `agents/trade_ranker.py`
- Modify: `agents/manager.py` if account metrics are already computed there
- Test: `tests/test_trade_ranker.py` and `tests/test_risk_manager.py`

**Work:**
- Pull account state:
  - NLV
  - cash
  - BP usage
  - delta
  - theta
  - existing concentration
  - current positions
- Penalise or reject candidates that add bad overlap or exceed sensible limits.

**Verify:**
- candidate scores change when account state changes
- oversized additions are rejected or down-ranked

---

## Task 7: Produce the top 3 output
**Objective:** Return the final answer in a clear trader-friendly format.

**Files:**
- Create/modify: `agents/trade_ranker.py`
- Modify: `main.py`
- Test: `tests/test_trade_ranker.py`

**Work:**
- Sort candidates by final score.
- Return the top 3 only.
- Show:
  - trade
  - score
  - reasons
  - account-fit notes
  - rejection summary for others

**Verify:**
- output has exactly 3 top candidates when 3 exist
- output still works with fewer than 3 valid candidates

---

## Task 8: Add entry logging
**Objective:** Save the market and account context used when a trade is entered.

**Files:**
- Create: `utils/trade_journal.py` or similar
- Modify: trade entry flow in the ranking/launcher layer
- Test: `tests/test_trade_journal.py`

**Work:**
- Persist a structured record for each entry.
- Include the metrics needed for later review and learning.
- Use a format that is easy to inspect and easy to export later.

**Verify:**
- a trade entry creates a log record
- the record contains all required fields

---

## Task 9: Add exit logging and lesson tags
**Objective:** Store what happened after a trade closed.

**Files:**
- Modify: trade close / history pipeline
- Create/modify: `utils/trade_journal.py`
- Test: `tests/test_trade_journal.py`

**Work:**
- Record exit P/L, hold time, thesis result, and failure mode.
- Add lesson tags for repeated patterns.
- Keep this simple and structured.

**Verify:**
- closing a trade adds an exit record
- lesson tags appear in the saved record

---

## Task 10: Add a learning index
**Objective:** Make the logged trades searchable for future ranking.

**Files:**
- Create: `docs/trade-learning/` or a similar folder
- Create: index file and per-trade notes if needed
- Test: basic file existence / generation tests

**Work:**
- Add a lightweight filing system for entries, exits, and lessons.
- Keep it simple enough that future ranking code can read it.

**Verify:**
- entries are written to a predictable path
- index references the stored notes

---

## Final verification
Run the full flow end-to-end:
1. scan watchlist
2. generate candidates
3. apply gates
4. score survivors
5. account-fit check
6. print top 3
7. log the run

Expected result:
- top 3 appear
- reasons are visible
- bad candidates are rejected with explanations
- logs are written
