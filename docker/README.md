# Inspectra Docker Build

## Backend image
Build from project root:
```bash
docker build -f docker/backend/Dockerfile -t <registry>/inspectra-backend:latest .
```

## Frontend image (optional)
If you add a React frontend under `frontend/`, build it with:
```bash
docker build -f docker/frontend/Dockerfile -t <registry>/inspectra-frontend:latest .
```

## Push images
```bash
docker push <registry>/inspectra-backend:latest
# Optional if you have a separate React frontend image:
# docker push <registry>/inspectra-frontend:latest
```

## Notes
- The repository currently contains a Flask monolith that serves templates and static assets.
- `docker/backend/Dockerfile` builds the Flask backend and installs `gunicorn` and `psycopg2-binary`.
- `docker/frontend/Dockerfile` is optional and intended for a future React frontend.
