# MyFreeHosting1

## Render deployment

This project includes a lightweight health endpoint at `/health` and a GitHub Actions keep-alive workflow.

### Optional 10-minute keep-alive (Render Free)

The workflow at `.github/workflows/keep-render-alive.yml` sends an HTTP request to the app's `/health` endpoint every 10 minutes and can also be run manually from the GitHub Actions tab.

1. Open this repository's **Settings → Secrets and variables → Actions → Variables**.
2. Create a repository variable named `TARGET_URL`.
3. Set its value to the base URL of your deployed Render web service, for example `https://your-service.onrender.com` (do not add `/health`).
4. Open **Actions**, enable workflows if GitHub asks, and run **Keep Render Service Warm** once using **Run workflow** to test it.

The scheduled job is best-effort: GitHub may delay scheduled runs, so a request is not guaranteed at an exact minute. It can reduce idle spin-down when the scheduled requests arrive within Render's 15-minute inactivity window, but it cannot guarantee always-on availability or prevent platform restarts, monthly-hour limits, or service suspensions. Paid Render instances do not need this workaround.

### Health endpoint

- `GET /health` returns a small JSON health response and is used by Render and the keep-alive workflow.

## Important Render notes

Render Free web services can spin down after 15 minutes without inbound traffic. Their local filesystem is ephemeral, and free services can restart. Keep important user and bot data in an external persistent database or object storage rather than relying on local files.
