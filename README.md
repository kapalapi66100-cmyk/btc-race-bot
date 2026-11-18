# btc-race-bot

A trend-following bot for make.fun's `btc-race-24h-20261118-1444`: race a BTC
trading bot live for 24 hours. It trades Coinbase Wrapped BTC (cbBTC) against
USDC on 1-minute on-chain prices, starting with $1,000 of paper money.

## Strategy

Slow and selective, because a full round trip costs about 26 bps (4 bps fee +
2 bps slippage + pool impact) and most 1-minute moves are far smaller than
that. Fast signals churn and lose to fees — every fast EMA baseline lost
money on the dev window.

- **Indicators:** fast EMA(60) [1h] and slow EMA(240) [4h] on 1-minute closes.
- **Entry:** fast EMA crosses above slow EMA **and** the 4-hour momentum
  (close vs the close 240 bars ago) is above +20 bps. The momentum filter is
  what keeps the bot out of weak, choppy crossings. It buys with all its cash
  (max weight is 100% of equity, one position).
- **Exit:** fast EMA crosses back below slow EMA, or the close falls 0.8%
  below the highest close since entry (trailing stop), or the position falls
  1.5% below its cost (hard stop).
- **Otherwise:** it sits in cash. In a falling market that is the right
  trade — the dev window fell 2.8% and buy-and-hold lost $31.63 there.

## Dev result (local replay, faithful to the harness fill model)

- **Net PnL: +$7.45** (passes the dev gate: above $0)
- **Trades: 2** (one round trip: bought the mid-day rally, sold after it)
- **Max drawdown: 0.97%** (guardrail is 25%)
- **Deterministic:** two runs produce byte-identical action logs

The entrypoint is `main.py` (Python 3.13, standard library only). It speaks
`agent-fun/bars-replay/v1` through the vendored shim `vendor/makefun_bars.py`
(a byte-identical copy of the kit SDK). It reads no clock, no environment and
no file outside the repo.

## Files

- `main.py` — the bot
- `vendor/makefun_bars.py` — the kit's bars-replay shim (byte copy)
- `LICENSE` — MIT
