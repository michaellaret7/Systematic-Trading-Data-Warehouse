# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

The **data warehouse** for the systematic-trading stack: it fetches market data from vendors (currently FMP), normalizes it, and stores it in **ArcticDB on S3** as a small number of versioned logical tables. It does not backtest, size positions, or place orders — downstream repos read from here.

## Commands

Single package (`systematic-trading-data-warehouse`) managed by **uv**. Python `>=3.11` (`.venv` is on 3.13); there is no `.python-version` pin. `uv sync` installs everything, including the `dev` group (pytest).

Most commands need credentials in the environment:

```bash
set -a; source .env; set +a
```

- `uv run python -m src.jobs.update_equities AAPL MSFT` — fetch daily OHLCV for the named tickers and upsert them into the `daily_prices` table. One call covers every ticker passed.
- `uv run python scripts/seed_universe.py` — seed `ticker_universe` from FMP's profile-bulk endpoint (paged, rate-limited, prints a live progress bar).
- `uv run python scripts/seed_equities.py` — build a filtered US equity list from FMP's company screener.
- `uv run pytest` — full offline test suite. **No network, no S3**: every test mocks the HTTP layer and writes to a temporary local LMDB Arctic instance.

Ruff is not a project dependency; run it on demand with `uvx ruff format src scripts tests` / `uvx ruff check src scripts tests`. Keep lines under 100 characters (the codebase currently maxes out at 94).

`scripts/` holds one-shot and scheduled seeding jobs that are run by hand. `src/jobs/` holds the recurring update jobs.

## Architecture

Three layers, each with one job. Keep the boundaries:

```
src/
  vendors/fmp/       # vendor boundary: HTTP, throttling, payload → typed Polars frame
    helpers.py       #   shared HTTP/retry/rate-limit/coercion plumbing (dataset-agnostic)
    prices.py        #   daily OHLCV
    profiles.py      #   company profiles / ticker universe
  storage/arctic.py  # declarative Dataset registry + generic read/write/upsert over ArcticDB
  jobs/              # recurring jobs that wire a vendor fetch to a storage write
  api/               # read-side surface for consumers
  config.py          # env/secrets (placeholder — not yet written)
  main.py            # entry point (placeholder — not yet written)
scripts/             # hand-run seeding jobs
tests/               # mirrors the modules under test: test_arctic, test_fmp_*, test_equities
```

**Dataflow is one-directional:** `vendors → jobs → storage`. Vendor modules never import storage; storage never makes HTTP calls. A job is the only place the two meet.

### Current state (mid-refactor)

`src/config.py`, `src/main.py`, `src/api/equities.py`, and `src/jobs/scheduler.py` are **empty placeholders**. `src/vendors/fmp.py` was split into the `src/vendors/fmp/` package.

`update_equities.py` was gutted in that move and has since been restored: it calls `fetch_daily_prices` **once** for the whole batch and upserts on `(date, symbol)`. `uv run pytest` is green.

### Storage: datasets are declared, not hand-written

`storage/arctic.py` describes each dataset as a frozen `Dataset` — three fields: ArcticDB symbol, Polars schema, and the `key` columns that identify a row — and serves them all through one generic `read` / `write` / `upsert` trio.

**Adding a dataset means adding a `Dataset` entry, not another pair of hand-written functions.** Don't add named wrappers (`read_daily_prices`, `write_ticker_universe`); they were pure aliasing and were deleted. Call `read(library, DAILY_PRICES, ...)`.

Current datasets, both in the `market_data` library:

| symbol | key (and sort order) | pandas index | source |
| --- | --- | --- | --- |
| `daily_prices` | `(date, symbol)` | `date` | `fmp.prices.fetch_daily_prices` |
| `ticker_universe` | `(symbol,)` | RangeIndex | `fmp.profiles.fetch_ticker_universe` |

Non-obvious storage invariants (learned the hard way — the comments in `arctic.py` are load-bearing):

- **Only a timestamp index earns ArcticDB anything.** `Dataset.time_index` is `key[0]` when that column is temporal, and `None` otherwise. A string index buys no pruning and mangles the column name on the way back, so `ticker_universe` is stored on a plain RangeIndex with `symbol` as an ordinary column. **Never write a MultiIndex** — that was the sole cause of the old `index` / `level_0` / `<name>_0` renaming mess. A single named `DatetimeIndex` round-trips its name cleanly.
- **ArcticDB widens every temporal column to naive `datetime[ns]`** — both index and data columns, timezones dropped. `_conform` casts them back to the declared dtype on read. This is the round-trip, not defensive coding; deleting it silently changes `pl.Date` to `Datetime` and drops tz-awareness.
- **Push filters down into ArcticDB**, never read-then-filter in Polars. `symbols=` becomes a `QueryBuilder` predicate, `start`/`end` skip whole row-segments in storage, and `where=` takes a raw `QueryBuilder` for anything else. Don't build a query DSL on top of `QueryBuilder` — expose it.
- **ArcticDB silently ignores unknown column names.** `read` raises on a typo instead of quietly returning fewer columns.
- **`start`/`end` only apply to time-indexed datasets** — they raise on `ticker_universe`.
- **`upsert` rewrites only the date range `fresh` spans**, via `Library.update(..., date_range=..., upsert=True)`. It reads that range, merges on the key with `fresh` last so `keep="last"` lets refreshed rows win, and writes it back. Order matters. Never reintroduce read-whole-table/rewrite-whole-table — measured at 7.5x slower on 1M local rows, and far worse over S3.
- **`Library.update` rejects unsorted input**, so `_to_pandas` sorting by `key` is correctness, not cosmetics.
- Ticker symbols are upper-cased and stripped at every entry point (`normalize_symbols`, `read`). Keep new entry points consistent.

### Vendors: the messy edge

Everything that knows an endpoint's shape lives under `src/vendors/<vendor>/`, one module per dataset plus a shared `helpers.py`. A vendor module's contract is: **take tickers, return a Polars frame matching a declared schema.** It returns data, never writes it.

FMP-specific facts worth keeping:

- **Payloads are loosely typed and mixed-format.** Bulk endpoints return CSV, most others JSON; `parse_rows` handles both. CSV is read with `infer_schema_length=0` (everything as text) because inferring from a sample breaks on fields like `fullTimeEmployees` reporting `"165.8"` — the `as_bool` / `as_float` / `as_str` / `as_date` coercers decide the types instead.
- **Field names mix camelCase and snake_case.** Use `field(row, "marketCap", "market_cap")` rather than indexing directly.
- **429/502/503/504 are expected, not exceptional.** `helpers.get` retries them with exponential backoff and honours `Retry-After`. Bulk endpoints throw 502 under load by FMP's own docs.
- **Rate limits are etiquette, not quotas.** `RateLimiter` paces a rolling minute (default 250/min, conservative under the 300/min Starter plan); profile-bulk is paced optimistically and leans on the 429 backoff. Don't lower these into a hard 60s sleep without a reason.
- **The number of profile-bulk parts is unknown up front** — pagination ends when a part comes back empty, bounded by `PROFILE_BULK_MAX_PARTS`.
- **Pass `wait=` to skip sleeping in tests**; never `patch` `time.sleep` globally.
- Each new dataset re-exports its public names through `src/vendors/fmp/__init__.py`'s `__all__`.

## Configuration

`.env` is required (copy `.env.example`): `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION`, `S3_BUCKET`, `FMP_API_KEY`, `DIGITALOCEAN_TOKEN`.

Storage resolves to `s3s://s3.<region>.amazonaws.com:<bucket>?...&path_prefix=arcticdb`, library `market_data`.

`src/config.py` exists to become the single place credentials are read; today `scripts/` and jobs call `load_dotenv()` and `os.environ` directly. **When you write `config.py`, move them onto it** — fail fast on missing keys, and stop reading `os.environ` outside it.

## Safety rails (data-warehouse-specific)

- **Writes to S3 are shared state.** `write` *replaces* a dataset's entire contents; only `upsert` merges. Note that `upsert` still *replaces* every stored row inside the date range `fresh` spans — pass a complete slice for that range, not a partial one. Never call `write` against the real S3 library to "test" something — use a temporary LMDB library (`Arctic(f"lmdb://{tmp_path}")`), exactly as the tests do.
- **Never run a seeding script yourself** unless the user explicitly asks. `seed_universe.py` makes thousands of API calls and overwrites `ticker_universe`. `pytest` is safe to run freely.
- **Respect the vendor's quota.** Don't add a loop that fans out per-ticker requests without a `RateLimiter`; the daily-price endpoint is already one HTTP call per symbol.
- **Backfills are expensive and hard to undo.** Before changing a schema or index, say what happens to the existing stored rows — ArcticDB versions writes, but a schema change means a rewrite.

## Response Type
- Please be clear, concise, and to the point in your responses and do your best to avoid unecessary verbosity

## Overall Goal of Code
- To write clean, clear, well architected code that is easy for humans to understand

## Development Guidelines

### Core Philosophy

- **KISS** — choose straightforward solutions; simple is easier to maintain and debug.
- **YAGNI** — implement only what's needed now, not what might be useful later.
- **DRY** — single source of truth for every piece of knowledge. Search for an existing helper before writing a new one; extract shared logic into pure reusable functions.

#### 1. Think Before Coding

Don't assume. Don't hide confusion. Surface tradeoffs.

Before implementing:

- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

#### 2. Simplicity First

Minimum code that solves the problem. Nothing speculative.

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.
- Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

#### 3. Surgical Changes

Touch only what you must. Clean up only your own mess.

When editing existing code:

- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:

- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

#### 4. Goal-Driven Execution

Define success criteria. Loop until verified.

Transform tasks into verifiable goals:

- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:

1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

### Design Principles

- **Dependency Inversion** — high-level modules depend on abstractions, not low-level modules.
- **Open/Closed** — open for extension, closed for modification.
- **Single Responsibility** — one clear purpose per function/class/module.
- **Fail Fast** — validate early, raise immediately when something's wrong.
- **Type safety** — type hints and explicit return types are mandatory; the codebase should read as self-documenting.
- **Resource efficiency** — context managers for all I/O; vectorize data-heavy work.

### Code Constraints

- Files: max 500 lines — split into modules if approaching the limit.
- Functions: max 50 lines, single responsibility.
- Classes: max 100 lines, one concept.
- Group code by feature/responsibility.

### Data handling

- **Polars, not pandas.** Pandas appears only where ArcticDB's write path requires it (`_to_pandas` converts at the boundary). Don't spread it further.
- **Declare the schema.** Every frame that crosses a module boundary has a `dict[str, pl.DataType]` schema constant next to the function that produces it, and is conformed to it before being returned or stored.
- **Vectorize.** Build columns with Polars expressions; a Python loop over rows in the data path is a bug, not a style choice. Looping over *tickers* to make one HTTP call each is fine — looping over rows to compute values is not.
- **Missing is `None`, not a sentinel.** Coercers return `None` on unparseable input rather than 0.0 or `""`.

### Whitespace & Vertical Formatting (CRITICAL)

Code must breathe. Use blank lines to separate logical blocks within functions:

- Blank line after the initial declaration block.
- Blank line between distinct steps inside a loop (fetch → validate → transform → assign).
- Blank line before `return`.
- Blank line between independent `if` checks in a loop.

```python
def process_items(items: list[str], lookup: dict):
    results: dict[str, float] = {}
    errors: list[str] = []

    for item in items:
        value = lookup.get(item)

        if value is None:
            errors.append(item)
            continue

        transformed = value * 2.0

        results[item] = transformed

    return results, errors
```

### Naming

- Variables/functions: `snake_case`
- Classes: `PascalCase`
- Constants: `UPPER_SNAKE_CASE`
- Private attributes: `_leading_underscore`
- Type aliases / Enums: `PascalCase` / `UPPER_SNAKE_CASE`
- Never prefix folders or files with `_`.

### Documentation

- Module docstring explaining purpose.
- Complete docstrings on public functions.
- **Function docstrings: short, plain, direct.** Two short sentences max when possible — what it does, what it returns. No Args/Returns blocks, no implementation narration, no restating type hints. Example:

  ```python
  def write(library, dataset, frame):
      """Replace a dataset's entire contents with `frame`."""
  ```

- **Never delete user-authored comments.** Do not remove, rewrite, relocate, or "clean up" comments the user wrote — including inline notes, step markers, trailing flow/design blocks (e.g. module-level `"""..."""` plans), and TODO annotations. If a comment is factually wrong after a code change, fix the factual part in place; do not delete the comment. When rewriting a file, restore every pre-existing user comment. This overrides any default tendency to strip "narration" comments.
- When editing a function, leave untouched comments exactly as they are unless the line they describe is itself being changed.
- **Comments explain vendor and storage quirks, not syntax.** The valuable comments in this repo record *why* a workaround exists (FMP's decimal FTE counts, ArcticDB's index renaming). Keep writing those; keep deleting none.
- Helper functions live at the **top** of the file under a banner block:

  ```
  # ====================================
  # --> Helper funcs
  # ====================================
  ```

### Complexity Gauging

Before writing or planning: assess whether the approach is under-engineered, optimally engineered, or over-engineered. Aim for the middle.

### Testing

- No pytest scaffolding — write **real tests with real data**.
- A test exercises the full flow: pull real inputs, call the function, grade the output. Lint/format afterward.
- Don't create parallel `test_x.py` and `test_x_fixed.py` files — fix the one test in place.
- **The suite is offline and must stay offline.** Vendor tests drive `httpx.MockTransport` or a `MagicMock(spec=httpx.Client)` with realistic payloads (including the malformed ones FMP actually sends); storage tests use a temporary LMDB library under `tmp_path`. No test may touch S3 or the FMP API.
- **Test through the declared schema.** Build fixture frames with `schema=TABLE.schema` so a schema change breaks the test loudly instead of silently coercing.
- Pass `wait=`/inject a fake clock rather than sleeping — tests must not spend real seconds on backoff.

### Hard Rules

- **No backwards-compatibility shims.** If a change is needed, build the new solution and update every caller. Backwards-compat violates the design principles.
- **Never create CLI flag–driven test scripts** like `tests/foo.py --mode long-only`. If behavior needs to switch, write separate entry points or pass arguments programmatically.
- **Never auto-create READMEs** for specific functionality unless explicitly requested.
- **Disagree freely** — correctness beats agreement. If the user is wrong, say so.
- For specs, standards, or patterns worth referencing later, write a document under `docs/` (create it when the first one is needed), organized by topic (e.g. `docs/storage/`, `docs/vendors/`). Institutional knowledge belongs in the repo, not just chat history.
- **Agent system prompts use XML tags** (`<role>`, `<methodology>`, `<constraints>`, `<output_format>`) for top-level structure; markdown headers are sub-structure within those XML sections.
- Use the LSP / Pyright server when available.

### Branching

`main` (production) · `dev` (integration) · `feature/*` · `fix/*` · `refactor/*` · `docs/*` · `test/*`
