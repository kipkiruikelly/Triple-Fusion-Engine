# Contributing to BullLogic

Thanks for helping improve BullLogic (Triple-Fusion-Engine). This guide
covers local setup, testing, and the conventions the codebase follows.

## Dev environment setup

1. Clone the repo and create a virtual environment:

   ```bash
   git clone https://github.com/kipkiruikelly/Triple-Fusion-Engine.git
   cd Triple-Fusion-Engine
   python -m venv .venv
   # Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. Copy the environment template and fill in what you need:

   ```bash
   cp .env.example .env
   ```

   For local development only `SECRET_KEY` is required (or set
   `FLASK_DEBUG=true` to use the built-in dev key). Payments, OAuth,
   email, and AI features each need their own credentials; every
   variable is documented inline in `.env.example`.

3. Run the app:

   ```bash
   python app.py
   ```

   The SQLite database is created automatically under `instance/` on
   first start. Live trading stays disabled unless an operator
   explicitly sets `ENABLE_LIVE_TRADING=true`.

## Running tests

```bash
python run_tests.py              # full suite
python run_tests.py --module risk
python run_tests.py --coverage
pytest tests/ -q                 # direct pytest works too
```

Tests run against a throwaway SQLite database, never `instance/users.db`.
All tests must pass before a change is merged.

## Code style

- No emoji in Python files.
- No banner comment separators (no `=====` or `#####` blocks).
- Concise docstrings written in a natural, human voice; explain the
  why, not the obvious what.
- No decorative elements or generated-code signatures.
- Honesty rules: any endpoint or widget backed by demonstration or
  placeholder data must be labeled (`simulated: true` and
  `data_source: "simulated"` in JSON, a visible DEMO DATA badge in
  HTML). `tests/test_honesty_flags.py` enforces the API side.
- Live-trading safety: nothing may place a real broker order unless
  `ENABLE_LIVE_TRADING=true`. `tests/test_mt5_safety.py` enforces this;
  do not weaken it.

## Submitting issues

Open a GitHub issue with:

- What you expected and what happened instead.
- Steps to reproduce (ticker, timeframe, and page if relevant).
- Relevant log output. The app logs to stdout; admin users can also
  check the error log in the admin console.
- Your environment (OS, Python version, browser).

Security issues: do not open a public issue. Email the maintainer
instead so a fix can land before disclosure.
