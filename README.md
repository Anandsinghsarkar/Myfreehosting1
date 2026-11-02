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


## Backblaze B2 object storage (bot files and runtime backups)

The application uses Backblaze B2 through its S3-compatible API for persistent bot files. Firebase Authentication and Firestore remain unchanged for login and application records (users, scripts, plans, and settings).

Create a private B2 bucket and an application key scoped to that bucket with **Read and Write** access. The key must also be able to list objects and delete objects/versions. Add these environment variables to Render:

- `B2_BUCKET_NAME`: exact bucket name (for this setup: `Myfreehosting`).
- `B2_ENDPOINT`: bucket endpoint, for this setup: `https://s3.us-east-005.backblazeb2.com`.
- `B2_REGION`: region, for this setup: `us-east-005`.
- `B2_KEY_ID`: Backblaze application key ID (keep secret).
- `B2_APPLICATION_KEY`: Backblaze application key/secret (keep secret).

The backend stores bot files as private objects, restores them before starting a bot, syncs changed runtime/session files periodically, and deletes all object versions for a bot when the bot is deleted. The admin storage monitor reads object-version sizes and counts from the bucket. It does not expose the private bucket to the browser.

Backblaze B2 uses S3 Signature Version 4. Do not use your Backblaze account password or master key; create a dedicated application key. Never expose credentials in frontend JavaScript or screenshots.

**Object Lock note:** the bucket screenshot showed Object Lock enabled. If a file version has active retention or a legal hold, Backblaze may refuse its deletion until that restriction expires or is removed by an authorized bucket administrator. The app will keep the bot record if it cannot verify cloud deletion.

### Storage monitor capacity settings

- `B2_QUOTA_GB`: displayed allowance in GiB; defaults to `10`. This is a display estimate, not provider billing telemetry.
- `B2_UPLOAD_WORKERS`: parallel file uploads; defaults to `4` (maximum `8`).
- `RENDER_APP_STORAGE_QUOTA_MB`: app-managed upload/temp-file allowance shown in the Render card; defaults to `512`. The used value counts files under the application's upload directory, not every byte used by the Render host/container.
- The admin storage monitor refreshes automatically every 5 seconds.
## Bot deployment features

- Python requirements are installed with pip into that bot's local `.packages` directory before launch. Node dependencies are installed with `npm install`. Install output and startup errors are written to the bot log.
- The Create Bot page also supports pasting Python source, optional requirements, and environment variables as a JSON object.
- Approved Python bots can be edited from My Bots. Saving updates the Backblaze B2 copy; if the bot was running, the app restarts it.
- Bot logs refresh in the existing Live Log panel. Process exit codes are recorded and status changes to Stopped or Failed.
- Direct file upload supports `.py` and `.js` scripts only (20 MB maximum). ZIP upload and automatic archive extraction are disabled.

### Important execution isolation note

Render runs these bot processes on the same service/container as the website. This implementation does not provide a hardened per-customer OS/container sandbox. Keep user uploads behind admin approval, only run code you trust, and do not enable automatic approval for untrusted users. Do not put platform-wide secrets in a bot's environment; only supply credentials intended for that bot. Resource-heavy dependencies may exceed the available memory/disk.
### Upload and persistence order
- `.py`/`.js` uploads are first written to the Render runtime folder. Approved bots are launched in a background task; Backblaze B2 backup starts after launch. Pending uploads are backed up after local receipt so they survive while awaiting approval.
- Backblaze B2 backup no longer blocks the browser upload request. If the backup fails, the bot remains on Render and the failure is written to Render logs; check backup status before relying on a redeploy.
- Render's local filesystem is ephemeral: after a service restart/redeploy, bot source/session files must be restored from Backblaze B2.
