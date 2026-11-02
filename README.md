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


## DBByte object storage (bot files and runtime backups)

The application uses DBByte for persistent bot files. Firebase Authentication and Firestore are still used for login and app records (users, scripts, plans, and settings); do not remove the Firebase service-account or Firebase web-auth environment variables.

Create a private DBByte bucket (for example `cyber-bot-storage`) and an API key scoped to that bucket with **Read**, **Write**, and **Delete** permissions. Add these environment variables to Render:

- `DBBYTE_API_KEY`: DBByte API key (keep secret).
- `DBBYTE_BUCKET`: exact bucket slug, e.g. `cyber-bot-storage`.
- `DBBYTE_API_URL`: `https://api.dbbyte.com` (optional; this is the default).

The backend stores bot files as private objects, restores them before starting a bot, syncs changed runtime files, and deletes the bot's cloud objects when the bot is deleted. The admin storage monitor reads actual object sizes and counts from DBByte.

DBByte's current REST API has a 50 MB per-object upload limit. The website's normal upload limit is currently 20 MB. The free plan has usage caps, so monitor storage, bandwidth, and request usage in the DBByte dashboard. Never expose the API key in frontend JavaScript or share it in screenshots.


### Storage monitor capacity settings

- `DBBYTE_QUOTA_GB`: displayed DBByte allowance in GiB; defaults to `20`. The used bytes and object count are read from the bucket listing; the quota is a configured allowance and is not independently verified against DBByte billing.
- `RENDER_APP_STORAGE_QUOTA_MB`: app-managed upload/temp-file allowance shown in the Render card; defaults to `512`. The used value counts files under the application's upload directory, not every byte used by the Render host/container.
- The admin storage monitor refreshes automatically every 5 seconds.


## Bot deployment features

- Python requirements are installed with pip into that bot's local `.packages` directory before launch. Node dependencies are installed with `npm install`. Install output and startup errors are written to the bot log.
- The Create Bot page also supports pasting Python source, optional requirements, and environment variables as a JSON object.
- Approved Python bots can be edited from My Bots. Saving updates the DBByte copy; if the bot was running, the app restarts it.
- Bot logs refresh in the existing Live Log panel. Process exit codes are recorded and status changes to Stopped or Failed.
- Direct file upload supports `.py` and `.js` scripts only (20 MB maximum). ZIP upload and automatic archive extraction are disabled.

### Important execution isolation note

Render runs these bot processes on the same service/container as the website. This implementation does not provide a hardened per-customer OS/container sandbox. Keep user uploads behind admin approval, only run code you trust, and do not enable automatic approval for untrusted users. Do not put platform-wide secrets in a bot's environment; only supply credentials intended for that bot. Resource-heavy dependencies may exceed the available memory/disk.
### Upload and persistence order
-
-
- `.py`/`.js` uploads are first written to the Render runtime folder. Approved admin bots are launched in a background task; DBByte backup starts after launch. Pending uploads are backed up after local receipt so they survive while awaiting approval.
- DBByte backup no longer blocks the browser upload request. If the backup fails, the bot remains on Render and the failure is written to Render logs; check backup status before relying on a redeploy.
- Render's local filesystem is ephemeral: after a service restart/redeploy, bot source/session files must be restored from DBByte.
