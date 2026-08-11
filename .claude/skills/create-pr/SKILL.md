---
name: create-pr
description: Draft a ready-to-paste `gh pr create` command for the current branch into a target branch. Use when the user says "create pr into <branch>", "/create-pr <branch>", or asks for a PR command to copy into the terminal. Does NOT create the PR — it only prints the command.
---

## Overview

Take the target branch from the user's argument, have a lightweight agent read the diff,
and print a single `gh pr create` command the user can copy-paste. **Never run `gh pr create` yourself.**

## Workflow

### Step 1: Resolve inputs

Target branch = the user's argument. If none given, default to `dev`.

Run in parallel:

```bash
git rev-parse --abbrev-ref HEAD
```

```bash
git rev-parse --abbrev-ref --symbolic-full-name @{u} 2>/dev/null
```

### Step 2: Delegate the diff read

Spawn ONE agent with the Agent tool (`subagent_type: "general-purpose"`, `model: "haiku"`,
`run_in_background: false`) with this prompt, substituting the branches:

> Read-only task. Run `git diff <target>...HEAD --stat`, `git log <target>...HEAD --oneline`,
> and `git diff <target>...HEAD` (if the diff is over ~500 lines, read the `--stat` plus the
> first 400 lines only). Return exactly:
>
> TITLE: <one line, under 70 chars, imperative mood, no prefix like "PR:">
> BODY:
> ## Summary
> - <2-4 bullets on what changed and why>
>
> ## Changes
> - `path/to/file.py` — <what changed>
>
> Write as the repo owner. Never mention Claude, AI, or co-authorship. No other output.

### Step 3: Print the command

Output the push line only if the branch has no upstream, then the PR command in one block:

````
```powershell
git push -u origin <current-branch>

gh pr create --base <target> --head <current-branch> --title "<title>" --body @'
<body>
'@
```
````

The closing `'@` must be at column 0.

Add one sentence under the block naming the target branch and file count. Nothing else.

## Rules

- Never execute `gh pr create` — the user copies it.
- Never include "Co-Authored-By", "Generated with Claude Code", or any AI attribution.
- No emoji in the title or body.
