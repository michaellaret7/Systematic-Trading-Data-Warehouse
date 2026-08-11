---
name: skill-builder
description: Comprehensive guide for creating, structuring, validating, and packaging Agent Skills. Use when building new skills, improving existing skills, or understanding skill architecture. Covers YAML frontmatter, progressive disclosure, bundled resources, testing, and distribution.
license: Apache-2.0
metadata:
  author: anthropic-community
  version: "2.0"
  tags: ["meta", "development", "documentation"]
---

# Skill Builder

A comprehensive guide for creating effective Agent Skills that extend Claude's capabilities with specialized knowledge, workflows, and tools.

## Overview

Agent Skills are filesystem-based resources that provide Claude with domain-specific expertise. Skills use **progressive disclosure** to efficiently manage context:

1. **Level 1 - Metadata** (~100 tokens): `name` and `description` in YAML frontmatter - always loaded at startup
2. **Level 2 - Instructions** (<5k tokens): SKILL.md body - loaded when skill triggers
3. **Level 3+ - Resources** (unlimited): Bundled files in scripts/, references/, assets/ - loaded on-demand

## Skill Structure

```
skill-name/
├── SKILL.md                    # Required - Core instructions
├── scripts/                    # Optional - Executable code
│   ├── helper.py
│   └── validate.sh
├── references/                 # Optional - Documentation
│   ├── api-reference.md
│   └── examples.md
└── assets/                     # Optional - Templates, images, etc.
    ├── template.html
    └── logo.png
```

## Creating a New Skill

### Step 1: Define Purpose and Scope

Before writing any code, answer these questions:

- What specific problem does this skill solve?
- What tasks trigger this skill? (Be specific for the description)
- What procedural knowledge does Claude lack for this task?
- What reusable resources would help? (scripts, references, assets)

**Decision Framework:**
- Use **scripts/** when: Operations need deterministic reliability, code is repeatedly rewritten, or external tools are involved
- Use **references/** when: Domain knowledge needs to be loaded into context, documentation is too long for SKILL.md
- Use **assets/** when: Output requires templates, binary files, or static resources

### Step 2: Initialize the Skill

Run the initialization script from this skill's directory:

```bash
python scripts/init_skill.py <skill-name>
```

This creates `~/.claude/skills/<skill-name>/` by default (Claude Code's user-level skills folder).

Options:
- `--path <dir>` - Create skill in a different location (e.g., `--path ./project/.claude/skills`)
- `--resources scripts,references,assets` - Include specific resource directories
- `--examples` - Include example placeholder files

### Step 3: Write the YAML Frontmatter

The frontmatter is critical - it determines when Claude uses your skill.

```yaml
---
name: my-skill-name
description: Clear description of what the skill does and when to use it. Include trigger keywords and specific use cases.
license: Apache-2.0
metadata:
  author: your-name
  version: "1.0"
---
```

**Validation Rules:**
- `name`: Max 64 characters, lowercase letters/numbers/hyphens only, no XML tags
- `description`: Max 1024 characters, non-empty, no XML tags. Be specific about triggers.

**Good vs Bad Descriptions:**
- ❌ "Helps with code" (too vague)
- ✅ "Reviews Python and JavaScript code for security vulnerabilities, PEP 8 compliance, and performance issues"
- ❌ "PDF stuff" (no trigger words)
- ✅ "Extract text and tables from PDF files, fill forms, merge documents. Use when working with PDF files or when the user mentions PDFs, forms, or document extraction."

### Step 4: Write the Instructions

The SKILL.md body is loaded when the skill triggers. Keep it under 500 lines.

**Writing Guidelines:**
- Use imperative/infinitive form ("To accomplish X, do Y" not "You should do X")
- Include only information Claude doesn't already know
- Prefer concise examples over verbose explanations
- Reference bundled files explicitly so Claude knows they exist

**Recommended Sections:**
```markdown
## Overview
Brief purpose statement (2-3 sentences)

## Quick Start
Minimal working example

## Detailed Instructions
Step-by-step procedures for common tasks

## Common Patterns
Typical workflows and when to use them

## Edge Cases
How to handle unusual situations

## References
Links to bundled files for more detail
```

### Step 5: Add Bundled Resources

For detailed guidance on resource types, see:
- `references/specification.md` - Complete format specification
- `references/patterns.md` - Common skill patterns with examples
- `references/best-practices.md` - Writing and optimization tips

**scripts/** - Executable Code:
- Must be self-contained or clearly document dependencies
- Include usage examples in docstrings
- Handle edge cases gracefully
- Test before bundling

**references/** - Documentation:
- Keep files focused and single-purpose
- Include table of contents for files >100 lines
- Avoid deeply nested references (max 1 level from SKILL.md)

**assets/** - Static Files:
- Templates, images, fonts, configuration files
- Keep binary files minimal
- Use text formats when possible

### Step 6: Validate and Test

Run the validation script:

```bash
python scripts/validate_skill.py <skill-directory>
```

**Testing Checklist:**
- [ ] YAML frontmatter parses correctly
- [ ] Name follows naming conventions
- [ ] Description is clear and includes trigger keywords
- [ ] Instructions are under 500 lines
- [ ] All referenced files exist
- [ ] Scripts run without errors
- [ ] Skill triggers on relevant queries
- [ ] Skill doesn't trigger on unrelated queries

### Step 7: Package and Distribute

Create a distributable zip file:

```bash
cd <skill-directory>
zip -r skill-name.zip .
```

The zip file can be:
- Uploaded to Claude.ai via Settings > Features
- Used with Claude API via the skills parameter
- Installed in Claude Code at `~/.claude/skills/` or `.claude/skills/`

## Skill Design Patterns

### Pattern 1: Task-Based Skill
For specific, well-defined tasks with clear inputs/outputs.

```yaml
---
name: commit-message-generator
description: Generates clear commit messages from git diffs. Use when writing commit messages or reviewing staged changes.
---
```

### Pattern 2: Workflow Skill
For multi-step processes with conditional logic.

```yaml
---
name: code-review
description: Comprehensive code review workflow. Use when asked to review code for bugs, security, performance, and best practices.
---
```

See `references/patterns.md` for more patterns.

### Pattern 3: Domain Expertise Skill
For specialized knowledge in a particular field.

```yaml
---
name: financial-analysis
description: Financial analysis and reporting using company-specific schemas and calculations. Use for quarterly reports, budget analysis, or financial projections.
---
```

### Pattern 4: Tool Integration Skill
For working with specific tools, APIs, or file formats.

```yaml
---
name: pdf-processing
description: Extract text and tables from PDF files, fill forms, merge documents. Use when working with PDF files.
---
```

## Context Window Optimization

The context window is a shared resource. Optimize token usage:

1. **Frontmatter**: Keep descriptions concise but specific (~100 tokens)
2. **SKILL.md Body**: Stay under 5000 tokens, split into files if larger
3. **References**: Load on-demand, keep individual files focused
4. **Scripts**: Execute without loading into context when possible

**Decision Matrix:**
| Information Type | Location | Tokens Used |
|-----------------|----------|-------------|
| When to trigger | frontmatter | Always (~100) |
| Core instructions | SKILL.md body | When triggered (<5k) |
| Detailed docs | references/ | On-demand |
| Executable code | scripts/ | Only output (minimal) |
| Static resources | assets/ | Never (used in output) |

## Common Mistakes to Avoid

1. **Vague descriptions** - Claude won't know when to trigger the skill
2. **Including obvious information** - Claude already knows how to code, explain concepts, etc.
3. **Monolithic SKILL.md** - Split large content into reference files
4. **Untested scripts** - Always run scripts before bundling
5. **Missing file references** - Explicitly mention all bundled files in SKILL.md
6. **Wrong abstraction level** - Match specificity to task fragility

## Iterating on Skills

Skills improve through observation and iteration:

1. **Observe** Claude using the skill on real tasks
2. **Identify** where it struggles or goes off-track
3. **Refine** instructions based on observations
4. **Test** again with similar tasks

Ask Claude to help improve skills:
- "When you used this skill, what information was missing?"
- "What patterns did you notice that should be documented?"
- "Where were the instructions unclear?"

## Additional Resources

- `references/specification.md` - Complete SKILL.md format specification
- `references/best-practices.md` - Detailed authoring best practices
- `references/patterns.md` - Common patterns with full examples
- `references/workflows.md` - Multi-step workflow patterns
- `scripts/init_skill.py` - Initialize new skill directories
- `scripts/validate_skill.py` - Validate skill structure and format
- `assets/template-skill/` - Minimal skill template to copy
