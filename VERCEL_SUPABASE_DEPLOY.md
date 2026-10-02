# FloodAlert — Vercel + Supabase deployment

## 1) GitHub

Upload the contents of this package to a GitHub repository. Do not create an extra parent folder inside the repository.

```text
repository-root/
├── app.py
├── run.py
├── requirements.txt
├── vercel.json
├── .python-version
├── floodalert/
└── .env.example
```

## 2) Vercel

Import the GitHub repository into Vercel. Use the repository root as the Root Directory.

- Framework detection: automatic Flask/Python detection
- Build Command: leave blank/default
- Output Directory: leave blank/default

The root `app.py` exports `app`, which is the Flask instance created by `run.py`.

## 3) Environment Variables

In **Vercel → Project → Settings → Environment Variables**, add:

### Secret type

- `SECRET_KEY` — random long secret for Flask sessions
- `DATABASE_URL` — Supabase PostgreSQL connection string
- `TMD_ACCESS_TOKEN` — TMD Personal Access Token
- `CRON_SECRET` — random long secret for Vercel Cron

### Config type

- `TMD_WARNING_URL` — optional warning endpoint URL

For current Vercel UI, use **Secret** for passwords, API keys, and tokens; use **Config** for non-sensitive configuration values.

## 4) Supabase DATABASE_URL

Copy a PostgreSQL connection string from Supabase → Connect. For the Render/Vercel IPv4-friendly pooler setup used by this project, the URL can look like:

```text
postgresql://postgres.PROJECT-REF:PASSWORD@...pooler.supabase.com:5432/postgres
```

Do not put the real password into GitHub. If the password contains reserved URL characters, encode them before placing them in the URL.

## 5) Deploy

Deploy Production from Vercel. Vercel installs Python dependencies from `requirements.txt` and runs the Flask application through its Python runtime.

## 6) Cron

`vercel.json` contains:

```json
{
  "crons": [
    {
      "path": "/api/cron/refresh",
      "schedule": "0 0 * * *"
    }
  ]
}
```

Vercel sends `Authorization: Bearer <CRON_SECRET>` when invoking a protected Cron endpoint. On Hobby, the current minimum Cron frequency is once per day, so the scheduled refresh in this package is daily.

The long-lived APScheduler thread is disabled automatically when `VERCEL` is present, because Vercel is request-driven. Local/Render-style execution can still use the existing scheduler code.
