# CloakBrowser on AWS Lambda

Run stealth Chromium one-shot scrapes inside an AWS Lambda function (container image package type). The image derives directly from the official CloakHQ Docker Hub image (`cloakhq/cloakbrowser`) and adds Lambda runtime support on top — Lambda is an additional invocation surface, not a replacement. Every other surface from the canonical image (`python`, `cloakserve`, `cloaktest`, `node`, `bash`, examples) keeps working.

This document covers what the image is, how to build and locally test it, and the event/response contract. **It does not prescribe a deployment method** — push the resulting image to ECR and create the Lambda function however you prefer (AWS CLI, CDK, Terraform, SAM, console, etc.). Configuration tips for whichever tool you use are at the bottom.

## Files in this directory

| File | Purpose |
|---|---|
| `Dockerfile` | `FROM cloakhq/cloakbrowser` plus a thin Lambda layer. Self-contained — no files outside this directory are referenced. |
| `lambda-entrypoint.sh` | Dual-mode entrypoint. Starts Xvfb, then routes `module.func` CMDs through `awslambdaric` (via the bundled `aws-lambda-rie` locally, or the AWS Runtime API in production), and execs everything else (`python`, `cloakserve`, `cloaktest`, `node`, `bash`) directly. |
| `lambda_handler.py` | Default handler. Takes `{url, ...}`, returns `{title, url, html, screenshot_b64?}`. Always headed via Xvfb. |
| `INSTRUCTIONS.md` | This file. |

The Lambda layer is ~30 lines on top of the official image — no apt list, no Node install, no JS-wrapper build, no Chromium download. The canonical CloakHQ image owns those.

This directory is **standalone**: copy or clone it anywhere (its own repo, a subdirectory of an existing project, a CI artifact bundle) and the build still works. It depends only on the upstream `cloakhq/cloakbrowser` image on Docker Hub and the `aws-lambda-rie` binary on GitHub Releases — both fetched at build time.

## Build

From inside this directory:

```bash
docker buildx build --platform linux/arm64 -t cloakbrowser-lambda:arm64 --load .
```

Or from anywhere, pointing at this directory as the build context:

```bash
docker buildx build --platform linux/arm64 \
  -f path/to/aws_lambda/Dockerfile \
  -t cloakbrowser-lambda:arm64 --load \
  path/to/aws_lambda
```

The build pulls `cloakhq/cloakbrowser:latest` from Docker Hub and adds the Lambda layer on top. Pin a specific tag (e.g. `cloakhq/cloakbrowser:0.3.25`) in the `FROM` line for reproducible builds; `latest` floats with the upstream release cadence.

For x86_64, switch `--platform linux/amd64` (slower on Apple Silicon under emulation).

## Local smoke test (no AWS account needed)

> **What's the RIE?** Lambda container images can't be run with a plain `docker run` — they expect to talk to AWS's Runtime API (the HTTP service Lambda exposes inside its sandbox to deliver events and collect responses). AWS publishes a small binary called the **Runtime Interface Emulator** that stands up a fake Runtime API on localhost so you can test the container exactly the way Lambda will invoke it, without deploying. We bake the RIE into the image, and the dual-mode entrypoint uses it automatically when `AWS_LAMBDA_RUNTIME_API` isn't set (i.e. you're not running in real Lambda).

The image bakes in `aws-lambda-rie`, so the standard Lambda local-invoke endpoint works without mounting anything:

```bash
docker run --rm -p 9000:8080 cloakbrowser-lambda:arm64

# In another shell:
curl -sS -XPOST "http://localhost:9000/2015-03-31/functions/function/invocations" \
  -d '{"url":"https://example.com"}'
```

Other invocation surfaces stay intact (these match the canonical CloakHQ image):

```bash
docker run --rm -it cloakbrowser-lambda:arm64 python                          # REPL
docker run --rm cloakbrowser-lambda:arm64 python examples/basic.py            # examples
docker run --rm -p 9222:9222 cloakbrowser-lambda:arm64 cloakserve --port=9222 # CDP server
docker run --rm cloakbrowser-lambda:arm64 cloaktest                           # stealth tests
docker run --rm -it cloakbrowser-lambda:arm64 node                            # JS wrapper
```

## Event schema

Only `url` is required. Everything else is optional.

### Launch options (forwarded to `cloakbrowser.launch_context_async`)

| Field | Type | Default |
|---|---|---|
| `url` | str | required |
| `proxy` | str / dict | none — `http://user:pass@host:port` or a Playwright proxy dict |
| `humanize` | bool | `false` — enable human-like mouse / keyboard / scroll |
| `human_preset` | str | `"default"` or `"careful"` |
| `geoip` | bool | `false` — auto timezone+locale from proxy IP |
| `timezone` | str | none — IANA tz, e.g. `"America/New_York"` |
| `locale` | str | none — BCP-47, e.g. `"en-US"` |
| `viewport` | `{width,height}` | `1920x947` (cloakbrowser default) |
| `user_agent` | str | none |
| `extra_args` | `list[str]` | `[]` — extra Chromium CLI flags |

### Navigation

| Field | Type | Default |
|---|---|---|
| `wait_until` | str | `"domcontentloaded"` — `load` / `domcontentloaded` / `networkidle` / `commit` |
| `goto_timeout_ms` | int | `30000` |

### Post-navigation waits

`smart_wait` is the default when no other wait is specified. It polls `document.documentElement.outerHTML.length` and returns when the size hasn't changed for `dom_stable_ms`. Robust for at-scale scraping because it ignores network activity (analytics beacons, long-poll, websockets) that doesn't mutate the DOM — `wait_until: "networkidle"` is unreliable on modern SPAs for exactly this reason.

| Field | Type | Default |
|---|---|---|
| `smart_wait` | bool | `true` if no other wait is set |
| `dom_stable_ms` | int | `1500` |
| `max_settle_ms` | int | `15000` |
| `wait_for_load_state` | str | none — `load` / `domcontentloaded` / `networkidle` |
| `wait_for_load_state_timeout_ms` | int | `30000` |
| `wait_for_selector` | str | none — CSS or XPath |
| `wait_for_selector_state` | str | `"visible"` — also `attached` / `detached` / `hidden` |
| `wait_for_selector_timeout_ms` | int | `30000` |
| `wait_for_function` | str | none — JS expression returning truthy when ready |
| `wait_for_function_timeout_ms` | int | `30000` |
| `wait_ms` | int | none — fixed pause |

### Capture

| Field | Type | Default |
|---|---|---|
| `screenshot` | bool | `true` |
| `full_page_screenshot` | bool | `false` |

### Response

```json
{
  "title": "...",
  "url": "https://example.com/",
  "html": "<!DOCTYPE html>...",
  "screenshot_b64": "<base64 PNG>"
}
```

## Lambda-specific Chromium hardening (baked in, do not remove)

Two flags are forced on every launch by `lambda_handler.py`:

- `--disable-dev-shm-usage` — Lambda's `/dev/shm` is ~64 MB; Chromium's renderer crashes mid-paint without this.
- `--no-zygote` — Lambda's restricted process model can't fork from Chromium's zygote process; without this the browser launches but child renderers fail to spawn and the first `page.new_page()` raises `TargetClosedError`.

## Function configuration recommendations

Whatever tool you use to create the Lambda function (CLI, CDK, Terraform, SAM, console), apply these settings:

| Setting | Value | Why |
|---|---|---|
| Package type | Image | Required — this is a container image, not a zip. |
| Architecture | `arm64` | Roughly 20% cheaper than x86_64. Native build on Apple Silicon. Match the architecture you built for. |
| Memory | 3008 MB | Memory in Lambda is tied to vCPU. Below ~1769 MB Chromium starts noticeably slower. |
| Timeout | 60–120 s | Cold start can hit 80+ s on this image; warm invocations are 3–15 s depending on site. |
| Ephemeral storage (`/tmp`) | 1024 MB | Chromium profile dirs and screenshots can fill the 512 MB default. |
| Networking | Default (no VPC) | Binary is baked in, no network needed at cold start. Add VPC + NAT only if your proxy egress requires it. |
| Execution role | `AWSLambdaBasicExecutionRole` | Just CloudWatch Logs. Add more permissions only if your handler needs them. |

## Cold start

First invocation in a new container takes ~80–90 s (image extraction, Chromium binary mmap, JS engine warmup, no DNS/TLS caches). Subsequent warm invocations on the same container are 3–15 s.

For latency-sensitive use cases: provision concurrency, schedule a CloudWatch/EventBridge warmer ping, or accept the cold tail.

If you see empty/missing dynamic content on cold-start invocations, raise `max_settle_ms` in the event payload (e.g. `25000`) — the default `15000` is tuned for warm runs.

## License

The patched Chromium binary inside the upstream `cloakhq/cloakbrowser` image is governed by the **CloakBrowser Binary License** (published at https://github.com/CloakHQ/CloakBrowser/blob/main/BINARY-LICENSE.md). Internal organizational use (private ECR, your own scraping pipelines, your own business) is free. Exposing this Lambda as a paid API to third-party customers — i.e. browser-as-a-service — requires an OEM/SaaS license from CloakHQ (`cloakhq@pm.me`). Do not push the resulting image to a public registry; that would be redistribution and is prohibited.
