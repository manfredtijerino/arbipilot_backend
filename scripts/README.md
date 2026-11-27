# scripts

One-off commands run by hand, such as `env_status.py` (lists `.env` keys as set or empty, never values).

`backtest_download.py` fetches the past prices for the backtest into `history/`; `backtest_run.py tuning|hidden` runs the backtest fixed in `docs/build-roadmap.md` (stage 7a).

`trend_run.py choosing|hidden` runs the trend test fixed in `docs/build-roadmap.md` (stage 7b), on the daily prices fetched by `backtest_download.py daily`.
