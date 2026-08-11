# Common Skill Patterns

A collection of proven patterns for different types of Agent Skills, with complete examples.

## Table of Contents
1. [Task-Based Skills](#task-based-skills)
2. [Workflow Skills](#workflow-skills)
3. [Domain Expertise Skills](#domain-expertise-skills)
4. [Tool Integration Skills](#tool-integration-skills)
5. [Code Generation Skills](#code-generation-skills)
6. [Analysis Skills](#analysis-skills)
7. [Hybrid Patterns](#hybrid-patterns)

---

## Task-Based Skills

For specific, well-defined tasks with clear inputs and outputs.

### Characteristics
- Single purpose
- Clear trigger conditions
- Deterministic output format
- Often include scripts for automation

### Example: Commit Message Generator

```yaml
---
name: commit-message-generator
description: Generates clear, conventional commit messages from git diffs. Use when writing commit messages or reviewing staged changes.
---
```

```markdown
# Commit Message Generator

Generate clear, conventional commit messages following best practices.

## Instructions

1. Run `git diff --staged` to see changes
2. Analyze the diff to understand:
   - What files changed
   - What type of change (feature, fix, refactor, docs, test, chore)
   - The scope of changes
3. Generate a commit message following this format:

```
<type>(<scope>): <subject>

<body>

<footer>
```

## Commit Types
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation only
- `style`: Formatting, no code change
- `refactor`: Code change that neither fixes bug nor adds feature
- `test`: Adding or updating tests
- `chore`: Maintenance tasks

## Guidelines
- Subject line: max 50 characters, imperative mood, no period
- Body: Explain what and why, not how
- Wrap body at 72 characters

## Example

Given a diff that adds input validation to a user form:

```
feat(auth): add email validation to signup form

Add regex-based email validation to prevent invalid
email addresses during user registration.

- Validate email format on blur and submit
- Show inline error messages
- Prevent form submission with invalid email
```
```

---

## Workflow Skills

For multi-step processes with conditional logic and decision points.

### Characteristics
- Sequential or branching steps
- Multiple decision points
- May require user input at stages
- Often reference additional documentation

### Example: Code Review Workflow

```yaml
---
name: code-review-workflow
description: Comprehensive code review following security, performance, and maintainability best practices. Use when reviewing pull requests or code changes.
---
```

```markdown
# Code Review Workflow

Systematic code review covering security, performance, maintainability, and correctness.

## Review Process

### Phase 1: Overview (5 min)
1. Read the PR description and linked issues
2. Understand the intent of changes
3. Check if scope is appropriate (not too large)

### Phase 2: Security Review
Check for:
- [ ] Input validation on all user data
- [ ] SQL injection vulnerabilities (parameterized queries)
- [ ] XSS vulnerabilities (output encoding)
- [ ] Authentication/authorization checks
- [ ] Sensitive data exposure
- [ ] Secure dependencies (no known CVEs)

If security issues found → Flag as blocking, explain risk.

### Phase 3: Performance Review
Check for:
- [ ] N+1 query problems
- [ ] Unnecessary database calls
- [ ] Missing indexes on queried fields
- [ ] Large payload sizes
- [ ] Missing pagination
- [ ] Inefficient algorithms (O(n²) where O(n) possible)

If performance issues found → Suggest optimization, provide benchmark if possible.

### Phase 4: Code Quality
Check for:
- [ ] Clear naming (variables, functions, classes)
- [ ] Single responsibility principle
- [ ] DRY (Don't Repeat Yourself)
- [ ] Appropriate error handling
- [ ] Sufficient test coverage
- [ ] Documentation for complex logic

### Phase 5: Summary
Provide structured feedback:

```
## Summary
[Brief overview of changes]

## Approval Status
[Approved / Changes Requested / Needs Discussion]

## Required Changes
- [Blocking issue 1]
- [Blocking issue 2]

## Suggestions
- [Non-blocking improvement 1]
- [Non-blocking improvement 2]

## Positive Feedback
- [What was done well]
```
```

---

## Domain Expertise Skills

For specialized knowledge in a particular field or organization.

### Characteristics
- Deep domain knowledge
- Organization-specific schemas or terminology
- Often include reference documentation
- May require confidential information

### Example: Financial Analysis

```yaml
---
name: financial-analysis
description: Financial analysis and reporting using standard metrics. Use for quarterly reports, budget analysis, revenue projections, or financial modeling.
---
```

```markdown
# Financial Analysis Skill

Financial analysis, reporting, and projections using standard accounting metrics.

## Available Analyses

### Profitability Analysis
- Gross Profit Margin = (Revenue - COGS) / Revenue
- Operating Margin = Operating Income / Revenue  
- Net Profit Margin = Net Income / Revenue
- ROE = Net Income / Shareholders' Equity
- ROA = Net Income / Total Assets

### Liquidity Analysis
- Current Ratio = Current Assets / Current Liabilities
- Quick Ratio = (Current Assets - Inventory) / Current Liabilities
- Cash Ratio = Cash / Current Liabilities

### Efficiency Analysis
- Asset Turnover = Revenue / Average Total Assets
- Inventory Turnover = COGS / Average Inventory
- Receivables Turnover = Revenue / Average Receivables

### Growth Analysis
- YoY Growth = (Current - Prior) / Prior * 100
- CAGR = (Ending / Beginning)^(1/years) - 1

## Report Templates

For standard reports, see `references/report-templates.md`.

### Quarterly Report Structure
1. Executive Summary
2. Revenue Analysis (by segment, geography)
3. Expense Analysis
4. Profitability Metrics
5. Cash Flow Summary
6. Outlook and Guidance

## Data Sources

When analyzing financial data:
1. Verify data currency (date of figures)
2. Ensure consistent accounting periods
3. Note any restatements or one-time items
4. Adjust for non-GAAP items when comparing
```

---

## Tool Integration Skills

For working with specific tools, APIs, or file formats.

### Characteristics
- Specific tool or format expertise
- Often include utility scripts
- Clear input/output specifications
- Error handling for tool-specific issues

### Example: PDF Processing

```yaml
---
name: pdf-processing
description: Extract text and tables from PDF files, fill forms, merge/split documents. Use when working with PDF files or when the user mentions PDFs, forms, or document extraction.
---
```

```markdown
# PDF Processing Skill

Comprehensive PDF manipulation using Python libraries.

## Quick Start

```python
import pdfplumber

with pdfplumber.open("document.pdf") as pdf:
    text = ""
    for page in pdf.pages:
        text += page.extract_text()
```

## Operations

### Text Extraction
Use `pdfplumber` for text-heavy PDFs:
```python
import pdfplumber

def extract_text(pdf_path):
    with pdfplumber.open(pdf_path) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)
```

### Table Extraction
```python
def extract_tables(pdf_path):
    with pdfplumber.open(pdf_path) as pdf:
        tables = []
        for page in pdf.pages:
            tables.extend(page.extract_tables())
        return tables
```

### Form Filling
For PDFs with fillable fields, see `references/forms.md`.

Run `scripts/check_form_fields.py <pdf_path>` to detect fillable fields.

### Merge/Split
```python
from pypdf import PdfReader, PdfWriter

# Merge
def merge_pdfs(pdf_paths, output_path):
    writer = PdfWriter()
    for path in pdf_paths:
        reader = PdfReader(path)
        for page in reader.pages:
            writer.add_page(page)
    with open(output_path, "wb") as f:
        writer.write(f)

# Split
def split_pdf(pdf_path, page_ranges):
    reader = PdfReader(pdf_path)
    for i, (start, end) in enumerate(page_ranges):
        writer = PdfWriter()
        for page_num in range(start, end):
            writer.add_page(reader.pages[page_num])
        with open(f"split_{i}.pdf", "wb") as f:
            writer.write(f)
```

## Dependencies
- pdfplumber: Text and table extraction
- pypdf: Merging, splitting, form filling
- pdf2image: PDF to image conversion (requires poppler)

## Common Issues
- Scanned PDFs: Use OCR (pytesseract + pdf2image)
- Encrypted PDFs: Requires password
- Complex layouts: May need custom extraction logic
```

---

## Code Generation Skills

For generating boilerplate code or project scaffolding.

### Characteristics
- Template-based generation
- Customizable parameters
- Often include asset templates
- Follow language/framework conventions

### Example: React Component Generator

```yaml
---
name: react-component-generator
description: Generate React components with TypeScript, tests, and Storybook stories. Use when creating new React components or scaffolding frontend code.
---
```

```markdown
# React Component Generator

Generate production-ready React components with TypeScript, tests, and documentation.

## Component Structure

Generated components follow this structure:
```
components/
└── ComponentName/
    ├── ComponentName.tsx      # Main component
    ├── ComponentName.test.tsx # Unit tests
    ├── ComponentName.stories.tsx # Storybook
    ├── ComponentName.module.css  # Styles
    └── index.ts               # Barrel export
```

## Templates

### Functional Component
```tsx
import React from 'react';
import styles from './{{name}}.module.css';

interface {{name}}Props {
  // Define props here
}

export const {{name}}: React.FC<{{name}}Props> = (props) => {
  return (
    <div className={styles.container}>
      {/* Component content */}
    </div>
  );
};
```

### Test Template
```tsx
import { render, screen } from '@testing-library/react';
import { {{name}} } from './{{name}}';

describe('{{name}}', () => {
  it('renders without crashing', () => {
    render(<{{name}} />);
  });
});
```

See `assets/templates/` for complete templates.

## Usage

Specify:
1. Component name (PascalCase)
2. Props interface
3. Component type (functional/class)
4. Include tests? (default: yes)
5. Include Storybook? (default: yes)

## Conventions
- Use functional components by default
- Props interface named `{ComponentName}Props`
- CSS modules for styling
- Named exports (not default)
```

---

## Analysis Skills

For analyzing data, code, or documents and producing insights.

### Characteristics
- Input analysis and pattern recognition
- Structured output format
- Often include scoring or metrics
- May generate reports or visualizations

### Example: Codebase Analyzer

```yaml
---
name: codebase-analyzer
description: Analyze codebase structure, dependencies, complexity, and technical debt. Use when evaluating code quality, planning refactoring, or onboarding to a new project.
---
```

```markdown
# Codebase Analyzer

Analyze codebases for structure, complexity, dependencies, and technical debt.

## Analysis Categories

### 1. Structure Analysis
- Directory organization
- Module boundaries
- Entry points
- Configuration files

### 2. Dependency Analysis
- External dependencies (package.json, requirements.txt)
- Internal imports
- Circular dependencies
- Outdated packages

### 3. Complexity Metrics
- Lines of code by file/directory
- Cyclomatic complexity
- Function/method length
- Nesting depth

### 4. Technical Debt Indicators
- TODO/FIXME comments
- Duplicate code
- Dead code
- Missing tests
- Outdated patterns

## Output Format

```markdown
# Codebase Analysis Report

## Overview
- Language: [Primary language]
- Framework: [If applicable]
- Size: [LOC, files, directories]
- Last updated: [Most recent commit]

## Structure
[Directory tree with annotations]

## Dependencies
### Production
[List with versions, security status]

### Development
[List with versions]

### Issues
- [Outdated packages]
- [Security vulnerabilities]

## Code Quality
- Average complexity: [Score]
- Test coverage: [Percentage if available]
- Documentation: [Assessment]

## Technical Debt
[Prioritized list of issues with severity]

## Recommendations
1. [Priority 1 action]
2. [Priority 2 action]
3. [Priority 3 action]
```

## Running Analysis

For automated metrics, run:
```bash
python scripts/analyze_codebase.py <directory>
```
```

---

## Hybrid Patterns

Many effective skills combine multiple patterns. Most production skills combine at least 2-3 patterns.

### Example: Full-Stack Feature Builder
Combines: Task-based + Code Generation + Workflow

```yaml
---
name: fullstack-feature-builder
description: Build complete full-stack features with React frontend, Node.js backend, database migrations, and tests. Use when implementing new features end-to-end.
---
```

### Example: Incident Response
Combines: Workflow + Domain Expertise + Analysis

```yaml
---
name: incident-response
description: Guide incident response with runbooks, communication templates, and post-mortem analysis. Use during production incidents or when creating incident documentation.
---
```

### Combining Patterns Effectively
1. Identify the primary pattern (main purpose)
2. Add supporting patterns as needed
3. Keep the SKILL.md focused on the primary flow
4. Use reference files for supporting pattern details
