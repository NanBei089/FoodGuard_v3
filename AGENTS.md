# Repository Guidelines

## Project Structure & Working Areas
This repository contains two active applications plus sample assets:

- `food-label-analyzer/`: FastAPI backend service.
- `food-label-frontend/`: React + TypeScript + Vite frontend.
- `images/`: sample food-label images for manual debugging and demos, not application source.

Backend layout inside `food-label-analyzer/`:

- `app/main.py`: FastAPI bootstrap, lifespan hooks, middleware, and `/health`.
- `app/api/v1/`: route modules for `auth`, `analysis`, `reports`, `users`, and `preferences`.
- `app/services/`: business logic for auth, reports, preferences, users, storage, scoring, and task orchestration.
- `app/tasks/`: Celery app setup and the analysis pipeline task entrypoint.
- `app/workers/`: OCR, YOLO, RAG, LLM, and extractor modules.
- `app/workers/extractor/prompts/`: prompt definitions used by extraction and health-analysis flows.
- `app/models/`, `app/schemas/`, `app/db/`: ORM, API contracts, and persistence helpers.
- `tests/`: pytest suite.
- `alembic/`: migrations.

Frontend layout inside `food-label-frontend/`:

- `src/App.tsx`: route registration.
- `src/pages/`: app screens including `auth/Login`, `auth/Register`, `Home`, `Onboarding`, `Analyzing`, `History`, `Profile`, and `ReportDetail`.
- `src/components/`: layout wrappers and reusable UI primitives.
- `src/api/client.ts`: Axios client, token injection, and refresh-token retry logic.
- `src/store/`: Zustand state.
- `src/lib/`: utilities, auth-session helpers, and API helper logic.
- `src/index.css`: Tailwind v4 theme tokens, global styles, and custom utilities.

## Current State
- This is not a backend-only scaffold anymore. The backend contains real implementations for auth, upload/task polling, reports, users, preferences, middleware, health checks, DB/Redis wiring, and much of the async analysis flow.
- The backend still depends on external services for full end-to-end behavior: Postgres, Redis, MinIO, Celery, ChromaDB, Ollama, PaddleOCR, YOLO model assets, and SMTP.
- The frontend is a standalone Vite app built with React 19, TypeScript, React Router 7, Zustand, Axios, and Tailwind CSS v4.
- Backend and frontend are tightly coupled through the `/api/v1` contract. Treat schema changes as full-stack changes unless proven otherwise.

## Build, Test, and Development Commands
Activate the shared backend environment first when doing Python work:

```powershell
conda activate foodguard-env
```

Backend commands:

```powershell
cd E:\GraduationProject\FoodGuard_v3\food-label-analyzer
pip install -r requirements-dev.txt
python -m pytest
python -m pytest tests/test_config.py tests/test_core_modules.py tests/test_infra_modules.py
$env:SKIP_STARTUP_CHECKS="true"; uvicorn app.main:app --reload
```

Frontend commands:

```powershell
cd E:\GraduationProject\FoodGuard_v3\food-label-frontend
npm install
npm run dev
npm run lint
npm run build
```

Important runtime behavior:

- Frontend dev server runs on `http://localhost:5173`.
- Vite proxies `/api` to `http://127.0.0.1:8000`.
- Frontend API base URL defaults to `/api/v1` unless `VITE_API_URL` is set.
- Backend startup checks connect to live dependencies unless `SKIP_STARTUP_CHECKS=true`.

## Coding Style & Architecture Conventions
Backend conventions:

- Use 4-space indentation.
- Keep `from __future__ import annotations` in Python modules.
- Add type hints on new public functions and methods.
- Keep route handlers thin; put reusable business logic in `app/services/`, `app/tasks/`, or `app/workers/`.
- Keep persistence concerns in `app/db/`, models, and service-layer code.
- Preserve the existing `ApiResponse[...]` response envelope unless the task explicitly changes the public API.

Frontend conventions:

- Use TypeScript function components.
- Prefer existing alias imports via `@/`.
- Reuse the shared `apiClient` and existing auth/session helpers instead of introducing ad-hoc fetch logic.
- Reuse the `cn` helper and existing UI primitives in `src/components/ui/`.
- Follow the current Tailwind and theme-token approach in `src/index.css` instead of introducing a second styling system.

For both apps, match surrounding style and do not reformat unrelated files.

## Testing & Verification
Backend uses `pytest`.

Important backend suites include:

- `tests/test_config.py`: settings and environment contract.
- `tests/test_core_modules.py`: errors, logging, security helpers, and health behavior.
- `tests/test_infra_modules.py`: DB session helpers, Redis helpers, router wiring, and dependencies.
- `tests/test_auth.py`: auth flows.
- `tests/test_analysis.py`: upload/task and analysis-related behavior.
- `tests/test_report.py`: report listing/detail/delete behavior.
- `tests/test_profile_preferences.py`: user profile and preference APIs.
- `tests/test_openapi_docs.py`: OpenAPI and docs behavior.
- `tests/test_doc02_data_layer.py` and `tests/test_doc05_workers.py`: deeper data-layer and worker coverage.

When changing:

- `app/core/config.py`: rerun `tests/test_config.py`.
- `app/main.py`, `app/dependencies.py`, `app/db/*`, or shared middleware/helpers: rerun `tests/test_core_modules.py` and `tests/test_infra_modules.py`.
- route modules, schemas, or API responses: rerun the relevant route tests and contract tests.
- analysis pipeline, extractor rules, prompt handling, or workers: rerun `tests/test_analysis.py`, `tests/test_doc05_workers.py`, and any affected domain tests.

Frontend currently has no dedicated test runner in `package.json`. For frontend-only changes, at minimum run:

- `npm run lint`
- `npm run build`

For API contract changes, verify both backend tests and frontend consumers.

## Config, Assets, and Security
- Use `food-label-analyzer/.env.example` as the source-of-truth config contract.
- Never commit live credentials for Postgres, Redis, MinIO, PaddleOCR, DeepSeek, SMTP, or Sentry.
- Default runtime asset paths include `./chroma_data` and `./models_store/yolo/yolo26s.onnx`. Do not casually rewrite vector stores, model binaries, or `.env`.
- `images/` is for sample inputs and manual validation. Avoid destructive edits there unless explicitly requested.
- If startup checks are enabled, expect live connectivity to Postgres, Redis, MinIO, ChromaDB, Ollama, and the OCR endpoint.

## Agent Workflow
- Read both backend and frontend code before changing shared behavior. Most user-visible features cross the API boundary.
- Before changing an API shape, inspect backend schemas/routes and frontend pages/types/client usage in the same pass.
- When changing extraction logic, OCR semantics, scoring, or health-analysis wording, inspect `app/workers/extractor/`, prompt files, `app/services/score_calculator.py`, and the corresponding tests first.
- Prefer focused edits over wide refactors. The current directory layout is already wired into tests, imports, and app startup.
- When library behavior is version-sensitive, verify against current official documentation for FastAPI, SQLAlchemy, Celery, Vite, React Router, Tailwind, ChromaDB, MinIO, PaddleOCR, and related dependencies before finalizing implementation.

## Commit & PR Guidelines
Use Conventional Commit style, for example:

- `feat(frontend): add report detail loading state`
- `fix(api): guard refresh token replay`
- `test(analysis): cover celery enqueue failure path`
- `docs: refresh repository agent guide`

Repository Git workflow:

- After changing tracked project files, create a local commit before handing work back unless the user explicitly says not to commit yet.
- Treat a completed local commit as the default stopping point. Do not push or upload to GitHub unless the user explicitly asks for it.
- Keep `SKILLS/` local-only. Ensure it stays ignored, never stage it, and never include it in a push.

PR descriptions should state:

- which app changed: `backend`, `frontend`, or `fullstack`
- whether `.env.example`, runtime assets, or external services are affected
- which verification commands were run
