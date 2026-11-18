"""Trend-following bot for the make.fun BTC race (cbBTC, 1-minute bars).

Strategy (my own design, built from the dev window's evidence):
  The dev window fell 2.8% with one clear multi-hour rally in the middle.
  Fast 1-minute signals churn: every fast EMA baseline lost money to the
  ~26 bps round-trip cost (fees + slippage + pool impact). So this bot is
  deliberately SLOW and SELECTIVE: it only buys a sustained uptrend and
  rides it, and otherwise sits in cash.

  - Indicators on 1-minute closes: fast EMA(60) [1h] and slow EMA(240) [4h].
    Each EMA starts as the mean of its first span of closes, then moves
    2 / (span + 1) of the way to each new close (float64, deterministic).
  - Entry, on a bar's close (the order fills at the next bar's open):
    fast EMA crosses above slow EMA AND the 4-hour momentum (close vs the
    close 240 bars ago) is above +20 bps. The momentum filter is the point:
    it keeps the bot out of weak, choppy crossings that lose money to fees.
    It buys with all its cash (max weight is 100% of equity, one position).
  - Exit, the whole position: fast EMA crosses back below slow EMA, or the
    close falls 80 bps (0.8%) below the highest close since entry (a
    trailing stop that locks in a rally's gains), or the position falls
    150 bps below its cost (a hard stop against a flash drop).
  - While warming up (hello.warmup_bars) it sends no order and only builds
    its indicators; a gap (a batch with no CBBTC bar) adds nothing.
  - One order per reply at most, sells before buys, max_slippage_bps 100
    (1% past the close it was decided on) so a fill far from the close is
    refused rather than taken at a bad price.

  The bot speaks agent-fun/bars-replay/v1 through the vendored shim
  (vendor/makefun_bars.py, a byte copy of the kit SDK): hello once, then
  one batch per minute, one reply per batch echoing its seq. It reads no
  clock, no environment and no file outside the repo; its orders are a pure
  function of the bars, so two runs on the same data match byte for byte.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

SYMBOL = "CBBTC"
FAST_SPAN = 60    # 1 hour of 1-minute bars
SLOW_SPAN = 240   # 4 hours
MOMENTUM_BARS = 240  # 4-hour momentum lookback
MOMENTUM_MIN_BPS = 20  # entry needs > +20 bps over 4h
TRAIL_BPS = 80    # trailing stop: 0.8% below the peak since entry
STOP_BPS = 150    # hard stop: 1.5% below cost
MAX_SLIPPAGE_BPS = 100  # 1% past the close the order was decided on


class Ema:
    """One EMA: the closes it has seen until it starts, then its value."""

    def __init__(self, span):
        self.span = span
        self.warm = []
        self.value = None

    def step(self, close):
        if self.value is not None:
            self.value += (2.0 / (self.span + 1)) * (close - self.value)
            return
        self.warm.append(close)
        if len(self.warm) == self.span:
            self.value = sum(self.warm) / self.span


# Per-symbol state, built from the bars as they arrive.
fast = Ema(FAST_SPAN)
slow = Ema(SLOW_SPAN)
closes = []          # closes seen, in order (a gap adds nothing)
prev_gap = None      # fast - slow after the previous bar, once both are set
peak_since_entry = None  # highest close since the current entry, or None


def on_batch(state, batch):
    global prev_gap, peak_since_entry
    # Fold this batch's bar into the indicators (only a fresh bar moves them).
    fresh = False
    for bar in batch["bars"]:
        if bar["symbol"] != SYMBOL:
            continue
        fresh = True
        close = int(bar["c"])
        closes.append(close)
        fast.step(close)
        slow.step(close)
    if not fresh:
        return []
    if state.warming_up:
        return []

    gap = None
    if fast.value is not None and slow.value is not None:
        gap = fast.value - slow.value
    held = state.positions.get(SYMBOL)
    close = closes[-1]

    if held is not None:
        # Track the peak since entry for the trailing stop.
        if peak_since_entry is None or close > peak_since_entry:
            peak_since_entry = close
        # Exit on a cross back down, the trailing stop, or the hard stop.
        if prev_gap is not None and gap is not None and gap < 0 and prev_gap >= 0:
            prev_gap = gap
            peak_since_entry = None
            return [{"side": "sell", "symbol": SYMBOL, "qty": held.qty,
                     "max_slippage_bps": MAX_SLIPPAGE_BPS}]
        if peak_since_entry is not None and close < peak_since_entry * (1 - TRAIL_BPS / 10000):
            prev_gap = gap
            peak_since_entry = None
            return [{"side": "sell", "symbol": SYMBOL, "qty": held.qty,
                     "max_slippage_bps": MAX_SLIPPAGE_BPS}]
        value = state.value(SYMBOL, held.qty)
        if value * 10000 < held.cost * (10000 - STOP_BPS):
            prev_gap = gap
            peak_since_entry = None
            return [{"side": "sell", "symbol": SYMBOL, "qty": held.qty,
                     "max_slippage_bps": MAX_SLIPPAGE_BPS}]
        prev_gap = gap
        return []

    # No position: enter only on a fresh cross up with real momentum behind it.
    if gap is not None and prev_gap is not None and gap > 0 and prev_gap <= 0:
        if len(closes) > MOMENTUM_BARS:
            ago = closes[-1 - MOMENTUM_BARS]
            if (close - ago) * 10000 > ago * MOMENTUM_MIN_BPS:
                prev_gap = gap
                peak_since_entry = close
                # Buy with all the cash, capped by the weight room (max_weight_bps
                # of equity): with one position and a 100% cap they agree, but the
                # cap is the binding rule, so honour it explicitly.
                amount = min(state.cash, state.weight_room(SYMBOL))
                if amount >= int(state.hello["fees"]["min_notional_quote_units"]):
                    return [{"side": "buy", "symbol": SYMBOL,
                             "notional_quote_units": amount,
                             "max_slippage_bps": MAX_SLIPPAGE_BPS}]
    prev_gap = gap
    return []


makefun_bars.run(on_batch)
