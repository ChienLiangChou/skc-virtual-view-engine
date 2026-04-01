# SKC Virtual View Engine

Standalone Streamlit project for the Toronto condo virtual viewing tool.

## Run locally

```bash
export GOOGLE_TILES_API_KEY="your-google-maps-api-key"
export SKC_ADMIN_CODE="your-admin-code"
export DATABASE_URL="postgresql://username:password@hostname:5432/database?sslmode=require"
streamlit run app.py
```

If `DATABASE_URL` is set, customer status and usage events are stored in Postgres.
If `DATABASE_URL` is missing or unavailable, the app falls back to local JSON files in `data/`.

## Temporary public share link for the MVP

This project is still a Streamlit app, so the fastest way to share it with clients is to keep it running on your Mac and publish a temporary public URL through Cloudflare Tunnel.

```bash
cd "/Users/kevinchou/Documents/New project"
export GOOGLE_TILES_API_KEY="your-google-maps-api-key"
export SKC_ADMIN_CODE="your-admin-code"
export DATABASE_URL="postgresql://username:password@hostname:5432/database?sslmode=require"
streamlit run app.py --server.port 8504
cloudflared tunnel --url http://127.0.0.1:8504
```

When the tunnel starts, it will print a public URL like:

```text
https://example-name.trycloudflare.com
```

Then you can share per-client links such as:

```text
https://example-name.trycloudflare.com/?customer_id=client-a
https://example-name.trycloudflare.com/?customer_id=client-b
```

Important limitations for this MVP:

- Your Mac must stay on and connected to the internet
- The tunnel URL changes when you restart Cloudflare Tunnel
- This is not a fixed production domain

## Required services

- Maps Static API
- Maps JavaScript API
- Geocoding API
- Elevation API
- Street View Static API

## Production deployment target

For a fixed public URL while keeping the app as Streamlit, the cleanest path is Streamlit Community Cloud:

1. Put this project in a GitHub repository
2. Deploy the repository in Streamlit Community Cloud
3. Set the app URL to a fixed `*.streamlit.app` subdomain
4. Add the secrets from `.streamlit/secrets.toml.example`

Required secrets:

- `GOOGLE_TILES_API_KEY`
- `SKC_ADMIN_CODE`
- `DATABASE_URL`

## Customer control

- Each client should use a stable `customer_id`
- Recommended `customer_id` patterns:
  - `client-a`
  - `zhangyan`
  - `plazamidtown-7f-demo`
- Use only lowercase letters, numbers, `-`, and `_`
- Do not change the same client's `customer_id` between sessions or their usage history will split
- Usage is stored in Postgres when `DATABASE_URL` is configured
- Local fallback files are `data/usage_log.jsonl` and `data/customers.json`
- The admin panel appears when `SKC_ADMIN_CODE` is set and entered correctly in the sidebar

## How to manage usage

1. Give each client a fixed link with their own `customer_id`
   Example:
   `https://skc-virtual-view-engine.streamlit.app/?customer_id=client-a`
2. Open the app yourself and enter your `Admin code`
3. Use the Admin Panel to review:
   - total events
   - preview events
   - blocked events
   - last seen time
4. Pause a client if needed; their shared link will still open, but the app will stop loading maps for them
5. Re-enable the client later from the same Admin Panel

## Example production links

```text
https://your-fixed-subdomain.streamlit.app/?customer_id=client-a
https://your-fixed-subdomain.streamlit.app/?customer_id=client-b
```

When a client opens a shared link that already contains `customer_id`, the app will lock that field so they do not accidentally change it and split their usage history.
