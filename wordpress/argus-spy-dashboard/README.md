# Argus SPY Signal Dashboard (WordPress plugin)

Private dashboard at a page containing `[argus_spy_dashboard]` (planned: /spy).
Receives signed pushes from the scanner PC; shows them only to logged-in users
with the `argus_spy_view` capability (Administrators get it on activation).

## Install (staging first)
1. Add to `wp-config.php` above "That's all, stop editing":
   `define( 'ARGUS_SPY_INGEST_SECRET', '<64 random characters>' );`
   Use the same value as `ARGUS_SPY_INGEST_SECRET` in the PC's `.env`.
2. Upload the `argus-spy-dashboard` folder to `wp-content/plugins/` and activate.
3. Create a page (slug `spy`, status Private or Published) with the shortcode
   `[argus_spy_dashboard]`. Anyone without access sees only a login/no-access message.
4. On the PC, set `ARGUS_SPY_INGEST_URL=https://<site>/wp-json/argus-spy/v1/ingest`
   and run `py worker\wp_push.py --once` — expect `push ok`.

## Security
- Ingest: HMAC-SHA256 over `timestamp.body`, 5-minute window, timestamps must not go
  backwards, 512 KB limit. The secret lives only in wp-config.php and .env.
- Reads: logged-in + capability + REST nonce. No market-data keys exist on the site.
- Page: noindex, no-store. All values rendered with textContent.
- Grant another user access: `wp user add-cap <user> argus_spy_view`.

## Data
Tables `{prefix}argus_spy_minutes` (one row per market minute), `_signals`
(CALL/PUT events + results, de-duplicated), `_journal` (per user). Latest snapshot
in option `argus_spy_latest` (not autoloaded). Deactivating keeps all data.
