# SINKA QUANT PRO

OKX USDT perpetual market scanner and manual-trade planning workspace.

## Start

Install Python 3.11+, then run `start_windows.bat` on Windows, or:

```bash
pip install -r requirements.txt
streamlit run app.py
```

The application uses public OKX REST endpoints and does not place orders. It requires internet access. Quotes are refreshed on demand; use the refresh button. Manual positions are saved in local SQLite. Historical signal scores are **not** validated win probabilities. Trading involves substantial risk.

## Features
- BTC, ETH, SOL, BNB, XRP overview
- Liquid USDT swap scanner, top 5 candidates
- Click any coin for a long/short plan with ATR-based stops and targets
- Risk-based position sizing
- Manual open/close positions and PnL summary

## Important
The GitHub repository is public at initial upload. Do not commit secrets, account credentials, or private trading data. Local SQLite databases are excluded from Git.
