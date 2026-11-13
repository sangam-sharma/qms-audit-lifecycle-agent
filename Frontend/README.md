# QMS Frontend

The QMS dashboard calls Django for normal audit workflows. The QMS dashboard's **AI audit analysis** section calls the separate, read-only agent service.

Set `VITE_API_URL` and `VITE_AGENT_API_BASE_URL` in a local `Frontend/.env` file (see `.env.example`). `VITE_AGENT_API_BASE_URL` is the agent origin, such as `http://127.0.0.1:8080`; the frontend appends `/api/tasks/execute`.

Run Django and the agent with `QMS_DATA_PROVIDER=django` and `QMS_API_BASE_URL=http://127.0.0.1:8000/api/`. The frontend sends the current Django access JWT to the agent as a bearer token. The agent validates it with Django and only reads records authorized for that user. Configure the agent's `AGENT_CORS_ORIGINS` to the exact browser origin(s) used by the frontend. Local Vite origins are allowed by default.

The AI section requests a portfolio analysis only when the user clicks its button. Results are displayed in the current page session and are not persisted. The agent cannot create or update QMS records.
