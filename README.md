# Stockpilot

![CI](https://github.com/sakib-101-git/stockpilot/actions/workflows/ci.yml/badge.svg)

AI-powered inventory and demand platform: probabilistic demand forecasting,
order recommendations, and an explainable assistant, built with Python and
FastAPI.

**Status:** under construction (Week 1 of 16 complete).

## Quick start

Requires Docker, [uv](https://docs.astral.sh/uv/) and Python 3.12.

```bash
cp .env.example .env
make up        # start Postgres (TimescaleDB) and Redis
make migrate   # apply database migrations
make run       # start the API on http://localhost:8000
make test      # run the tests
```

Open http://localhost:8000/docs for the interactive API docs.

## Building the dataset

Stockpilot uses a sample of the M5 (Walmart) dataset.

1. Download the data from https://www.kaggle.com/c/m5-forecasting-accuracy
   and unzip it into `data/raw/m5/`.
2. Run `uv run python scripts/prepare_m5.py`.

## Design decisions

See [`docs/decisions/`](docs/decisions/) for short notes on the main technical
choices and their trade-offs.

