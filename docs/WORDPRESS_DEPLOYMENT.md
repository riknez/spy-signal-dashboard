# Deploying the SPY dashboard to argusclients.com/spy

Plugin: `argus-spy-dashboard` 0.1.0 (folder `wordpress/argus-spy-dashboard`, or
`argus-spy-dashboard-0.1.0.zip`). Tested on WordPress 7.1.3 (same as the live site),
PHP 8.3, MariaDB 10.11. Nothing in these steps costs money.

## 0. Before you start (one time)
- **Hosting:** cPanel login for argusclients.com (File Manager + Backup) and a WordPress
  Administrator login.
- **PC clock:** the endpoint rejects messages more than 5 minutes off. On the PC: Settings >
  Time & language > Date & time > *Set time automatically* = On, *Time zone* = (UTC-05:00)
  Eastern Time, then click **Sync now**. (Part of July's logs were 3 hours off.)
- **Optional but recommended:** if cPanel offers *WordPress Toolkit > Clone/Staging*
  (or Softaculous *Staging*), do steps 2–6 on that staging copy first. It is free on most plans.

## 1. Back up the live site
cPanel > **Backup** > *Download a Home Directory Backup* and *Download a MySQL Database Backup*
(or your host's one-click backup). Keep both files until the dashboard has run for a week.

## 2. Create the shared secret
On the PC, in PowerShell:
```
$b = New-Object byte[] 48; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); [Convert]::ToBase64String($b) -replace '[+/=]', ''
```
Copy the result (about 64 characters). It goes in exactly two places: `wp-config.php` (step 3)
and the PC's `.env` (step 7). Never paste it into chat, email, a page or the plugin settings.

## 3. Add the secret to wp-config.php
cPanel > **File Manager** > `public_html` (or the WordPress folder) > right-click
`wp-config.php` > **Edit**. Find the line
`/* That's all, stop editing! Happy publishing. */` and add **above** it:
```php
define( 'ARGUS_SPY_INGEST_SECRET', 'PASTE-THE-SECRET-HERE' );
```
Save. (Keep the existing file permissions; don't change anything else.)

## 4. Install the plugin
WP Admin > **Plugins > Add New Plugin > Upload Plugin** > choose
`argus-spy-dashboard-0.1.0.zip` > **Install Now** > **Activate**.
Activation creates three tables (`wp_argus_spy_minutes`, `wp_argus_spy_signals`,
`wp_argus_spy_journal`, using your table prefix) and gives Administrators the
`argus_spy_view` capability. It changes nothing else on the site.

## 5. Create the /spy page (private first)
WP Admin > **Pages > Add New Page**
- Title: `SPY` — slug (URL): `spy`
- Content: a **Shortcode** block containing `[argus_spy_dashboard]`
  (Elementor: use the *Shortcode* widget; page template *Elementor Full Width* gives the
  dashboard the full width)
- Visibility: **Private** → Publish.
Private pages are visible only to logged-in Administrators/Editors. Even after you make it
Public later, the plugin shows data only to users with `argus_spy_view`.

## 6. Hosting configuration
- **Caching / CDN** (LiteSpeed Cache, WP Rocket, Cloudflare, host cache): exclude
  `/spy/` and `/wp-json/argus-spy/*` from page caching. The plugin already sends
  `no-store`, but some caches ignore it.
- **Security plugins / firewall** (Wordfence, iThemes, ModSecurity): the PC sends
  `POST /wp-json/argus-spy/v1/ingest` every 3 s with headers `X-Argus-Spy-Timestamp` and
  `X-Argus-Spy-Signature` and no cookies. If the PC reports 403 or 429, allow that path
  (rate limit at least 30 requests/minute from your home IP). Do **not** disable REST API
  authentication site-wide.
- **HTTPS** must be on (it is). PHP 7.4+; `post_max_size` ≥ 1 MB (default is fine).
- WP-Cron and outgoing connections are **not** needed — the site only receives data.

## 7. Connect the PC
Add to the PC's `.env` (Notepad, one line each, no quotes):
```
ARGUS_SPY_INGEST_URL=https://argusclients.com/wp-json/argus-spy/v1/ingest
ARGUS_SPY_INGEST_SECRET=PASTE-THE-SAME-SECRET
```
Test one push: PowerShell in the project folder: `py worker\wp_push.py --once` → expect
`push ok`. Then run `worker\windows\4_restart_task.cmd` so the scheduled task picks up the
new settings (the pusher runs only while the market is open; outside hours a snapshot is
sent every 5 minutes).

## 8. Verify on the live site
1. Logged in as Administrator, open `https://argusclients.com/spy/` — expect **LIVE**
   during market hours (or **HISTORICAL** outside them), price updating every ~3 s.
2. In a private/incognito window (logged out), open the page — expect a 404 while the page
   is Private, or "This dashboard is private" once Public.
3. Logged out, open `https://argusclients.com/wp-json/argus-spy/v1/status` — expect
   `401` (`rest_forbidden`).
4. Phone: open the page logged in; no sideways scrolling.
5. Check the rest of the site (home, /leakit, /advok, /card, Little Lumi /app) still loads.

## 9. Giving someone else access (later)
WP Admin cannot grant custom capabilities without a role plugin; use WP-CLI
`wp user add-cap <username> argus_spy_view`, or ask me to add a small settings screen.
Remove with `wp user remove-cap <username> argus_spy_view`.

## Rollback (any time, ~2 minutes)
1. PC: delete the two `ARGUS_SPY_INGEST_*` lines from `.env` → run `4_restart_task.cmd`.
2. WP Admin > Plugins > **Deactivate** "Argus SPY Signal Dashboard" (data is kept).
3. Trash the `/spy` page.
4. Remove the `define( 'ARGUS_SPY_INGEST_SECRET', … )` line from `wp-config.php`.
Deleting the plugin from the Plugins screen also leaves its tables in place; drop the three
`*_argus_spy_*` tables manually only if you want the data gone.

## What was verified before this procedure (2026-11-11)
- 34 automated tests (scanner fixes, calendar, CALL/PUT mirror symmetry, non-blocking
  alerts, dashboard password/token rules, supervisor).
- 25/25 endpoint security checks on staging (`tests/wp_endpoint_security.py`): unsigned,
  wrong-secret, expired, future, tampered, replayed, oversized and malformed pushes rejected;
  anonymous and subscriber reads rejected; nonce required; secret never in responses.
- Browser tests: anonymous / subscriber / admin views, journal XSS, mobile width.
- Live on the Windows PC: scheduled task running the scanner on real Yahoo data,
  volume measured on 100% of rows, logs in `C:\SPYData`.
