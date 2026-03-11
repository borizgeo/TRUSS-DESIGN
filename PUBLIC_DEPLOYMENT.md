# Public Deployment

This app can be deployed publicly as a containerized Streamlit web service.

## Important constraints

- The app is currently open access. Anyone with the URL can use it.
- Saved designs are stored in a JSON file. Public deployment should use persistent disk storage.
- For stronger public security, put the app behind platform auth, reverse-proxy auth, or add app-level login later.

## Fastest deployment: Render

1. Push this folder to a Git repository.
2. Create a new Web Service on Render from that repository.
3. Render will detect the included Dockerfile or render.yaml.
4. Attach the persistent disk at `/data`.
5. Deploy.

The app uses these environment variables:

- `PORT`: port assigned by the host platform.
- `HSS_TRUSS_HOST`: bind address, defaults to `0.0.0.0`.
- `HSS_TRUSS_DB_FILE`: path to the JSON database file.

Recommended value for public hosting:

- `HSS_TRUSS_DB_FILE=/data/designs_database.json`

## Generic Docker deployment

Build:

```bash
docker build -t hss-truss-designer .
```

Run locally:

```bash
docker run -p 8501:8501 -e PORT=8501 -e HSS_TRUSS_DB_FILE=/data/designs_database.json -v hss_truss_data:/data hss-truss-designer
```

## Public exposure options

- Render
- Railway
- Fly.io
- Azure App Service for Containers
- Any VM with Docker and a reverse proxy

## Recommended next hardening steps

1. Add authentication.
2. Put the app behind HTTPS.
3. Add rate limiting if exposed broadly.
4. Replace the JSON file with a real shared database if multi-user write traffic becomes important.