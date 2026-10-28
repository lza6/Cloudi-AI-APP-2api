# Cloudi-AI-APP-2api

Reverse-engineered **Cloudi AI v1.0.9** (Premium by @ElaMods, actually a **Sola AI** repackage) into a self-hostable 2API server with OpenAI-compatible endpoints.

> Upstream: `https://nano-banana.leansoft-ai.com` (Cloudflare Workers) · 图床 `cdn.leansoft-ai.com`

## Reverse-Engineering Summary

| Item | Detail |
|---|---|
| Package | `com.cloudi.ai.image.video.generator` (business code `com.ai.art.generator.video.sola`) |
| Config | **Firebase Remote Config** (project `ls62---ai-video-2`) dynamically serves `base_url` / `aes_key` / `aes_iv` / SSL pin |
| Auth | `X-Client-Auth = base64(AES-256-CBC("{unix_now}||{packageName}||{unix_now+60}"))` — 60s time-window token, keys from Remote Config |
| Headers | `X-Client-Auth` `device-id` `app-user-id` `app-version: 1.0.9` `version-code: 9` `language-code` `app-id` `os-type: android` |
| Crypto | AES-256-CBC + PKCS7, key 32B / IV 16B (recovered from `libnativelib.so` via capstone: `encryptString(key, iv, pkg)`) |

### Endpoint Map (verified live)

| Endpoint | Method | Purpose | Status |
|---|---|---|---|
| `/user/deviceId` | POST | register device → `SaasID:xxx` | ✅ |
| `/activeUser` | POST | daily quota `{usesLeft:6, coins:30, spins:1, rewardeds:4}` | ✅ |
| `/action/rewarded` | POST | rewarded-ad → +50 coins | ✅ |
| `/data/spins` | POST | spin-wheel prize pool | ✅ |
| `/user/appToken` | POST | `access_key` + `secret_key` pair | ✅ |
| `/genUploadLink` | POST | presigned Wasabi upload URL | ✅ |
| `/upload/image-v3` | POST multipart | direct image upload → CDN url | ✅ |
| `/image/enhance` | POST | image enhance — **free, no wall** | ✅ |
| `/image/prompt` | POST | prompt img2img generation | ⚠️ needs `tokenData` session (see Notes) |
| `/image/img2img/v2` | POST | styled img2img | ⚠️ server-side style validation |
| `/video/createTask` | POST multipart | video generation | ❌ upstream `DOMAIN_SUSPENDED` (dead) |

**Styles**: 32 presets across 12 categories dumped in `styles.json` (B&W Portrait, LinkedIn Avatar, Chibi, Wedding, Film Vibe, ...).

## Quick Start

```bash
pip install pycryptodome
python demo_server.py 8902
```

Server auto-fetches Firebase Remote Config at startup — if the vendor rotates `aes_key`/`aes_iv`/`base_url`, it follows automatically.

```bash
curl http://127.0.0.1:8902/health
curl http://127.0.0.1:8902/v1/models
# register a device
curl http://127.0.0.1:8902/v1/session
# enhance an image (free, works)
curl -X POST http://127.0.0.1:8902/v1/image/enhance -d '{"image_b64":"<base64 jpeg>"}'
```

Web dashboard: open `demo.html` in a browser.

## OpenAI-Compatible API

```
GET  /v1/models
POST /v1/chat/completions     {"model":"cloudi-nano-banana","messages":[{"role":"user","content":"prompt"}]}
POST /v1/image/enhance        {"image_b64":"..."}          # or {"image":"url"}
POST /v1/image/generate       {"prompt":"..."}
GET  /v1/session              bootstrap a device
POST /v1/session/bootstrap
POST /v1/session/rewarded
```

## Stress Test

```
python stress_test.py 10
# register: 15 concurrent 100% success (p50 ≈ 3s)
# enhance:  3 concurrent 100% success
```

## ⚠️ Notes & Limitations

1. **`/image/prompt` requires a `tokenData` session** — the worker binds upload↔generate via a server-side session row. Recovering it needs a Frida trace on a real ARM64 device (emulator is blocked by ndk_translation W^X — frida Java hooks SIGSEGV).
2. `Quota limit` from the worker = IP-reputation wall; clean residential/VPN exits work (free proxies do NOT — they fail CF TLS).
3. Direct connections from burned IPs get CF `SSL UNEXPECTED_EOF`; route through a proxy.
4. Video generation upstream is dead (`DOMAIN_SUSPENDED`, Vietnamese error).

## Files

```
demo_server.py            2API server (OpenAI-compatible, auto Remote Config)
demo.html                 web dashboard
stress_test.py            concurrency stress test
styles.json               32 style presets dump
remote_config_sample.json Firebase Remote Config dump (47 entries)
NEW-API-INTEGRATION.md    new-api channel integration guide (中文)
```

## License

MIT — for research/educational purposes only.
