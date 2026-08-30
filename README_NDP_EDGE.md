# NDP-EDGE — Next-Day Intraday Scanner

## Fixed universe
- NIFTY 500 only
- Market Cap >= ₹10,000 Crore

## Main dashboard order
Rank | Share | Current | Trigger | Stop | T1 | T2 | Signal | Score | R:R | Market Cap

## Workflow
1. Run after market close to build the next-day watchlist.
2. Do not automatically buy at market open.
3. Trade only after price crosses Trigger with intraday volume confirmation.
4. Use Stop for risk control and T1/T2 as reference targets.

Research tool only. Historical validation is required before relying on the strategy with real money.
