# ralph-sandbox specification

Daytona-backed Ralph runner + Dashboard (no SSH) + PR output + model/provider swapping
Implementation spec + starter templates (copy/paste ready)

---

## 0) Executive summary

Build a system that runs Ralph-style iterative coding in isolated sandboxes (default: Daytona) with:
- Deliberate rotation: each iteration is a fresh LLM session (no long-lived chat context).
- Persistent state: only filesystem + git (anchor spec + append-only logs).
- No SSH: you monitor and intervene from a dashboard only.
- PR as the output: each run produces a branch and opens/updates a Pull Request.
- Provider/model swapping: via LiteLLM, default model profile zai/glm-4.7.
- Hard stop conditions: budgets + verifiable checks so runs don’t go infinite.
- Gutter detection: detect “going in circles” and auto-mitigate (rotate, model swap, doctor diagnostics, pause).

Dashboard must run both:
1. Locally (dev + daily use) while controlling remote Daytona sandboxes, and
2. Inside a Daytona sandbox (shareable preview link for demos), still controlling other run sandboxes.

---

## 1) Goals

MVP must:
- Run iterative “Ralph loops” with fresh context each iteration.
- Persist all run truth in repo:
- ralph_task.md + .ralph/* inside the repo in the sandbox.
- Never require SSH (no manual shell/terminal access).
- Support public + private repo access.
- Create and update a PR as the primary output.
- Make LLM providers/models easy to swap (LiteLLM).
- Enforce budgets and stop conditions.
- Detect and respond to “circling” (gutter).

---

## 2) Non-goals (MVP)
- Full multi-tenant auth/roles (single-user is fine).
- Full IDE in browser (basic file view/edit + diff + logs + spec/guardrails editor is enough).
- Distributed orchestration / k8s (single server process OK).

---

## 3) Core architecture

### 3.1 Components
1. Dashboard + API Server (FastAPI)

- Manages runs, sandboxes, credentials, PR creation, event streaming
- Runs locally or in a sandbox (demo mode)

2. Runner / Orchestrator

- Executes iterations and actions
- Concurrency via async tasks + worker pool

3. Sandbox provider layer

- DaytonaProvider (default)
- LocalProvider (for tests/integration without external creds)

4. SCM provider layer

- GitHubProvider (MVP)
- later: GitLab, Bitbucket, etc.

5. Model provider layer

- LiteLLM wrapper
- Config-driven model profiles (default zai/glm-4.7)

### 3.2 Ralph invariants (enforced)
- Each iteration is a fresh model call (no multi-hour context).
- “Memory” is only:
- ralph_task.md
- .ralph/guardrails.md
- .ralph/progress.md
- .ralph/logs + iteration artifacts
- repo files + git history
- If it isn’t written to a file, it doesn’t exist.
- DB is not the source of truth (only indexing/metadata).

---

## 4) Tech stack

Backend (MVP):
- Python 3.12
- FastAPI + Uvicorn
- WebSockets for live updates
- SQLite (upgradeable to Postgres)
- SQLModel or SQLAlchemy
- Pydantic for strict schemas
- LiteLLM for LLM provider abstraction

Frontend (MVP):
- Either:
- Server templates + HTMX, or
- Vite + React
- Must support live updates (WebSockets)

Packaging:
- Dockerfile for dashboard server
- docker-compose for local dev

---

## 5) Deployment modes (must support both)

### 5.1 Local dashboard mode
- docker compose up
- Dashboard runs on localhost, controls Daytona sandboxes via API
- Opens PRs via GitHub API
- No SSH

### 5.2 In-sandbox demo mode (Daytona)
- Script: scripts/deploy_daytona_demo.py
- creates a Daytona sandbox for the dashboard
- starts dashboard server inside it (port 8000)
- prints a shareable preview link + access token
- Demo dashboard can create additional run sandboxes

---

## 6) Sandbox provider abstraction

### 6.1 Interface: SandboxProvider

Required methods:
- create_sandbox(name, resources, image, env, labels) -> sandbox_id
- delete_sandbox(sandbox_id)
- start_sandbox(sandbox_id)
- stop_sandbox(sandbox_id)
- exec(sandbox_id, command, cwd, env, timeout_s) -> {exit_code, stdout, stderr, duration_ms}
- exec_stream(sandbox_id, command, cwd, env, timeout_s) -> stream_handle (optional)
- read_file(sandbox_id, path) -> bytes
- write_file(sandbox_id, path, bytes, mode=None, append=False)
- list_files(sandbox_id, path) -> [{name,is_dir,size,mod_time}]
- mkdirs(sandbox_id, path)
- git_clone(sandbox_id, url, path, branch=None, auth=None)
- git_status(sandbox_id, path) -> structured_or_raw
- git_diff(sandbox_id, path) -> patch_text
- git_checkout_new_branch(sandbox_id, path, branch_name)
- git_commit(sandbox_id, path, message) -> sha
- git_push(sandbox_id, path, remote, branch, auth) -> result
- get_preview_link(sandbox_id, port) -> url (optional; Daytona supports)

Implementation note:
- In this repo, the interface lives in `app/providers/sandbox/base.py` and shared types are in `app/models/sandbox.py`.

### 6.2 Implementations
- DaytonaProvider: uses Daytona SDK (FS/Git/Process/Preview)
- LocalProvider: uses subprocess + temp dirs for unit/integration tests (no preview link)

---

## 7) SCM provider abstraction (PR output)

### 7.1 Interface: ScmProvider
- validate_auth() -> ok
- get_repo_default_branch(repo) -> string
- open_pr(repo, head_branch, base_branch, title, body, draft=False, labels=[]) -> {url, number}
- update_pr(pr_number, title=None, body=None) -> ok
- comment_pr(pr_number, body) -> ok (optional)
- get_pr_checks(pr_number) -> status (optional)
- set_commit_status(sha, state, description, target_url=None) -> ok (optional)

Implementation note:
- In this repo, the interface lives in `app/providers/scm/base.py` and shared types are in `app/models/scm.py`.

### 7.2 GitHub auth modes (public + private)

Support at least:
- GitHub App (recommended for real usage)
- GitHub PAT (fast fallback for demos)

Secrets rules:
- Never write tokens into .ralph/
- Never log tokens (redact)
- Pass tokens to sandboxes via env vars for commands that need them
- Store tokens securely (MVP: local env + minimal storage; production: secrets manager)

---

## 8) Filesystem state (source of truth)

Inside the repo in the sandbox:

Required files
1. ralph_task.md (anchor file, required)

- YAML frontmatter (machine config)
- Markdown body (human spec + checkboxes)

2. .ralph/guardrails.md (append-only “signs”)
3. .ralph/progress.md (short status: done / next)
4. .ralph/errors.log (append-only; failures and summaries)
5. .ralph/activity.log (append-only; actions, commands, timings)

Optional but recommended
6. .ralph/notes.md (structured hints injected by dashboard)
7. .ralph/diagnostics.md (doctor reports)
8. .ralph/iterations/<N>/

- prompt.md
- response.json
- actions.jsonl
- git_diff.patch
- test_output.txt
- metrics.json
- pr_state.json

Resumability rule:
- A run can resume after server restart using only these files + repo state.

---

## 9) Iteration contract (strict JSON actions)

### 9.1 Model output schema (JSON only)

```
{
  "summary": "short summary for humans",
  "actions": [
    { "type": "run", "command": "npm test", "cwd": ".", "timeout_s": 900 },
    { "type": "patch", "path": "src/foo.ts", "patch": "unified diff..." },
    { "type": "write", "path": ".ralph/guardrails.md", "append": true, "content": "..." },
    { "type": "commit", "message": "Fix health endpoint", "paths": ["src/foo.ts"] },
    { "type": "rotate", "reason": "need fresh pass" },
    { "type": "pause", "reason": "needs human decision" },
    { "type": "stop_success", "reason": "all checks pass" },
    { "type": "stop_failure", "reason": "budget exceeded" }
  ],
  "claims": {
    "checkboxes_checked": ["M1.1", "M2.3"],
    "milestones_completed": ["M1"]
  }
}
```

### 9.2 Actions required in MVP
- run
- patch (unified diff applied to a single file)
- write (append or overwrite)
- commit
- rotate
- pause
- stop_success
- stop_failure

### 9.3 PR operations

Recommended: runner owns PR creation, not the model.

Runner policy:
- Model proposes commits and “ready to PR” state implicitly via passing tests and checked criteria.
- Runner pushes branch and opens/updates PR when:
- first successful push occurs, OR
- milestones progress enough, OR
- on completion.

(You can still allow a model action like request_pr_update later, but keep the MVP deterministic.)

---

## 10) Prompt construction (state hygiene)

Each iteration prompt includes (fixed order):
1. System instructions: Ralph loop, JSON only, follow schema, don’t hallucinate tool results.
2. ralph_task.md (full)
3. .ralph/guardrails.md (full or truncated)
4. .ralph/progress.md
5. .ralph/notes.md (if present)
6. Tail of .ralph/errors.log (last ~200 lines)
7. git status + brief diff summary (full diff written to file, not pasted)
8. tail/summarized last test_output.txt
9. budgets remaining + iteration count + recent loop_score history
10. the action schema + examples + constraints

Hard rules:
- Never paste huge logs; truncate and reference the file path.
- Keep prompt compact and deterministic.
- Prefer “run tests / inspect error output” over large rewrites.

---

## 11) Stop conditions / budgets

Configurable defaults (frontmatter):
- max_iterations: 30
- max_wall_time_minutes: 120
- max_cost_usd_estimate: 10
- max_consecutive_gutter: 3

Stop success when:
- all success checkboxes checked, AND
- test_command exits 0, AND
- PR is opened (or updated) with final changes

Stop failure when:
- any budget exceeded, OR
- gutter repeats beyond max_consecutive_gutter with no progress and no mitigation remaining

---

## 12) Gutter / circling detection (MVP)

Compute loop_score ∈ [0,1] each iteration:

A) Repeated failure signature (0.5)
- signature = (command, exit_code, normalized stderr first 2000 chars)
- if same signature repeats ≥ 3 times in last 5 iterations => +0.5

B) No-code-change stagnation (0.3)
- if git diff empty OR net change < X lines for ≥ 3 iterations => +0.3

C) File thrash (0.2)
- per file, track content hash per iteration
- detect ABAB flip pattern => +0.2

If loop_score >= 0.7 emit GUTTER.

Mitigation ladder (default):
1. auto-rotate
2. auto-switch to fallback model profile (if configured)
3. run “Doctor” diagnostics (strong model) to propose guardrails/spec improvements
4. if still stuck: pause run for human review

All signals written to:
- .ralph/activity.log
- .ralph/iterations/<N>/metrics.json

---

## 13) Steering philosophy (recommended)

### 13.1 Default mode: “Ralph-pure”

Humans do not run arbitrary shell commands.

Allowed interventions:
- edit ralph_task.md (clarify “done”, budgets)
- append to .ralph/guardrails.md (add signs)
- add structured note to .ralph/notes.md
- pause/resume/rotate/stop
- change model profile for next iteration

### 13.2 Optional modes

Mode A) AUTONOMOUS (default)
- Only persistent contract edits (task/guardrails/notes) + run controls

Mode B) GUIDED
- Adds “inject note” form (structured hints), still no shell

Mode C) DEBUG (power user)
- Allows running a restricted allowlist of commands from UI:
- rerun test_command
- lint/typecheck
- print selected logs
- Still no generic shell, still no SSH

### 13.3 Doctor diagnostics (strong model)

Trigger:
- loop_score high, OR
- every N iterations, OR
- manual “Diagnose” button

Doctor pass outputs:
- failure pattern summary
- 1–3 guardrails (signs)
- spec edits to reduce ambiguity / add verification
- model swap suggestion

Writes to .ralph/diagnostics.md

Apply policy:
- configurable: auto-apply or require 1-click approval

---

## 14) Concurrency + monorepo strategy

### 14.1 Default strategy (scales cleanly)
- 1 run = 1 sandbox = 1 clone = 1 branch = 1 PR
- No shared filesystem → no locking issues
- Conflicts handled at merge time (normal engineering)

### 14.2 Branch naming
- ralph/<task_id>/<slug>
- stable task_id used for resume
- if rerun, add suffix -v2

### 14.3 Monorepo overlap warnings (recommended)

Dashboard periodically checks:
- other open PR diffs (via GitHub API)
- file overlap between current run edits and existing open PRs
- if overlap high, warn and optionally pause

### 14.4 Optional: stacked diffs

Advanced option:
- set base_branch to another Ralph branch
- open PR against that base branch

### 14.5 CI-aware completion (recommended)
- After push, poll GitHub checks
- Only stop_success when CI passes (optional but valuable)

---

## 15) Default sandbox image / ecosystems

Default image includes:
- Node LTS + npm + pnpm
- Python 3.12 + pip (optionally uv)
- git, jq, curl, ripgrep

Per-run overrides:
- sandbox_image and sandbox_resources in frontmatter

Optional later:
- dependency snapshot caching after install

---

## 16) Dashboard requirements (no SSH)

### 16.1 Pages
1. Runs list

- create run: repo URL, base branch, provider, model profiles, budgets, sandbox resources/image, auth source
- show status, iteration count, loop_score, cost estimate, last activity, PR link

2. Run detail tabs

- Overview (controls + status + budgets + PR)
- Live logs (activity/errors)
- Spec editor (ralph_task.md + linter)
- Guardrails (append UI by default)
- Diff (current git diff + last iteration patch)
- Diagnostics (doctor output + apply button)
- Sandbox (id/state/resources + preview links)

### 16.2 API

REST:
- runs CRUD + pause/resume/rotate/stop
- set model profile (next iteration)
- read/write files by path
- trigger diagnostics

WebSocket:
- per-run event stream:
- iteration start/end
- action start/end
- log lines
- PR updated
- budget warnings
- gutter signals

---

## 17) Runner execution model
- Worker pool controls concurrency (configurable)
- Each run executes one iteration at a time
- Resume behavior:
- reload .ralph/ + repo state
- reconnect to sandbox if exists, else fail with actionable message

---

## 18) Spec authoring workflow (mandatory)

### 18.1 Checkboxes first

Write definition of done as checkboxes, then attach verification.

### 18.2 Spec-linter (block start if failing)

Before run starts, validate:
- ralph_task.md exists
- includes:
- test_command
- max_iterations
- max_wall_time_minutes
- at least one of max_cost_usd_estimate or max_tokens_total
- at least K checkboxes (default K=2)
- verification exists:
- either per-checkbox verify: command, OR
- a global verify_commands: list that covers all criteria

If linter fails: do not start; show fixes.

---

## 19) Enhanced “circling” roadmap (optional later)
- semantic similarity of plans via embeddings
- patch churn scoring
- test-output delta scoring (are we getting closer?)
- critic pass only when loop_score is high

---

## 20) Pricing notes (optional UI)

Dashboard may display:
- estimated LLM cost from LiteLLM token usage
- estimated compute cost from sandbox resources + elapsed time (best-effort)

---

## 21) Testing

Unit tests:
- parse frontmatter + checkboxes
- JSON schema validation + repair flow
- loop_score heuristics
- spec-linter
- secret redaction

Integration tests (no external creds):
- LocalProvider on fixture repo
- creates .ralph/
- performs patch + run
- triggers stop conditions

Optional smoke tests (with creds):
- Daytona create sandbox + clone + run no-op iteration
- GitHub open PR in test repo

---

## 22) Definition of done
- Local dashboard runs via docker compose
- LocalProvider run executes ≥ 1 iteration, writes .ralph/iterations/1/*
- Dashboard shows logs/diff and pause/resume/stop/rotate
- DaytonaProvider smoke test works with creds
- GitHubProvider opens PR for public + private in at least one auth mode
- Model profiles swappable; default zai/glm-4.7
- Gutter detection triggers and causes mitigation step (rotate/model swap/doctor/pause)

---

## Starter templates

### A) Starter ralph_task.md template (copy/paste)

```
---
task_id: "task-001"
repo_url: "https://github.com/ORG/REPO.git"
base_branch: "main"

# Branch strategy
target_branch_prefix: "ralph/task-001/"
target_branch_slug: "implement-foo"   # becomes ralph/task-001/implement-foo

# Sandbox
sandbox_provider: "daytona"           # daytona | local
sandbox_image: "ghcr.io/your-org/ralph-node-python:latest"  # optional override
sandbox_resources:
  vcpu: 2
  memory_gib: 4
  disk_gib: 20

# Model selection (via LiteLLM)
model_profile_default: "default-cheap"    # maps to config/models.yaml
model_profile_fallback: "strong-doctor"   # optional

# Budgets (hard stops)
max_iterations: 30
max_wall_time_minutes: 120
max_cost_usd_estimate: 10
max_consecutive_gutter: 3

# Verification
# If you can, keep a SINGLE gate that implies success (tests/lint/types)
test_command: "npm test"
# Optional extra verifiers (used by spec-linter + runner)
verify_commands:
  - "npm test"
  - "npm run lint"
  - "npm run typecheck"

# PR settings (runner-owned)
pr:
  draft: true
  labels: ["ralph"]
  title_template: "[Ralph] Implement Foo: task-001"
  body_template: |
    ## Summary
    Implements Foo per task-001.

    ## Verification
    - `npm test`
    - `npm run lint`
    - `npm run typecheck`

    ## Notes
    - Generated by ralph-sandbox.
---

# Task: Implement Foo (task-001)

## Context
Write 2–4 sentences about what this is and where in the repo it belongs.

## Constraints (non-negotiable)
- Do not rewrite unrelated modules.
- Keep diffs minimal and reviewable.
- Prefer small commits with clear messages.
- If a change could break public API, call it out in PR body.

## Success criteria (checkboxes)
> IMPORTANT: Every checkbox should be objectively verifiable.

### Milestone M1 — Behavior
- [ ] M1.1 Foo endpoint returns 200 for valid input  
  - verify: `node scripts/verify-foo.js` (or a curl command)
- [ ] M1.2 Foo endpoint returns 400 for invalid input  
  - verify: `node scripts/verify-foo-invalid.js`

### Milestone M2 — Quality gates
- [ ] M2.1 Unit tests added/updated for Foo  
  - verify: `npm test`
- [ ] M2.2 Lint passes  
  - verify: `npm run lint`
- [ ] M2.3 Types pass  
  - verify: `npm run typecheck`

## Implementation notes (optional but helpful)
- Files likely involved:
  - `src/foo/*`
  - `src/server.ts`
- Expected commands:
  - install: `npm ci`
  - tests: `npm test`

## “Definition of Done”
- All checkboxes above checked.
- `test_command` exits 0.
- PR opened and updated with final changes.
```

---

### B) Starter .ralph/guardrails.md template

```
# Ralph Guardrails (append-only)

## How to add a sign
When something breaks, append a sign:

### sign: <short name>
- trigger: <when this mistake tends to happen>
- instruction: <what to do instead>
- added_after: iteration <N>
- evidence: <error snippet or symptom>

---

### sign: keep diffs small
- trigger: when planning a broad refactor
- instruction: prefer minimal change sets; avoid unrelated rewrites; only touch files necessary for success criteria
- added_after: iteration 0
- evidence: project policy

### sign: always re-run tests after changing logic
- trigger: after modifying business logic
- instruction: run `test_command` before committing
- added_after: iteration 0
- evidence: reduces regressions

### sign: never edit secrets
- trigger: when encountering auth/config issues
- instruction: do not print or write tokens; use env vars only; redact logs
- added_after: iteration 0
- evidence: security
```

---

### C) Starter .ralph/progress.md template

```
# Progress

## Done
- (none yet)

## Next
- Parse repo, install deps, run baseline tests.
- Implement M1 criteria.
- Add/adjust tests and quality gates.

## Current blockers
- (none)

## Last known status
- iteration: 0
- test_command: not run
```

---

### D) Starter .ralph/notes.md template (for guided hints)

```
# Notes (optional)

## Allowed notes
Keep notes short, factual, and action-oriented. Prefer:
- clarifying requirements
- pointing to relevant files
- decisions (API shape, naming)
Avoid:
- speculative long plans
- contradicting the anchor spec

## Latest note
(none)
```

---

### E) Starter .ralph/diagnostics.md template (doctor output)

```
# Diagnostics (Doctor reports)

## Report format
- Observed failure patterns
- Likely root causes
- Suggested guardrails (signs)
- Suggested spec edits (tighten verification)
- Suggested model profile change (if relevant)

## Latest report
(none)
```

---

### F) Starter config/models.yaml template (LiteLLM profiles)

```
profiles:
  default-cheap:
    litellm_model: "zai/glm-4.7"
    max_output_tokens: 2048
    temperature: 0.2
    tags: ["default", "cheap"]

  strong-doctor:
    # choose a stronger model you trust for diagnosis (can be swapped)
    litellm_model: "openai/gpt-5"   # example; replace with your actual preference
    max_output_tokens: 2048
    temperature: 0.1
    tags: ["doctor", "strong"]

  codex-like:
    litellm_model: "openai/gpt-codex"  # example; replace as needed
    max_output_tokens: 2048
    temperature: 0.2
    tags: ["implementation"]
```

---

### G) Starter .env.example (secrets / config)

```
# Daytona
DAYTONA_API_KEY=...

# GitHub auth (choose one)
GITHUB_PAT=...
# or GitHub App creds
GITHUB_APP_ID=...
GITHUB_APP_PRIVATE_KEY_PEM=...
GITHUB_APP_INSTALLATION_ID=...

# LiteLLM / Providers
ZAI_API_KEY=...
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...

# App
RALPH_DB_URL=sqlite:///./ralph.db
RALPH_DEFAULT_PROVIDER=daytona
RALPH_DEFAULT_MODEL_PROFILE=default-cheap
RALPH_FALLBACK_MODEL_PROFILE=strong-doctor
```

---

### H) Starter directory layout (recommended)

```
ralph-sandbox/
  app/
    api/
    runner/
    providers/
      sandbox/
        daytona.py
        local.py
      scm/
        github.py
      llm/
        litellm_client.py
    web/
    models/
  config/
    models.yaml
  scripts/
    deploy_daytona_demo.py
  templates/ (if server-rendered)
  static/
  tests/
  Dockerfile
  docker-compose.yml
  README.md
```
