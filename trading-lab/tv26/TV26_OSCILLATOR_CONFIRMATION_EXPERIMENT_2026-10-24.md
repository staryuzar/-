# TV26 oscillator confirmation experiment — 2026-10-24

Branch: tv26-oscillator-confirmation-study. Research only; no merge to candidate.

## Hypothesis
The total rating averages 15 moving-average votes and 11 oscillator votes. A strong total can pass while oscillators are nearly neutral. Trade-log review on Sep 14–18 showed several losing entries with directional oscillator averages around 0.091, whereas the winning buy setup had at least 0.182 directional oscillator strength on the five timeframes.

The new optional input InpMinDirectionalOscillatorRating adds an entry-only check. For a buy, each timeframe's oscillator average must meet the positive threshold; for a sell it must meet the negative threshold. At 0.00 the filter is disabled, preserving the previous behavior. A threshold of 0.15 effectively requires at least 2 of 11 net directional votes (2/11 = 0.1818). This does not modify the 26 published component ratings or their labels.

## Test protocol
- XAUUSD, Headway-Demo / Jarocel (Pty) Ltd.
- MT5 Strategy Tester Model 4, Every tick based on real ticks; MT5 may synthesize ticks where broker real-tick history is missing.
- Window: 2026-09-01 through 2026-09-10 inclusive.
- $500 initial balance; 1% risk; SL 2 ATR; TP 4 ATR.
- Consensus threshold 0.50, M1 close-breakout enabled, one prior M1 bar, no extra ATR buffer.
- Only the oscillator minimum differs: 0.00 baseline versus 0.15.
- Workflow: https://github.com/staryuzar/-/actions/runs/40106767960

## Acceptance criteria
Require a clean compile, clean export/data audits, identical input/history hashes, a useful number of trades, and manual review of the trade list. Do not accept zero or one trade as evidence of quality. Even a positive screen result requires another unseen period before any promotion.

No MT5 outcome is claimed here until the workflow artifacts are available and checked.


## Infrastructure retry note

The initial run (40106767960) for threshold 0.15 failed before a valid strategy result was produced. MT5 canceled preliminary real-tick history download and logged `no history data, stop testing`; the summary showed no audit export. Treat this as an incomplete infrastructure run, not a 0.15 strategy outcome. The workflow now preserves the first attempt's diagnostic logs and retries once on this precise failure only: https://github.com/staryuzar/-/actions/runs/40107875721. The 0.00 baseline completed successfully; await a full report/audit for a valid comparison.
