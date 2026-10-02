# db-console

A small page for one database workload on Juno Orion: how to connect to it, and its backups.

It runs next to the database in the same pod, behind the Hubble sign-in, and reads the credentials the database generated on its own volume. One image serves every engine.

## Configuration

| Variable | Purpose |
|----------|---------|
| `ENGINE` | `mongodb`, `postgres`, `mysql`, `mariadb`, `redis` or `qdrant` |
| `WORKLOAD` | Workload name, shown as the page title |
| `HOST`, `PORT` | Where the database is reached inside the cluster |
| `DATABASE`, `APP_USER`, `ADMIN_USER` | Database and users shown in the connection strings |
| `CREDENTIALS_DIR` | Directory holding `root_password`, `app_password` or `api_key`. Default `/store/credentials` |
| `BACKUPS_DIR` | Directory listed for download. Default `/store/backups` |
| `BASE_PATH` | Path the page is served under, for example `/project/mongodb/shopdb/` |

## Behaviour

- Serves the page, `/healthz`, and `backups/<file>` downloads under `BASE_PATH`. Nothing else
- Only GET and HEAD are accepted
- Backup names are checked against a strict pattern and must resolve inside `BACKUPS_DIR`, so nothing outside it can be read
- Responses are never cached
- Runs as uid 999 with a read-only filesystem

## Development

```bash
python -m unittest -v
```

Images are published to `ghcr.io/umer-jahangier/db-console` for amd64 and arm64. A tag `vX.Y.Z` publishes `X.Y.Z` and `X.Y`.
