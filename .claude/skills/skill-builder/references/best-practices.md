# Skill Authoring Best Practices

Comprehensive guidelines for creating effective, efficient, and maintainable Agent Skills.

## Table of Contents
1. [Design Principles](#design-principles)
2. [Writing Effective Descriptions](#writing-effective-descriptions)
3. [Structuring Instructions](#structuring-instructions)
4. [Progressive Disclosure](#progressive-disclosure)
5. [Token Optimization](#token-optimization)
6. [Testing and Iteration](#testing-and-iteration)
7. [Security Considerations](#security-considerations)
8. [Cross-Model Compatibility](#cross-model-compatibility)

---

## Design Principles

### 1. Context Window is a Public Good
Skills share the context window with system prompts, conversation history, other skills, and user requests. Every token must justify its cost.

**Questions to ask:**
- Does Claude already know this?
- Is this explanation necessary?
- Could this be shorter without losing meaning?

### 2. Write for Agents, Not Humans
Skills are consumed by AI agents. Optimize for agent understanding:
- Clear, unambiguous instructions
- Explicit rather than implicit guidance
- Consistent formatting and terminology

### 3. Match Specificity to Task Fragility

| Task Type | Specificity Level | Approach |
|-----------|------------------|----------|
| High stakes (database migrations) | High | Exact sequences, specific commands |
| Standard workflows (code review) | Medium | Clear steps, some flexibility |
| Creative tasks (writing) | Low | General direction, trust agent judgment |

### 4. Progressive Disclosure
Load information only when needed:
1. Frontmatter tells agents WHEN to trigger
2. SKILL.md body tells agents WHAT to do
3. References provide HOW details on-demand

---

## Writing Effective Descriptions

The `description` field is the most important part of your skill. It determines when agents use your skill.

### Do's
- ✅ Include specific action verbs: "extract", "generate", "validate", "convert"
- ✅ Mention file types: "PDF", "Excel", "JSON", "Python"
- ✅ Include trigger phrases users would say
- ✅ Specify the problem being solved
- ✅ Keep under 200 characters for optimal matching

### Don'ts
- ❌ Use vague language: "helps with", "useful for", "various tasks"
- ❌ Assume context: "the usual process"
- ❌ Include implementation details
- ❌ Use technical jargon unless domain-specific

### Examples by Category

**Development Skills:**
```yaml
# Good
description: Reviews Python/JavaScript code for security vulnerabilities, PEP 8 compliance, and performance issues. Use when asked to review or analyze code quality.

# Bad
description: Code helper for various development tasks.
```

**Document Skills:**
```yaml
# Good
description: Extract text and tables from PDF files, fill forms, merge/split documents. Use when working with PDFs or document extraction.

# Bad
description: PDF operations and manipulation.
```

**Data Skills:**
```yaml
# Good
description: Query and analyze BigQuery datasets using company-specific schemas. Use for data analysis, reporting, or SQL query generation.

# Bad  
description: Database queries and data stuff.
```

---

## Structuring Instructions

### Use Imperative Form
Write instructions as commands, not suggestions:

```markdown
# Good
Extract the text content using pdfplumber.
Validate the output against the schema.
Return results in JSON format.

# Bad
You should extract the text content.
It would be good to validate the output.
Consider returning results in JSON.
```

### Organize by Task Type
Group instructions by what the user wants to accomplish:

```markdown
## Extracting Text
1. Open the PDF with pdfplumber
2. Iterate through pages
3. Extract text from each page
4. Combine and return results

## Filling Forms
1. Check if PDF has fillable fields
2. Map input data to field names
3. Fill fields using pypdf
4. Save the modified PDF
```

### Include Decision Trees for Complex Logic

```markdown
## Handling Different PDF Types

To process a PDF, first determine its type:

1. If the PDF has fillable form fields → See [Form Filling](#form-filling)
2. If the PDF is a scanned image → Use OCR processing
3. If the PDF has embedded text → Direct extraction with pdfplumber
4. If the PDF is encrypted → Request password or skip
```

### Provide Concrete Examples
Examples are more effective than explanations:

```markdown
## Example: Extracting Tables

Input: PDF with financial data
```python
import pdfplumber

with pdfplumber.open("report.pdf") as pdf:
    for page in pdf.pages:
        tables = page.extract_tables()
        for table in tables:
            # Process table data
```

Output: List of tables as nested lists
```

---

## Progressive Disclosure

### Level 1: Frontmatter (Always Loaded)
~100 tokens maximum. Contains only:
- `name`: Identifier
- `description`: When to trigger

### Level 2: SKILL.md Body (Loaded on Trigger)
<5000 tokens recommended. Contains:
- Quick start / overview
- Core instructions
- References to bundled files

### Level 3+: Bundled Files (Loaded on Demand)
Unlimited but keep individual files focused. Load only what's needed for the current task.

### Reference Pattern
Explicitly tell agents what files are available:

```markdown
## Additional Resources

For detailed information, reference these files:
- `references/api-documentation.md` - Complete API reference
- `references/error-codes.md` - Error handling guide
- `scripts/validate.py` - Input validation script
- `assets/template.json` - Output template

Load these files only when the specific information is needed.
```

---

## Token Optimization

### Measure Token Usage
Rough estimate: 4 characters ≈ 1 token

```python
def estimate_tokens(filepath):
    with open(filepath) as f:
        return len(f.read()) // 4

# Target: SKILL.md body < 5000 tokens (20,000 characters)
```

### Reduce Redundancy
- Don't repeat information Claude already knows
- Reference existing files instead of duplicating
- Use tables instead of verbose lists

### Split Large Content
If SKILL.md exceeds 500 lines:

1. Identify content that's not always needed
2. Move to reference files
3. Add clear pointers in SKILL.md

```markdown
# Before (in SKILL.md)
## Complete API Reference
[500 lines of API documentation]

# After (split)
## API Reference
For complete API documentation, see `references/api.md`.

Quick reference for common operations:
- `create()` - Create new resource
- `read()` - Retrieve resource
- `update()` - Modify resource
- `delete()` - Remove resource
```

### Optimize Scripts
Scripts execute without loading into context. Prefer:
- Running scripts over generating code
- Script output over script source
- External tools over in-context processing

---

## Testing and Iteration

### Development Workflow
1. **Draft** initial skill with minimal content
2. **Test** with representative tasks
3. **Observe** where the agent struggles
4. **Refine** based on observations
5. **Repeat** until reliable

### Testing Checklist
- [ ] Skill triggers on relevant queries
- [ ] Skill doesn't trigger on unrelated queries
- [ ] Instructions are followed correctly
- [ ] Scripts run without errors
- [ ] Output matches expectations
- [ ] Edge cases are handled

### Iterating with Claude
Ask Claude to help improve skills:

```
"When you used this skill, what information was missing?"
"What patterns did you notice that should be documented?"
"Where were the instructions unclear or ambiguous?"
"Did you encounter any edge cases not covered?"
```

### A/B Testing Approach
1. **Claude A**: Helps create/refine the skill
2. **Claude B**: Uses the skill on real tasks (fresh context)
3. **Observe**: Note where Claude B struggles
4. **Iterate**: Bring observations back to Claude A

---

## Security Considerations

### For Skill Authors
- Never embed secrets, API keys, or credentials
- Minimize PII in bundled files
- Use least-privilege access patterns
- Audit all scripts for security issues

### For Skill Users
- Only install skills from trusted sources
- Review SKILL.md and scripts before enabling
- Watch for unexpected network calls
- Monitor file access patterns

### Code Review Checklist
- [ ] No hardcoded credentials
- [ ] No unexpected network requests
- [ ] No file system access outside skill scope
- [ ] Dependencies are documented and audited
- [ ] Error handling doesn't leak sensitive info

---

## Cross-Model Compatibility

Skills may run on different Claude models (Opus, Sonnet, Haiku) or even other LLMs supporting the Agent Skills format.

### Writing Portable Skills
1. **Don't assume capabilities**: Test on target models
2. **Be explicit**: More capable models may not need detail, but less capable ones do
3. **Provide examples**: Helps all models understand intent
4. **Use standard formats**: JSON, Markdown, YAML

### Model-Specific Considerations

| Model | Consideration |
|-------|--------------|
| Opus | Can handle more implicit instructions, longer context |
| Sonnet | Good balance of capability and cost |
| Haiku | May need more explicit step-by-step guidance |

### Testing Across Models
If your skill will be used with multiple models:
1. Test with all target models
2. Find the "lowest common denominator" for instructions
3. Add detail that helps weaker models without hurting stronger ones
