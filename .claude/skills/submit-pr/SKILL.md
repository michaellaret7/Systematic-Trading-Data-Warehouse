---
name: submit-pr
description: Run git diff, summarize changes, and submit a pull request to a target branch. Always authored as the user, never Claude.
---

## Overview

Automatically analyze the current branch's changes vs the base branch, generate a clear PR title and description, and submit the pull request via `gh`.

## Workflow

Follow these steps **in order**.

### Step 1: Determine the target branch

If the user specified a target branch, use that. Otherwise default to `dev`.

### Step 2: Gather context

Run these commands in parallel:

```bash
git status
```

```bash
git diff <target-branch>...HEAD
```

```bash
git log <target-branch>...HEAD --oneline
```

```bash
git rev-parse --abbrev-ref HEAD
```

Also check if the branch has a remote tracking branch and whether it needs to be pushed:

```bash
git rev-parse --abbrev-ref --symbolic-full-name @{u} 2>/dev/null
```

### Step 3: Analyze changes

From the diff and commit log, identify:
- What files were changed and why
- The nature of the changes (feature, fix, refactor, etc.)
- Any notable implementation details

### Step 4: Draft the PR

Create a concise PR title (under 70 characters) and a body using this format:

```markdown
## Summary
- <bullet point describing key change 1>
- <bullet point describing key change 2>
- ...

## Changes
- `path/to/file.py` — <what changed and why>
- ...
```

**CRITICAL RULES:**
- NEVER include "Co-Authored-By" lines
- NEVER include "Generated with Claude Code" or any AI attribution
- NEVER mention Claude in the PR title or body
- The PR must read as if the user wrote it themselves

### Step 5: Push and create the PR

If the branch is not pushed to remote, push it first:

```bash
git push -u origin <current-branch>
```

Then create the PR:

```bash
gh pr create --base <target-branch> --title "<title>" --body "$(cat <<'EOF'
<body content>
EOF
)"
```

### Step 6: Return the PR URL

Output the PR URL so the user can see it.
