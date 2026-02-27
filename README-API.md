# CloakBrowser API Server

Remote stealth browser control via HTTP API. Deploy on Docker/Coolify and automate anti-detect Chromium from any language or tool.

## Table of Contents

- [Quick Start](#quick-start)
- [Deploy to Coolify](#deploy-to-coolify)
- [Authentication](#authentication)
- [API Reference](#api-reference)
  - [System](#system)
  - [Sessions](#sessions)
  - [Pages](#pages)
  - [Actions](#actions)
- [Examples](#examples)
- [Configuration](#configuration)

---

## Quick Start

### Local Development

```bash
# 1. Copy env file
cp .env.example .env

# 2. Build and start
docker compose up --build

# 3. Open API docs
open http://localhost:8000/docs
```

### Test it works

```bash
# Health check
curl http://localhost:8000/health

# Create a session
curl -X POST http://localhost:8000/sessions

# Open a page
curl -X POST http://localhost:8000/sessions/{session_id}/pages

# Navigate
curl -X POST http://localhost:8000/sessions/{session_id}/pages/{page_id}/navigate \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'

# Take screenshot
curl -X POST http://localhost:8000/sessions/{session_id}/pages/{page_id}/screenshot/raw \
  --output screenshot.png

# Close session
curl -X DELETE http://localhost:8000/sessions/{session_id}
```

---

## Deploy to Coolify

### Option A: Docker Compose (Recommended)

1. In Coolify, create a new **Docker Compose** service
2. Point it to your Git repository
3. Set the compose file to `docker-compose.yml`
4. Add environment variables in Coolify dashboard:
   - `API_KEY` — your secret key
   - `MAX_SESSIONS` — max concurrent browsers (default: 10)
   - `SESSION_TTL` — idle timeout in seconds (default: 3600)
5. Set **Shared Memory** to at least `2GB` (required for Chromium)
6. Deploy!

### Option B: Single Dockerfile

1. In Coolify, create a new **Dockerfile** service
2. Set Dockerfile path to: `Dockerfile.api`
3. Set port to `8000`
4. Add environment variables
5. In **Advanced** settings, add:
   - Shared memory: `2gb`
   - Security option: `seccomp:unconfined`
6. Deploy!

### Important Coolify Settings

| Setting | Value | Why |
|---------|-------|-----|
| Shared Memory | `2048 MB` | Chromium crashes without enough `/dev/shm` |
| Security | `seccomp:unconfined` | Required for Chromium sandbox |
| Memory | `4 GB` minimum | Each browser session uses ~300-500MB |
| CPU | `2+` cores | Chromium is CPU-intensive |

---

## Authentication

Set the `API_KEY` environment variable to enable authentication.

```bash
# With API key
curl -H "X-API-Key: your-secret-key" http://your-server/sessions

# Or as Bearer token
curl -H "Authorization: Bearer your-secret-key" http://your-server/sessions
```

If `API_KEY` is empty, authentication is disabled (not recommended for production).

---

## API Reference

Interactive docs available at: `http://your-server/docs`

### System

#### `GET /health`
Health check. Returns 200 if running.

```json
{
  "status": "ok",
  "active_sessions": 2,
  "max_sessions": 10
}
```

---

### Sessions

A **session** = one browser instance with its own fingerprint, cookies, and context.

#### `POST /sessions` — Create session

```json
// Request body (all optional)
{
  "proxy": "http://user:pass@host:port",
  "user_agent": "Mozilla/5.0 ...",
  "viewport": {"width": 1920, "height": 1080},
  "locale": "en-US",
  "timezone_id": "America/New_York",
  "stealth_args": true
}
```

```json
// Response
{
  "session_id": "abc123def456",
  "message": "Session created successfully"
}
```

#### `GET /sessions` — List all sessions

#### `GET /sessions/{session_id}` — Get session details

#### `DELETE /sessions/{session_id}` — Close session

---

### Pages

A **page** = one browser tab within a session.

#### `POST /sessions/{session_id}/pages` — Open new tab

```json
// Response
{
  "page_id": "a1b2c3d4",
  "url": "about:blank",
  "message": "Page created"
}
```

#### `GET /sessions/{session_id}/pages` — List pages

#### `GET /sessions/{session_id}/pages/{page_id}` — Get page info

#### `DELETE /sessions/{session_id}/pages/{page_id}` — Close tab

---

### Actions

All actions are `POST` requests to `/sessions/{session_id}/pages/{page_id}/{action}`.

#### Navigation

| Endpoint | Description |
|----------|-------------|
| `POST /navigate` | Go to a URL |
| `POST /reload` | Reload current page |
| `POST /go_back` | Browser back |
| `POST /go_forward` | Browser forward |

**Navigate:**
```json
{
  "url": "https://example.com",
  "wait_until": "load",
  "timeout": 30000
}
```

`wait_until` options: `"load"`, `"domcontentloaded"`, `"networkidle"`, `"commit"`

---

#### Interaction

| Endpoint | Description |
|----------|-------------|
| `POST /click` | Click an element |
| `POST /type` | Type text (with keystroke delay) |
| `POST /fill` | Fill input instantly |
| `POST /select` | Select dropdown option |
| `POST /hover` | Hover over element |
| `POST /press_key` | Press keyboard key |
| `POST /scroll` | Scroll page |

**Click:**
```json
{
  "selector": "#submit-button",
  "button": "left",
  "click_count": 1,
  "timeout": 10000
}
```

**Type (human-like):**
```json
{
  "selector": "input[name='email']",
  "text": "user@example.com",
  "delay": 50,
  "clear_first": true
}
```

**Fill (instant):**
```json
{
  "selector": "#password",
  "value": "mypassword"
}
```

**Select dropdown:**
```json
{
  "selector": "select#country",
  "label": "United States"
}
```

**Press key:**
```json
{
  "key": "Enter",
  "selector": "input[type='search']"
}
```

**Scroll:**
```json
// Scroll to position
{"x": 0, "y": 500}

// Scroll by delta
{"delta_x": 0, "delta_y": 300}
```

---

#### Waiting

| Endpoint | Description |
|----------|-------------|
| `POST /wait_for_selector` | Wait for element |
| `POST /wait_for_url` | Wait for URL change |
| `POST /wait_for_load` | Wait for load state |
| `POST /wait` | Wait fixed milliseconds |

**Wait for element:**
```json
{
  "selector": ".results-container",
  "state": "visible",
  "timeout": 30000
}
```

`state` options: `"attached"`, `"detached"`, `"visible"`, `"hidden"`

**Wait for URL:**
```json
{
  "url": "**/dashboard**",
  "timeout": 30000
}
```

---

#### Data Extraction

| Endpoint | Description |
|----------|-------------|
| `GET /content` | Get full HTML |
| `POST /get_text` | Get element text |
| `POST /get_attribute` | Get element attribute |
| `POST /evaluate` | Run JavaScript |
| `POST /inject_script` | Inject JS script |

**Get text:**
```json
{
  "selector": "h1.title",
  "timeout": 10000
}
```

**Evaluate JavaScript:**
```json
// Simple expression
{"expression": "document.title"}

// Function with argument
{"expression": "(x) => x * 2", "arg": 21}

// Complex extraction
{
  "expression": "() => Array.from(document.querySelectorAll('a')).map(a => ({text: a.innerText, href: a.href}))"
}
```

---

#### Screenshot

**`POST /screenshot`** — Returns base64 JSON:
```json
{
  "full_page": false,
  "format": "png",
  "selector": null
}
```

Response:
```json
{
  "image": "iVBORw0KGgo...",
  "format": "png",
  "size": 45231
}
```

**`POST /screenshot/raw`** — Returns binary image directly (better for downloading).

---

#### Cookies

| Endpoint | Description |
|----------|-------------|
| `GET /cookies` | Get all cookies |
| `POST /cookies` | Set cookies |
| `DELETE /cookies` | Clear all cookies |

**Set cookies:**
```json
{
  "cookies": [
    {
      "name": "session",
      "value": "abc123",
      "domain": "example.com",
      "path": "/"
    }
  ]
}
```

---

#### PDF Export

**`POST /pdf`** — Returns binary PDF.

Query params: `format=A4`, `print_background=true`

---

## Examples

### Python — Full automation flow

```python
import httpx
import base64

BASE_URL = "http://your-server:8000"
HEADERS = {"X-API-Key": "your-secret-key"}

client = httpx.Client(base_url=BASE_URL, headers=HEADERS)

# 1. Create session
session = client.post("/sessions", json={
    "viewport": {"width": 1920, "height": 1080},
    "locale": "en-US",
    "timezone_id": "America/New_York",
}).json()
session_id = session["session_id"]

# 2. Open page
page = client.post(f"/sessions/{session_id}/pages").json()
page_id = page["page_id"]

# 3. Navigate
client.post(f"/sessions/{session_id}/pages/{page_id}/navigate", json={
    "url": "https://example.com",
    "wait_until": "networkidle",
})

# 4. Get page title
result = client.post(f"/sessions/{session_id}/pages/{page_id}/evaluate", json={
    "expression": "document.title"
})
print("Title:", result.json()["result"])

# 5. Screenshot
screenshot = client.post(f"/sessions/{session_id}/pages/{page_id}/screenshot", json={
    "full_page": True
}).json()
with open("screenshot.png", "wb") as f:
    f.write(base64.b64decode(screenshot["image"]))

# 6. Close
client.delete(f"/sessions/{session_id}")
```

### Python — Login automation

```python
import httpx

BASE_URL = "http://your-server:8000"
HEADERS = {"X-API-Key": "your-secret-key"}
client = httpx.Client(base_url=BASE_URL, headers=HEADERS)

# Create session with proxy
session_id = client.post("/sessions", json={
    "proxy": "http://user:pass@proxy-host:8080"
}).json()["session_id"]

page_id = client.post(f"/sessions/{session_id}/pages").json()["page_id"]
base = f"/sessions/{session_id}/pages/{page_id}"

# Navigate to login page
client.post(f"{base}/navigate", json={"url": "https://site.com/login"})

# Fill credentials
client.post(f"{base}/fill", json={"selector": "#email", "value": "user@example.com"})
client.post(f"{base}/type", json={
    "selector": "#password",
    "text": "mypassword",
    "delay": 80,
})

# Click login
client.post(f"{base}/click", json={"selector": "button[type='submit']"})

# Wait for redirect
client.post(f"{base}/wait_for_url", json={"url": "**/dashboard**", "timeout": 15000})

# Get cookies for later use
cookies = client.get(f"{base}/cookies").json()["cookies"]
print("Logged in! Cookies:", cookies)

client.delete(f"/sessions/{session_id}")
```

### JavaScript/Node.js

```javascript
const BASE_URL = 'http://your-server:8000';
const HEADERS = { 'X-API-Key': 'your-secret-key', 'Content-Type': 'application/json' };

async function run() {
  // Create session
  const { session_id } = await fetch(`${BASE_URL}/sessions`, {
    method: 'POST', headers: HEADERS, body: JSON.stringify({})
  }).then(r => r.json());

  // Open page
  const { page_id } = await fetch(`${BASE_URL}/sessions/${session_id}/pages`, {
    method: 'POST', headers: HEADERS
  }).then(r => r.json());

  const base = `${BASE_URL}/sessions/${session_id}/pages/${page_id}`;

  // Navigate
  await fetch(`${base}/navigate`, {
    method: 'POST', headers: HEADERS,
    body: JSON.stringify({ url: 'https://example.com' })
  });

  // Get title
  const { result: title } = await fetch(`${base}/evaluate`, {
    method: 'POST', headers: HEADERS,
    body: JSON.stringify({ expression: 'document.title' })
  }).then(r => r.json());

  console.log('Title:', title);

  // Screenshot (raw binary)
  const imgBuffer = await fetch(`${base}/screenshot/raw`, {
    method: 'POST', headers: HEADERS,
    body: JSON.stringify({ full_page: false })
  }).then(r => r.arrayBuffer());

  require('fs').writeFileSync('screenshot.png', Buffer.from(imgBuffer));

  // Close
  await fetch(`${BASE_URL}/sessions/${session_id}`, { method: 'DELETE', headers: HEADERS });
}

run().catch(console.error);
```

### cURL — Quick test

```bash
API="http://localhost:8000"
KEY="your-secret-key"

# Create session
SESSION=$(curl -s -X POST "$API/sessions" \
  -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{}' | python3 -c "import sys,json; print(json.load(sys.stdin)['session_id'])")

# Open page
PAGE=$(curl -s -X POST "$API/sessions/$SESSION/pages" \
  -H "X-API-Key: $KEY" | python3 -c "import sys,json; print(json.load(sys.stdin)['page_id'])")

# Navigate
curl -s -X POST "$API/sessions/$SESSION/pages/$PAGE/navigate" \
  -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'

# Screenshot
curl -s -X POST "$API/sessions/$SESSION/pages/$PAGE/screenshot/raw" \
  -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{}' --output screenshot.png

# Close
curl -s -X DELETE "$API/sessions/$SESSION" -H "X-API-Key: $KEY"
```

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `API_KEY` | _(empty)_ | Secret key for authentication. Empty = no auth |
| `CORS_ORIGINS` | `*` | Allowed CORS origins (comma-separated) |
| `MAX_SESSIONS` | `10` | Max concurrent browser sessions |
| `SESSION_TTL` | `3600` | Idle session timeout in seconds (0 = never) |
| `PORT` | `8000` | HTTP port |
| `LOG_LEVEL` | `INFO` | Log level: DEBUG, INFO, WARNING, ERROR |
| `MEMORY_LIMIT` | `4g` | Docker memory limit |
| `CPU_LIMIT` | `2.0` | Docker CPU limit |
| `CLOAKBROWSER_CACHE_DIR` | `~/.cloakbrowser` | Chromium binary cache directory |
| `CLOAKBROWSER_BINARY_PATH` | _(auto)_ | Override Chromium binary path |

---

## Resource Planning

| Sessions | RAM | CPU |
|----------|-----|-----|
| 1-3 | 2 GB | 1 core |
| 5-10 | 4-6 GB | 2 cores |
| 10-20 | 8-12 GB | 4 cores |
| 20+ | 16+ GB | 8+ cores |

Each browser session uses approximately **300-500 MB RAM** and **0.1-0.5 CPU cores** when active.
