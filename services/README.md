# services

The functions behind the non-trading endpoints: login, users, integration checks, system status.

- `paper_service.py`: the paper account. It joins the risk engine, the pretend fills and the database; every pretend order goes through it. It also holds the stop button (kill, resume, status) and the order diary.
