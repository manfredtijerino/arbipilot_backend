# exchange

Binance: REST client, market and user streams, exchange filters and the stream recorder. `config.py` first.

- `numbers.py`: Binance's text numbers as exact `Decimal`.
- `filters.py`: each pair's trading rules (minimum order value, steps).
- `market_stream.py`: the live price stream, with reconnect.
- `recorder.py`: saves the stream to `recordings/` and reads it back for tests.
