---
name: organize-file
description: Reorganize a Python file into banner-separated sections, group related functions together, and mark file-private helpers with a leading underscore. Use when asked to "organize this file", "clean up this file", "group these functions", "add section banners", or "make this file readable".
license: Apache-2.0
metadata:
  author: coding-agent
  version: "1.0"
  tags: ["organization", "readability", "refactor"]
---

# Organize File

Restructure a single file so a reader can scan it top-to-bottom and understand the shape of it. Move functions into logical groups, separate the groups with banner comments, and rename true file-only helpers with a leading underscore.

**This is a reorganization, not a rewrite.** Function bodies do not change. If you find a bug, mention it — do not fix it.

`src/storage/arctic/registry.py` is a small example of the target shape (helpers → declarations), and already uses the banner convention below. Read it for the grouping instinct.

## Target shape

```python
"""Module docstring: what this file is for, and any non-obvious 'why'."""

# imports (stdlib, third-party, first-party — ruff isort order)

# module constants (endpoints, schemas, tunables), then type aliases


# ====================================
# --> Helpers
# ====================================


def _helper_one(...) -> ...:
    ...


# ====================================
# --> <Next group name>
# ====================================


def public_thing(...) -> ...:
    ...
```

### Banner format — exact

```
# ====================================
# --> Section name
# ====================================
```

- Three lines, each 38 characters wide.
- Lines 1 and 3 are `#` + one space + **36** `=` characters. No other indentation — the `=` run starts at column 3 and there are never leading spaces before it.
- Line 2 is `# --> ` + the name.
- The older variant `#` + 5 spaces + 32 `=` is **wrong**. If you meet it in a file you are organizing, rewrite it to the format above.
- Section names are short noun phrases, sentence case: `Helpers`, `Drawdown detection`, `Order sizing & capital`, `Order submission`, `Main workflow`.
- **Two blank lines above the banner, two blank lines below it.**

## The five rules

### 1. Group related functions

Functions that operate on the same concept or belong to the same step of the flow go under one banner. Judge by what the function is *about*, not by call order alone.

Typical grouping axes:
- **By pipeline stage** — detection → review → sizing → submission → orchestration
- **By subject** — everything touching the cooldown dict, everything touching orders
- **By role** — shared helpers vs. public API

Aim for 3–7 sections. One function alone under a banner is fine if it's genuinely its own concern (e.g. `Main workflow`). Ten sections of one function each means the grouping failed.

### 2. Helpers first, entry point last

- The `Helpers` section goes directly after the constants, at the top.
- The main orchestrating function goes in the last section, usually named `Main workflow`.
- Everything else sits in between, ordered to follow the flow of the module.

A helper used by only one section may live in that section instead of the top `Helpers` block — put it immediately above its first caller.

### 3. Underscore-prefix true file-private helpers

Rename a function to `_name` when **both** are true:
- It is not imported anywhere outside this file.
- It is not part of the file's intended public surface (not a job or script entry point, not re-exported through a package `__init__.py`'s `__all__`).

Verify before renaming — never guess:

```bash
rg -n '\bfunction_name\b' src scripts tests
```

If the only hits are inside the file being organized, it's private. Rename it and update every call site in the file.

The inverse also applies: if a `_name` function *is* imported elsewhere, drop the underscore or leave a note — a leading underscore that lies is worse than none.

Never prefix a folder or file name with `_`.

### 4. Whitespace and breathing room

Per the repo guidelines:
- Blank line after the initial declaration block in a function.
- Blank line between distinct steps inside a loop.
- Blank line before `return`.
- Two blank lines between top-level functions.
- Two blank lines above and below each banner.

### 5. Never delete user comments

Every pre-existing comment — inline notes, step markers (`# 1. ...`), `TODO`s, trailing design blocks — must survive the reorganization. Comments move *with* the code they describe.

If a comment becomes factually wrong because of the move (e.g. it references a renamed helper), fix only the wrong part in place. Do not reword, tidy, or "improve" comments.

## Procedure

1. **Read the whole file.** Do not organize what you haven't read end-to-end.
2. **Map it.** List every top-level function with a one-line note on what it does and what it belongs to.
3. **Check privacy.** Run one `rg` across `src scripts tests` for the names that look internal. Record which are imported elsewhere.
4. **Propose the sections.** Before editing, state the section names and which functions land where, plus any planned renames. Then proceed.
5. **Rewrite the file** in the new order with banners inserted, renames applied, and all comments carried over.
6. **Verify:**
   ```bash
   uvx ruff format <file> && uvx ruff check <file>
   uv run python -c "import <module.path>"
   uv run pytest
   ```
7. **Report** the section layout, the renames, and anything you noticed but deliberately left alone.

## Do not

- Change any function body's logic.
- Add, remove, or merge functions.
- Add abstractions, type hints, or error handling that wasn't asked for.
- Touch imports beyond what a rename requires (ruff handles ordering).
- Split the file into modules unless the user asks — but *do* say so if it's over 500 lines.
