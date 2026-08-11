# Agent Skills Format Specification

This document defines the complete format specification for Agent Skills, following the open standard at agentskills.io.

## Table of Contents
1. [Directory Structure](#directory-structure)
2. [SKILL.md File Format](#skillmd-file-format)
3. [YAML Frontmatter Fields](#yaml-frontmatter-fields)
4. [Markdown Body](#markdown-body)
5. [Optional Directories](#optional-directories)
6. [Validation Rules](#validation-rules)
7. [Token Budgets](#token-budgets)

---

## Directory Structure

A skill is a directory containing at minimum a `SKILL.md` file:

```
skill-name/
├── SKILL.md              # Required - Entry point
├── LICENSE               # Recommended - License file
├── scripts/              # Optional - Executable code
│   ├── main.py
│   └── helpers/
├── references/           # Optional - Documentation
│   ├── api.md
│   └── examples.md
└── assets/               # Optional - Static files
    ├── templates/
    └── images/
```

### Directory Naming
- Use lowercase letters, numbers, and hyphens
- Maximum 64 characters
- No spaces or special characters
- Should match the skill name in frontmatter

---

## SKILL.md File Format

The SKILL.md file combines YAML frontmatter with Markdown content:

```markdown
---
name: skill-name
description: What the skill does and when to use it.
license: Apache-2.0
metadata:
  author: author-name
  version: "1.0"
  tags: ["tag1", "tag2"]
---

# Skill Title

Markdown content with instructions, examples, and guidance.
```

### Critical Formatting Rules
1. YAML frontmatter MUST start on line 1 (no blank lines before `---`)
2. Frontmatter MUST end with `---` before Markdown content
3. Use spaces for indentation in YAML (not tabs)
4. Include a blank line after the closing `---` before Markdown

---

## YAML Frontmatter Fields

### Required Fields

#### `name` (string, required)
Human-readable identifier for the skill.

**Validation:**
- Maximum 64 characters
- Lowercase letters, numbers, and hyphens only
- Must not start or end with a hyphen
- No XML tags or reserved words
- Non-empty

**Examples:**
```yaml
name: pdf-processing        # Good
name: code-review          # Good
name: My Cool Skill        # Bad - uppercase and spaces
name: skill_with_underscores  # Bad - underscores not allowed
```

#### `description` (string, required)
Explains what the skill does and when agents should use it.

**Validation:**
- Maximum 1024 characters
- Non-empty
- No XML tags

**Best Practices:**
- Include specific trigger keywords users might say
- Mention file types, actions, or domains
- Be specific about use cases

**Examples:**
```yaml
# Good - specific, actionable, includes triggers
description: Extract text and tables from PDF files, fill forms, merge documents. Use when working with PDF files or when the user mentions PDFs, forms, or document extraction.

# Good - clear scope and triggers  
description: Reviews Python and JavaScript code for security vulnerabilities, PEP 8 compliance, and performance issues. Use when asked to review code or analyze code quality.

# Bad - too vague
description: Helps with documents.

# Bad - no trigger information
description: A useful skill for various tasks.
```

### Optional Fields

#### `license` (string, optional)
License name or reference to a bundled license file.

```yaml
license: Apache-2.0
license: MIT
license: ./LICENSE.txt
```

#### `metadata` (object, optional)
Additional metadata for organization and discovery.

```yaml
metadata:
  author: anthropic
  version: "1.0.0"
  tags: ["development", "testing"]
  category: "development"
  requires:
    - python >= 3.8
    - pandas
```

Common metadata fields:
- `author`: Creator name or organization
- `version`: Semantic version string
- `tags`: Array of categorization tags
- `category`: Primary category
- `requires`: Dependencies or requirements
- `created`: Creation date (ISO 8601)
- `updated`: Last update date (ISO 8601)

---

## Markdown Body

The Markdown body follows the YAML frontmatter and contains instructions for the agent.

### No Format Restrictions
Write whatever helps agents perform the task effectively. The content should be optimized for agent consumption, not human readability.

### Recommended Structure

```markdown
## Overview
Brief description of the skill's purpose (2-3 sentences).

## Quick Start
Minimal working example or fastest path to results.

## Instructions
Detailed step-by-step procedures organized by task type.

### Task Type 1
Steps for this task...

### Task Type 2  
Steps for this task...

## Examples
Concrete examples showing input → output.

## Edge Cases
How to handle unusual situations or errors.

## References
Links to bundled files:
- See `references/api.md` for API documentation
- Run `scripts/helper.py` for automated processing
```

### Writing Style
- Use imperative/infinitive form ("To accomplish X, do Y")
- Avoid second person ("You should...")
- Be concise - every token should provide value
- Include only information the agent doesn't already know

---

## Optional Directories

### scripts/
Contains executable code that agents can run.

**Best Practices:**
- Self-contained or clearly document dependencies
- Include usage examples in docstrings/comments
- Handle edge cases gracefully
- Tested before bundling

**Supported Languages:**
- Python (.py) - most common
- Bash (.sh)
- JavaScript/Node.js (.js)
- Language support depends on agent implementation

**Example structure:**
```
scripts/
├── main.py              # Primary script
├── validate.py          # Validation utilities
├── helpers/
│   ├── __init__.py
│   └── utils.py
└── README.md            # Script documentation
```

### references/
Contains documentation that agents can read when needed.

**Best Practices:**
- Keep individual files focused on one topic
- Include table of contents for files >100 lines
- Avoid deeply nested references (max 1 level from SKILL.md)
- Use clear, descriptive filenames

**Common reference files:**
- `api.md` - API documentation
- `schema.md` - Data schemas
- `examples.md` - Extended examples
- `troubleshooting.md` - Common issues and solutions
- Domain-specific files (finance.md, legal.md, etc.)

### assets/
Contains files used in output or processing.

**Use Cases:**
- Templates (HTML, JSON, YAML)
- Images and icons
- Fonts
- Configuration defaults
- Sample data files

**Best Practices:**
- Keep binary files minimal
- Prefer text formats when possible
- Organize by type or purpose

---

## Validation Rules

### Frontmatter Validation

| Field | Rule |
|-------|------|
| `name` | Required, ≤64 chars, lowercase alphanumeric + hyphens |
| `description` | Required, ≤1024 chars, non-empty |
| `license` | Optional, string |
| `metadata` | Optional, object |

### File Structure Validation
- SKILL.md must exist
- YAML must be valid and parse without errors
- All files referenced in SKILL.md should exist
- Scripts should have valid syntax

### Content Validation
- No malicious code patterns
- No credential exposure
- No unexpected network calls
- Dependencies should be documented

---

## Token Budgets

Optimal token allocation for efficient context usage:

| Level | Content | When Loaded | Recommended Size |
|-------|---------|-------------|------------------|
| 1 | Frontmatter (name + description) | Always | ~100 tokens |
| 2 | SKILL.md body | When triggered | <5,000 tokens |
| 3+ | Reference files | On-demand | Unlimited (per-file: <10k recommended) |

### Optimization Tips
1. **Frontmatter**: Concise but specific descriptions
2. **SKILL.md body**: Core instructions only, under 500 lines
3. **References**: Split large content into focused files
4. **Scripts**: Execute without loading when possible

### Calculating Token Count
Rough estimate: ~4 characters per token for English text.

```python
# Approximate token count
def estimate_tokens(text):
    return len(text) // 4
```

For precise counts, use the Anthropic tokenizer or tiktoken library.
