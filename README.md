# BOP-PRE NSE Scanner v3

## Universe
- NIFTY 500
- Market Cap >= ₹10,000 Cr

## Signal design
The existing strict BUY confirmation is preserved.

### Signals
- BUY: confirmed breakout + existing confirmation conditions
- PRE-BUY STRONG: early setup with stronger pre-breakout evidence
- PRE-BUY: developing pre-breakout setup
- WATCH: monitor
- AVOID: weak setup

## Changes in v3
1. Progressive RVOL scoring replaces the old 0.65–1.35-only scoring rule.
2. Adds PRE-BUY and PRE-BUY STRONG without removing the strict BUY.
3. Results are ranked by actionable signal first, then score and distance to resistance.

## Important
PRE-BUY is a screening signal, not a guarantee. Validate it with historical walk-forward testing before using real money.
