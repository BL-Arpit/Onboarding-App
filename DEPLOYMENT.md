# Deploy the Onboarding App as one Vercel project

This repository uses Vercel Services to deploy the Vite frontend and FastAPI backend together under one Vercel project and one public domain. The backend is a Vercel Python Function (ASGI), **not a persistent Uvicorn process**. Vercel does not provide a single always-running Uvicorn machine.

## Project layout

- `frontend/`: React + Vite static frontend.
- `backend/`: FastAPI application, entrypoint `app.main:app`.
- `vercel.toml`: declares both services and routes `/api/*` to FastAPI; all other paths go to Vite.

## Deploy

1. Commit and push the repository root (the directory containing `vercel.toml`) to GitHub.
2. In Vercel, create/import **one** project from this repository.
3. Set the project Root Directory to the repository root (`./`), not `frontend` or `backend`.
4. Use the current Vercel CLI/Services support and deploy from the repository root: `vercel deploy --prod`. The Vercel Services configuration builds the two service roots.
5. The same deployment domain serves `/` (frontend) and `/api/...` (FastAPI). No `VITE_API_URL` is required; the frontend calls same-origin `/api` routes.

If the dashboard's import flow does not recognize `vercel.toml` Services, update the Vercel CLI and confirm Vercel Services is available for the project. Do not set the project root to `frontend/`.

## Local run

Install the Vercel CLI, then run `vercel dev` from the repository root. Vercel Services routes the frontend and backend through one local origin. This is not the same as one Uvicorn process.

## Important storage limitation

The backend currently writes employee JSON and generated Excel files to local disk (`DATA_DIR`, default `./data`). Vercel Functions have ephemeral local storage; files are not durable across invocations or deployments. Use a persistent database and object storage for employee records and uploaded documents before production use. Do not store real Aadhaar, PAN, bank, or confidential employee information without authentication, access controls, and secure storage.
