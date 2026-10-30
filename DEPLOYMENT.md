# Onboarding demo deployment

This repository is split into two hosted services:

- `frontend/`: Vite + React, deployed to Vercel with **Root Directory** set to `frontend`.
- `backend/`: FastAPI, deployed to Render using the root `render.yaml` blueprint.

## Vercel settings

- Framework preset: Vite
- Root directory: `frontend`
- Build command: `npm run build`
- Output directory: `dist`
- Environment variable: `VITE_API_URL=https://<your-render-service>.onrender.com`

Redeploy the frontend after setting `VITE_API_URL`.

## Render settings

Create the service from the repository using `render.yaml`. After the Vercel domain exists, set `CORS_ORIGINS` to the exact Vercel production origin (for example `https://your-project.vercel.app`, without a trailing slash), then redeploy the backend.

Health check: `/api/health`.

## Demo-only warning

This is an unauthenticated demonstration app. Do not upload real employee information, identity documents, bank details, or confidential files. The backend uses local filesystem storage; the Render free service filesystem is ephemeral and demo records can be lost on restart/redeploy. Do not use this deployment for production or real employee onboarding.

The original archive included local virtual environments, Node dependencies, environment files, and runtime employee data. Those are excluded from this deployment repository. Only source code, tests, templates, and deployment configuration are included.
