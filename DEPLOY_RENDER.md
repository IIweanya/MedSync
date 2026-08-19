# Deploying MedSync to Render

This document describes a minimal, secure way to deploy MedSync on Render and to enable automatic deploys from GitHub Actions.

1) Create a Render Web Service
   - In Render dashboard, create a new **Web Service** and connect your GitHub repository and the `main` branch.
   - Use the following build and start commands (or rely on `render.yaml`/`Procfile`):

     Build command:
     ```bash
     pip install -r requirements.txt && python manage.py collectstatic --noinput
     ```

     Start command:
     ```bash
     gunicorn medsync.wsgi --bind 0.0.0.0:$PORT
     ```

2) Create a Postgres database on Render
   - Create a new Managed Postgres instance (Starter plan is fine for small testing).
   - Copy the `DATABASE_URL` connection string and add it to your Web Service environment variables in Render.

3) Required environment variables (set in the Render service settings)
   - `SECRET_KEY` — a strong random string
   - `DEBUG` = `False`
   - `ALLOWED_HOSTS` = the Render hostname for your service (e.g. `example.onrender.com`)
   - `DATABASE_URL` — from the Render Postgres instance
   - Optional email SMTP settings: `EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL`, `SUPPORT_EMAIL`

4) Media storage
   - For persistent uploaded media, either attach a Persistent Disk to the web service, or configure S3-compatible object storage and a Django storage backend.

5) Run one-time maintenance commands
   - From Render's Console or SSH, run:
     ```bash
     python manage.py migrate
     python manage.py collectstatic --noinput
     ```

6) Automatic deploys via GitHub Actions
   - Create a **Deploy Hook** in your Render service (Service -> Manual Deploy -> Create Deploy Hook). Copy the hook URL.
   - In your GitHub repository, go to Settings -> Secrets -> Actions and add the secret `RENDER_DEPLOY_WEBHOOK` with the hook URL as the value.
   - The provided GitHub Actions workflow `.github/workflows/deploy-to-render.yml` will POST to this webhook after CI completes on `main`.

7) Security notes
   - Never commit `SECRET_KEY`, `.env` files, or credentials to the repo. Use Render environment variables and GitHub Secrets.
   - If secrets were committed previously, purge them from history (I can help with `git filter-repo`).

8) Optional: persistent media using Persistent Disk
   - In the Render service, add a Persistent Disk and update `MEDIA_ROOT` to match the mounted path. Alternatively use S3.

If you want, I can also:
- Create a GitHub Actions secret example script to set `RENDER_DEPLOY_WEBHOOK` via the GitHub CLI, or
- Add an automated migration step to the Render deploy hooks so `migrate` runs on each deploy.
