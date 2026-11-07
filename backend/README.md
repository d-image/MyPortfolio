# Portfolio API

Install the backend dependencies and run the API from the repository root:

```powershell
python -m pip install -r backend\requirements.txt
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

You can also start it from the `backend` directory with:

```powershell
python main.py
```

This uses `APP_HOST` and `APP_PORT` when set, and defaults to `127.0.0.1:8000`.

The public API accepts `POST /api/contact` with JSON fields `name`, `email`, and `message`. It validates input, limits request size, checks browser origins and hosts, applies a per-client rate limit, and stores accepted submissions as JSON Lines. `GET /health` is available for health checks. Interactive API documentation is available at `/docs` only in development.

## Blog accounts

The blog supports email/password registration and login:

- `POST /api/auth/signup` accepts `{"email":"reader@example.com","display_name":"Reader","password":"at least 12 characters"}` and creates a session.
- `POST /api/auth/login` accepts `{"email":"reader@example.com","password":"your password"}` and creates a session.
- `GET /api/auth/me` returns the signed-in account.
- `POST /api/auth/logout` revokes the current session.
- `GET /api/posts` lists published posts.
- Signed-in users can `POST /api/posts`, `PUT /api/posts/{id}`, and `DELETE /api/posts/{id}`. New posts are published immediately; authors can only change or remove their own posts.

Passwords are stored as scrypt hashes. Session tokens are random, stored only as SHA-256 hashes, and expire after seven days. The browser receives the token only in an HttpOnly, SameSite=Lax cookie; the cookie is Secure in production. Signup, login, and logout require an exact allowed Origin and are rate limited. The React app uses same-origin `/api` requests; Vite proxies these requests to `127.0.0.1:8000` during development. For a separate production API origin, build the frontend with `VITE_API_BASE_URL` set and serve the frontend and API on the same site so the Lax session cookie can be sent.

Post titles, summaries, and plain-text content are validated and length-limited. Published content is rendered as text rather than trusted HTML. Email ownership is not verified, and password reset/account recovery is not implemented; add a verified email workflow before relying on accounts for valuable or privileged access.

Before production, set `APP_ENV=production`, `APP_ALLOWED_ORIGINS` to the exact HTTPS origin(s) of the website, and `APP_ALLOWED_HOSTS` to the API host name(s). Set `APP_AUTH_DATABASE_FILE` to a persistent, application-private SQLite path and protect its backups. SQLite and the in-memory rate limiters are intended for a single API instance; use a managed database and shared rate limiter before scaling across instances. Enable HTTPS at the ingress or TLS endpoint. Set `APP_FORCE_HTTPS=true` only when the ASGI app itself receives HTTPS requests; configure trusted proxy handling at the deployment boundary rather than trusting arbitrary forwarded headers.

The included rate limiters are process-local and are not shared across multiple workers or instances. Contact records contain personal data and are stored unencrypted in the configured local JSONL file; protect the storage volume and backups, restrict access to the application account, and configure retention appropriate to your privacy requirements. The default runtime directory is excluded from version control.

The API adds security headers to API responses. Configure equivalent HTTPS, HSTS, CSP, framing, and content-type protections on the static frontend host; this repository does not include a production hosting or reverse-proxy configuration. Keep frontend and API on the same site, and route `/api` to the backend.

Run the backend tests from the repository root:

```powershell
python -m unittest discover -s backend\tests -v
```
