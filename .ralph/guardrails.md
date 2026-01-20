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
