# scripts

One-off commands run by hand, such as `env_status.py` (lists `.env` keys as set or empty, never values).

`backtest_download.py` fetches the past prices for the backtest into `history/`; `backtest_run.py tuning|hidden` runs the backtest fixed in `docs/build-roadmap.md` (stage 7a).

`trend_run.py choosing|hidden` runs the trend test fixed in `docs/build-roadmap.md` (stage 7b), on the daily prices fetched by `backtest_download.py daily`.

`spread_measure.py measure|summary` measures each coin's spread for the ten-coin trend test (stage 7c): once a minute for 7 days, from Binance's public best bid and ask. It runs by itself on the server, with Python's own library only: no key, no `.env`, no database.

`trend_ten_run.py run` runs the ten-coin trend test fixed in `docs/build-roadmap.md` (stage 7c), once. It downloads the candles itself and refuses to start until the ten measured spreads are filled in.
