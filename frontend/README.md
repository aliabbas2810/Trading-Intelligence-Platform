# Frontend

React + Lightweight Charts visualization frontend for TIP.

## Local Development

Run the backend API first:

```powershell
py -3.12 -m backend.app --api --dry-run --host 127.0.0.1 --port 8000
```

Then start Vite:

```powershell
npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173
```

Environment overrides:

- `VITE_TIP_API_BASE_URL`, default `http://127.0.0.1:8000`
- `VITE_TIP_POLL_INTERVAL_MS`, default `0` for manual refresh only
