# SKC Virtual View Engine

Standalone Streamlit project for the Toronto condo virtual viewing tool.

## 如何使用這套系統

這個 repo 目前有兩個部分：

1. Streamlit 主系統
   用來輸入多倫多地址、樓層與方向，產出街景主圖、互動 Street View 與俯視比例圖。
2. Codex repo-local skills
   放在 `.agents/skills/`，用來讓 Codex 在這個 repo 內用固定格式工作。

### A. 怎麼使用看房主系統

1. 在終端機設定必要環境變數：

```bash
export GOOGLE_TILES_API_KEY="your-google-maps-api-key"
export SKC_ADMIN_CODE="your-admin-code"
export DATABASE_URL="postgresql://username:password@hostname:5432/database?sslmode=require"
```

2. 啟動系統：

```bash
streamlit run app.py
```

3. 打開瀏覽器後，依序操作：
   - 在 sidebar 輸入或確認 `customer_id`
   - 輸入客戶名稱
   - 輸入地址、樓層、面向等參數
   - 系統會產出街景主圖、互動地圖與高度資訊

4. 如果要分享給客戶，直接帶 `customer_id` 分享連結：

```text
https://your-app-url/?customer_id=client-a
```

這樣客戶打開後就會被綁定在自己的 `customer_id`，不會把 usage 記到別人名下。

### B. 你平常怎麼管理客戶

1. 自己打開系統，輸入 `Admin code`
2. 到 `Admin Panel` 看每個客戶的：
   - status
   - total events
   - preview events
   - blocked events
   - last seen
3. 如果某個客戶要停用，按 `暫停客戶`
4. 要恢復時，按 `啟用客戶`

補充：
- 如果有 `DATABASE_URL`，資料會進 Postgres
- 如果沒有 `DATABASE_URL`，資料會退回本機 `data/` 目錄
- `customer_id` 建議固定，不要同一個客戶一直改

### C. 怎麼在 Codex 裡使用 repo-local skills

目前這個 repo 內保留一個 repo-local skill：

- `.agents/skills/kevin-claude-style-orchestrator/SKILL.md`

使用方法對應的目錄如下：

```text
your-repo/
├── AGENTS.md
├── README.md
└── .agents/
    └── skills/
        └── kevin-claude-style-orchestrator/
            ├── SKILL.md
            └── agents/
                └── openai.yaml
```

各檔案用途：
- `AGENTS.md`
  repo 工作規則，定義這個專案裡做事的基本原則
- `README.md`
  人類看的使用說明，包含怎麼跑系統、怎麼用 skill、怎麼切換模式
- `.agents/skills/kevin-claude-style-orchestrator/SKILL.md`
  skill 本體內容，定義 Claude-style workflow
- `.agents/skills/kevin-claude-style-orchestrator/agents/openai.yaml`
  skill metadata，控制 UI 顯示與 `allow_implicit_invocation: false`

這個 skill 目前有三種開關方式：

1. 完全不用 skill
   直接正常使用 Codex，不要在 prompt 裡寫 `$kevin-claude-style-orchestrator`。
2. 手動用 Claude-style skill
   在 prompt 裡明確寫出 `$kevin-claude-style-orchestrator`。
3. 整個 skill 暫停
   在你本機的 `~/.codex/config.toml` 加上這段，讓這個 skill 整體停用：

```toml
[[skills.config]]
path = "/Users/kevinchou/Documents/New project/.agents/skills/kevin-claude-style-orchestrator/SKILL.md"
enabled = false
```

補充說明：
- repo 內的 `.agents/skills/kevin-claude-style-orchestrator/agents/openai.yaml`
  已經設定 `allow_implicit_invocation: false`
- 這代表它不會自動套用
- 所以你平常可以自由選擇：
  - 不用 skill，就正常和 Codex 對話
  - 要用 Claude-style workflow，再明確輸入 `$kevin-claude-style-orchestrator`

範例：

```text
Use $kevin-claude-style-orchestrator to break down this repo task, inspect the relevant files first, and make the smallest safe change.
```

Codex 會依這個 workflow 做事：
- 先定義 objective
- 分 facts / assumptions / unknowns
- 先看 context 再改
- 用最小安全變更
- 最後交付 validation、risks、next action

### D. 什麼時候用哪一個 skill

- `kevin-claude-style-orchestrator`
  適合多步驟工作、需求拆解、技術分析、穩健改動流程

不要混用情境：
- `kevin-claude-style-orchestrator` 不適合單純閒聊或超小修改

### E. 最短工作流程

如果你是要對外給客戶看：

1. 啟動 Streamlit
2. 建一個固定 `customer_id`
3. 產出專屬分享連結
4. 在 Admin Panel 追 usage 與控制啟停

如果你是要在 Codex 裡工作：

1. 開這個 repo
2. 先決定你現在是哪一種模式：
   - 正常 Codex：什麼都不用加
   - Claude-style：明確寫 `$kevin-claude-style-orchestrator`
   - 完全停用 skill：在 `~/.codex/config.toml` 設 `enabled = false`
3. 把任務目標、限制、相關檔案或背景寫清楚
4. 讓 Codex 依當前模式執行

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

## Daily monitoring

- GitHub Actions runs `.github/workflows/daily-healthcheck.yml`
- The workflow checks the deployed Streamlit app every day at 9:00 AM Toronto time
- It runs at both `13:00` and `14:00` UTC, then the script keeps only the real 9:00 AM Toronto run so daylight saving time does not shift the schedule
- On failure, GitHub Actions opens or updates a GitHub issue with the reason and uploads a screenshot artifact
- On recovery, the workflow closes the open failure issue automatically
