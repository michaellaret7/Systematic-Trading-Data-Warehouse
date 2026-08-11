# Workflow Patterns

Patterns for implementing multi-step processes, conditional logic, and complex workflows in Agent Skills.

## Table of Contents
1. [Sequential Workflows](#sequential-workflows)
2. [Conditional Workflows](#conditional-workflows)
3. [Iterative Workflows](#iterative-workflows)
4. [Parallel Workflows](#parallel-workflows)
5. [Error Handling](#error-handling)
6. [User Interaction Points](#user-interaction-points)
7. [State Management](#state-management)

---

## Sequential Workflows

For processes that must be executed in order.

### Basic Pattern
```markdown
## Process Name

Execute these steps in order:

### Step 1: [Name]
[Instructions]

Expected output: [What should result]
Proceed to Step 2 when: [Condition]

### Step 2: [Name]
[Instructions]

Expected output: [What should result]
Proceed to Step 3 when: [Condition]

### Step 3: [Name]
[Instructions]

Complete when: [Final condition]
```

### Example: Database Migration
```markdown
## Database Migration Workflow

Execute these steps in order. Do not skip steps.

### Step 1: Create Backup
Run the backup script before any changes:
```bash
python scripts/backup_database.py --output backups/
```

Expected: backup file created at backups/backup_YYYYMMDD.sql
Proceed when: Backup file exists and is non-empty

### Step 2: Review Migration
Read the migration file and verify:
- [ ] No destructive operations without reversibility
- [ ] Indexes added for new foreign keys
- [ ] Data transformations are idempotent

Flag any issues before proceeding.

### Step 3: Run Migration (Staging)
Apply to staging environment first:
```bash
python manage.py migrate --database staging
```

Expected: Migration completes without errors
Proceed when: All tests pass on staging

### Step 4: Run Migration (Production)
Apply to production with monitoring:
```bash
python manage.py migrate --database production
```

Monitor for 15 minutes after completion.
```

---

## Conditional Workflows

For processes with branching logic based on conditions.

### Decision Tree Pattern
```markdown
## Process with Decisions

### Initial Assessment
Evaluate [condition criteria].

### Decision Point
Based on assessment:

**If [Condition A]:**
→ Proceed to Path A

**If [Condition B]:**
→ Proceed to Path B

**If [Condition C]:**
→ Proceed to Path C

**Otherwise:**
→ Request clarification from user

---

### Path A: [Name]
[Path A instructions]

### Path B: [Name]
[Path B instructions]

### Path C: [Name]
[Path C instructions]
```

### Example: File Processing Router
```markdown
## File Processing Router

### Step 1: Detect File Type
Examine the file to determine its type:
- Extension
- MIME type
- Magic bytes (first few bytes)

### Decision Point

**If PDF file:**
→ Use PDF extraction path

**If Image (PNG, JPG, GIF):**
→ Use image processing path

**If Spreadsheet (XLSX, CSV):**
→ Use tabular data path

**If Text/Code:**
→ Use text analysis path

**If Unknown:**
→ Ask user for clarification

---

### PDF Path
1. Check if scanned or native text
2. If scanned: Apply OCR
3. If native: Extract with pdfplumber
4. Return structured text

### Image Path
1. Determine if text extraction needed
2. If yes: Apply OCR
3. If no: Describe image content
4. Return appropriate output

### Spreadsheet Path
1. Load with pandas
2. Identify structure (headers, data types)
3. Provide summary statistics
4. Return DataFrame or summary
```

---

## Iterative Workflows

For processes that repeat until a condition is met.

### Loop Pattern
```markdown
## Iterative Process

### Initialize
Set up initial state:
- [Initial condition]
- [Counter/tracker]

### Iteration Loop
Repeat until [termination condition]:

1. [Action]
2. [Evaluate result]
3. [Update state]
4. [Check termination]

If max iterations reached without success:
→ [Fallback action]

### Finalize
After loop completion:
- [Cleanup actions]
- [Report results]
```

### Example: Retry with Backoff
```markdown
## API Request with Retry

### Initialize
```python
max_retries = 3
retry_delay = 1  # seconds
attempt = 0
```

### Retry Loop
Repeat while attempt < max_retries:

1. Make API request
2. If success (2xx): Return response
3. If rate limited (429): 
   - Wait for retry_delay * 2^attempt seconds
   - Increment attempt
4. If server error (5xx):
   - Wait for retry_delay seconds
   - Increment attempt
5. If client error (4xx): Return error (don't retry)

### On Max Retries Exceeded
- Log failure with all attempt details
- Return error with retry history
- Suggest manual intervention
```

---

## Parallel Workflows

For processes that can run concurrently.

### Fan-Out/Fan-In Pattern
```markdown
## Parallel Processing

### Step 1: Split Work
Divide input into independent chunks:
[Chunking logic]

### Step 2: Process in Parallel
For each chunk, execute independently:
[Processing logic]

Note: Each chunk must be independent (no shared state).

### Step 3: Merge Results
Combine results from all chunks:
[Merging logic]

Handle partial failures:
- If all succeed: Return combined result
- If some fail: Return partial result with errors
- If all fail: Return error summary
```

### Example: Multi-File Analysis
```markdown
## Analyze Multiple Files

### Step 1: List Files
Get all files matching criteria:
```python
files = glob.glob("**/*.py", recursive=True)
```

### Step 2: Analyze Each File
For each file (can be parallel):
1. Read file content
2. Run analysis (complexity, style, etc.)
3. Store results

```python
results = {}
for file in files:
    results[file] = analyze_file(file)
```

### Step 3: Aggregate Results
Combine individual analyses:
```python
summary = {
    "total_files": len(results),
    "total_lines": sum(r["lines"] for r in results.values()),
    "avg_complexity": mean(r["complexity"] for r in results.values()),
    "issues": [r["issues"] for r in results.values()],
}
```
```

---

## Error Handling

Patterns for graceful error handling in workflows.

### Try-Recover Pattern
```markdown
## Process with Error Handling

### Attempt Primary Path
Try to complete using the preferred method:
[Primary instructions]

### On Error: Fallback
If primary path fails:
1. Log the error with context
2. Attempt fallback method:
   [Fallback instructions]

### On Complete Failure
If all paths fail:
1. Preserve any partial results
2. Document what succeeded and what failed
3. Provide actionable error message
4. Suggest next steps for user
```

### Example: Data Import with Recovery
```markdown
## Import Data with Error Recovery

### Primary: Bulk Import
Attempt bulk import for performance:
```python
try:
    db.bulk_insert(records)
except BulkInsertError as e:
    # Fall back to individual inserts
```

### Fallback: Individual Insert
If bulk fails, try one at a time:
```python
succeeded = []
failed = []
for record in records:
    try:
        db.insert(record)
        succeeded.append(record)
    except InsertError as e:
        failed.append({"record": record, "error": str(e)})
```

### Report Results
Always report what happened:
```python
return {
    "total": len(records),
    "succeeded": len(succeeded),
    "failed": len(failed),
    "errors": failed
}
```
```

---

## User Interaction Points

Patterns for workflows requiring user input.

### Checkpoint Pattern
```markdown
## Workflow with Checkpoints

### Step 1: [Automated]
[Instructions that run without user input]

### CHECKPOINT: User Review Required
Before proceeding, present to user:
- Summary of completed work
- Proposed next actions
- Questions needing answers

Wait for user confirmation or input.

### Step 2: [Continues after user input]
[Instructions using user's response]
```

### Example: Code Refactoring with Approval
```markdown
## Refactoring Workflow

### Phase 1: Analysis (Automated)
1. Identify refactoring candidates
2. Assess risk level for each
3. Estimate effort

### CHECKPOINT: Review Plan
Present refactoring plan to user:

**Proposed Changes:**
| File | Change | Risk | Effort |
|------|--------|------|--------|
| [list each change] |

**Questions:**
- Proceed with all changes?
- Exclude any files?
- Additional changes needed?

Wait for user approval before proceeding.

### Phase 2: Implementation
For each approved change:
1. Create backup
2. Apply refactoring
3. Run tests
4. Report result

### CHECKPOINT: Final Review
Present completed changes for review:
- Diff of all modifications
- Test results
- Any issues encountered

User can approve, rollback, or request modifications.
```

---

## State Management

Patterns for tracking state across workflow steps.

### State Object Pattern
```markdown
## Stateful Workflow

### Initialize State
Create state object at workflow start:
```python
state = {
    "started_at": datetime.now(),
    "current_step": "init",
    "completed_steps": [],
    "data": {},
    "errors": []
}
```

### Step Execution
Each step updates state:
```python
def execute_step(state, step_name, action):
    state["current_step"] = step_name
    try:
        result = action()
        state["data"][step_name] = result
        state["completed_steps"].append(step_name)
    except Exception as e:
        state["errors"].append({"step": step_name, "error": str(e)})
    return state
```

### State Recovery
If interrupted, resume from last completed step:
```python
def resume_workflow(saved_state):
    for step in workflow_steps:
        if step not in saved_state["completed_steps"]:
            execute_step(saved_state, step, step_actions[step])
```
```

### Example: Multi-Stage Pipeline
```markdown
## Data Processing Pipeline

### Pipeline State
```python
pipeline_state = {
    "input_file": None,
    "stages": {
        "extract": {"status": "pending", "output": None},
        "transform": {"status": "pending", "output": None},
        "validate": {"status": "pending", "output": None},
        "load": {"status": "pending", "output": None}
    },
    "current_stage": None,
    "errors": []
}
```

### Stage: Extract
```python
pipeline_state["current_stage"] = "extract"
data = extract_from_source(pipeline_state["input_file"])
pipeline_state["stages"]["extract"] = {
    "status": "complete",
    "output": data,
    "record_count": len(data)
}
```

### Stage: Transform
Only runs if extract succeeded:
```python
if pipeline_state["stages"]["extract"]["status"] == "complete":
    pipeline_state["current_stage"] = "transform"
    transformed = transform_data(
        pipeline_state["stages"]["extract"]["output"]
    )
    pipeline_state["stages"]["transform"] = {
        "status": "complete",
        "output": transformed
    }
```

Continue pattern for validate and load stages.

### Pipeline Resume
If pipeline fails mid-way:
1. Check pipeline_state for last completed stage
2. Resume from next pending stage
3. Use outputs from completed stages
```
