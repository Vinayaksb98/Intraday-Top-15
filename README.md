# BOP Top 15 — NSE All-Equity Update

This update replaces manual stock entry with an NSE equity-universe selector.

Options:
- All NSE Equity (automatic)
- NSE liquid scan (faster)
- My 7 reference stocks

The app retrieves the NSE equity security master and uses Yahoo Finance daily OHLCV data
for research scoring. It ranks the scanned symbols and displays the Top 15.

Important: free Yahoo Finance data is not a guaranteed real-time NSE feed. Scanning a very
large universe can be slow or rate-limited. Increase max symbols gradually.

For true intraday/live scanning, replace the data layer with a licensed live market-data API
(e.g. Zerodha Kite Connect) and do not put API secrets in the source code.
