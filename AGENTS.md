# AGENTS.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.


--- 





This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

FoodGuard is an intelligent food label analysis system for pre-packaged foods. It uses image detection, OCR, ingredient extraction, nutrition parsing, knowledge retrieval (RAG), and LLM reasoning to produce structured health reports with scoring, risk summaries, and personalized recommendations.

The project is a Chinese-language graduation design (毕业设计). All UI text, API descriptions, and documentation are in Chinese.

## Development Environment

- **Conda environment**: `foodguard-env` — always use `conda run -n foodguard-env` or activate it before running backend commands.
- **Windows development**: Celery auto-detects Windows and switches to `solo` pool mode. No manual override needed.
- **Skip startup checks**: Set `SKIP_STARTUP_CHECKS=true` in `.env` when doing frontend-backend integration without all external services running.

## Commands

### Backend (food-label-analyzer/)

```bash
# Install dependencies
conda run -n foodguard-env pip install -r requirements-dev.txt

# Run all tests
conda run -n foodguard-env python -m pytest

# Run specific test file
conda run -n foodguard-env python -m pytest tests/test_auth.py

# Run focused module tests
conda run -n foodguard-env python -m pytest tests/test_config.py tests/test_core_modules.py tests/test_infra_modules.py

# Database migration
conda run -n foodguard-env python -m alembic upgrade head

# Start API server
conda run -n foodguard-env uvicorn app.main:app --reload

# Start Celery worker
conda run -n foodguard-env celery -A app.tasks.celery_app.celery_app worker -Q analysis --loglevel=info

# Create new migration
conda run -n foodguard-env python -m alembic revision --autogenerate -m "description"
```

### Frontend (food-label-frontend/)

```bash
npm install
npm run dev          # Dev server at http://localhost:5173
npm test             # Vitest with jsdom
npm run lint         # ESLint
npm run build        # Production build (tsc + vite)
```

### Single test (frontend)

```bash
npx vitest run src/pages/Analyzing.test.tsx
```

## Architecture

### Monorepo Layout

```
food-label-analyzer/   FastAPI backend
food-label-frontend/   React frontend
train_yolo26s/         YOLO26-OBB nutrition-table detection — training scripts, custom model configs, ONNX export & tests (training runs/models excluded via .gitignore)
docs/                  Architecture deep-dive docs
```

### Backend — Layered FastAPI + Celery

The backend follows a strict three-layer pattern. Routes must not contain business logic.

- **API layer** (`app/api/v1/`): HTTP parameter handling, dependency injection, response serialization. Routes call services only.
- **Service layer** (`app/services/`): Business orchestration — auth, task lifecycle, report assembly, chat sessions.
- **Task/Worker layer** (`app/tasks/`, `app/workers/`): Celery tasks and external service adapters, fully decoupled from HTTP.

Key backend modules:
- `app/core/config.py`: Pydantic Settings, all config from `.env`
- `app/core/security.py`: JWT creation/verification, password hashing
- `app/core/metrics.py`: Prometheus instrumentation
- `app/db/session.py`: Async SQLAlchemy engine
- `app/db/redis.py`: Async Redis client
- `app/models/`: SQLAlchemy ORM models (User, AnalysisTask, Report, ReportConversation, etc.)
- `app/schemas/`: Pydantic request/response schemas
- `app/workers/extractor/`: Ingredient and nutrition extraction from OCR text, with rule configs and topic cleaning
- `app/workers/ocr/`: PaddleOCR remote API integration
- `scripts/`: ChromaDB rebuild, pipeline runner utilities

### Analysis Pipeline (the core business flow)

Triggered by image upload, runs asynchronously via Celery:

1. **Upload** → MinIO storage → create `AnalysisTask` → dispatch to Celery
2. **YOLO detection** (`workers/yolo_worker.py`) → locate nutrition table bbox; if found, crop table region + mask original
3. **OCR** (`workers/ocr_worker.py`) → parallel OCR (masked image + table crop) via PaddleOCR remote API, or single-pass if no table detected
4. **Extraction** (`workers/extractor/`) → parse nutrition table JSON + ingredient list from OCR text
5. **RAG** (`workers/rag_worker.py`) → Ollama embeddings → ChromaDB similarity search for additive safety data
6. **LLM** (`workers/llm_worker.py`) → DeepSeek generates health score, risk summary, and recommendations
7. **Persist** → save `Report` record, update task status to completed

Entry points: `app/tasks/analysis_task.py` → `app/tasks/analysis/` submodules (ocr_strategy, artifacts, persistence, ingredient_fallback)

### Frontend — React 19 + TypeScript

- **Routing**: Two layout groups — `AuthLayout` (login/register) and `AppLayout` (all authenticated pages). `AppLayout` enforces auth and onboarding redirect.
- **State**: Zustand (`src/store/auth.ts`) for auth/preferences. `@tanstack/react-query` for server state.
- **API client** (`src/api/client.ts`): Axios with JWT injection and 401 refresh token handling. Failed refresh triggers forced logout.
- **Chat** (`src/lib/report-chat.ts`): SSE streaming for report Q&A, with recovery logic for interrupted streams.
- **Lazy loading**: All page routes use `React.lazy` for code splitting.
- **Vite proxy**: `/api` → `http://127.0.0.1:8000` in dev mode.

## Key Conventions

- **Language**: Code comments, variable names, and API docs are in Chinese where user-facing; English for code identifiers.
- **API response envelope**: All responses use `ApiResponse[T]` wrapper with `code`, `message`, `data` fields (see `app/schemas/common.py`).
- **Path alias**: Frontend uses `@/` → `src/` (configured in `vite.config.ts` and `tsconfig.app.json`).
- **Migrations**: Alembic versions in `food-label-analyzer/alembic/versions/`. Always create migrations for model changes.
- **External service failures**: Workers record metrics and mark tasks as `failed` — no silent swallowing. Upload failures clean up MinIO objects.
- **Health endpoints**: `/health` (public), `/metrics` (Prometheus), `/api/v1/metrics` (auth-protected process snapshot).
- **Celery config**: `task_soft_time_limit=270`, `task_time_limit=300`, `worker_prefetch_multiplier=1`, `task_acks_late=True`.
- **Frontend test env**: Vitest with jsdom. Test files colocated with components/pages as `*.test.tsx`.

## Behavioral Guidelines (from AGENTS.md)

- State assumptions explicitly before implementing. Ask when uncertain.
- Minimum code that solves the problem — no speculative features or over-engineering.
- Touch only what you must — match existing style, don't refactor adjacent code.
- Every changed line should trace directly to the task request.
- Define verifiable success criteria before starting.
- Prefer skills, MCP tools, and web-searched documentation over writing code from scratch.
