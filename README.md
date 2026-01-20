# ralph-sandbox

Daytona-backed Ralph runner + dashboard starter layout.

## What this repo provides

- A starter directory layout for a Ralph-style runner and dashboard.
- Copy/paste templates for task specs, guardrails, and diagnostics.
- A LiteLLM model profile configuration sample.
- Docker and docker-compose placeholders for local dashboard runs.

## Quickstart (scaffold)

1. Copy `.env.example` to `.env` and fill in secrets.
2. Add your FastAPI app and frontend code under `app/`.
3. Adjust `config/models.yaml` for your preferred LiteLLM profiles.
4. Run `docker compose up` once Dockerfiles are implemented.

## Directory layout

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
  templates/
  static/
  tests/
  Dockerfile
  docker-compose.yml
  ralph_task.md
  .ralph/
    guardrails.md
    progress.md
    notes.md
    diagnostics.md
```

## Notes

This repo intentionally keeps the runner state inside the sandboxed repo as `.ralph/*` files, and uses `ralph_task.md` as the authoritative spec anchor.
