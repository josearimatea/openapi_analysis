"""Optional HTTP adapter (FastAPI) — install with `openapi-analysis[api]`.

Mirrors the chat UI layout (api/routes, api/schemas). The chat UI mounts the
routers with app.include_router(...), so routes are not duplicated there. Routes
only call services/; no evaluation logic lives here.

routes/   rulesbank.py, openapi.py
schemas/  request DTOs (responses reuse the reports from openapi_analysis.schemas)
"""
