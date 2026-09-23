---
name: low-hanging-fruit
description: Default hygiene checks per target — TLS versions, security headers, CSP, tech leakage, CORS, WAF/CDN and rate limiting
metadata:
  version: '1.0'
---

# Low Hanging Fruit

Run these checks once per **target** (base URL / host). Keep probes simple (`curl`, `openssl`, `httpx`). Record each issue via `judge_and_record_finding` with concrete request/response or command output as proof. Use the severity table below; put the severity in the finding markdown (e.g. `**Severity:** medium`).

## Severity rules

| Check | Condition | Severity |
|-------|-----------|----------|
| TLS | Any supported protocol ≤ TLS 1.1 | **medium** |
| TLS | TLS 1.3 not offered/supported | **informational** |
| Security headers | Missing CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, or Permissions-Policy | **low** |
| Cross-origin headers | Missing Cross-Origin-Embedder-Policy, Cross-Origin-Opener-Policy, or Cross-Origin-Resource-Policy | **low** |
| Tech leakage | Server / X-Powered-By / similar discloses product **without** exact version | **low** |
| Tech leakage | Exact version number disclosed (e.g. `nginx/1.18.0`) | **medium** |
| WAF/CDN + rate limit | No WAF/CDN indicators **and** no evidence of rate limiting | **low** |
| CORS | Dangerous policy (e.g. `Access-Control-Allow-Origin: *` on app responses, or reflected origin with credentials) | **low** (use **medium** if credentials are allowed with a reflected/null origin) |

Do **not** file a finding for headers that are present with a reasonable value. Missing HSTS on pure HTTP-only targets: note only; prefer checking HTTPS endpoints.

## 1. TLS versions

For HTTPS hosts, probe supported protocols (example):

```bash
# Replace HOST:443
for v in tls1 tls1_1 tls1_2 tls1_3; do
  echo "=== $v ==="
  openssl s_client -connect HOST:443 -$v </dev/null 2>/dev/null | openssl x509 -noout -subject 2>/dev/null && echo OK || echo FAIL
done
```

- If `tls1` or `tls1_1` succeeds → medium finding (legacy TLS).
- If `tls1_3` fails while TLS 1.2 works → informational finding.
- Skip TLS checks for plain HTTP-only targets.

## 2. Security response headers

Fetch the target homepage (and the primary HTTPS URL if available) with full headers:

```bash
curl -sI -L --max-redirs 5 "https://HOST/"
```

### Default security headers (missing → low)

| Header | Why it matters | Recommended |
|--------|----------------|-------------|
| Content-Security-Policy | Mitigates XSS by whitelisting content sources | Policy appropriate to the app |
| X-Frame-Options | Clickjacking defense | `SAMEORIGIN` (or CSP `frame-ancestors`) |
| X-Content-Type-Options | Stops MIME sniffing | `nosniff` |
| Referrer-Policy | Limits referrer leakage | e.g. `strict-origin-when-cross-origin` |
| Permissions-Policy | Restricts browser features/APIs | Explicit allowlist |

One finding may group several missing default headers, listing each missing header and a short remediation note.

### If CSP is present — analyze it

Flag (still via findings, usually **low**, escalate if clearly exploitable):

- `unsafe-inline` / `unsafe-eval` in `script-src`
- Wildcards like `*` or overly broad CDNs in `script-src` / `default-src`
- Missing `object-src 'none'` / `base-uri` / `frame-ancestors` when relevant
- Report the raw CSP value in the proof

### Cross-origin headers (missing → low)

| Header | Purpose |
|--------|---------|
| Cross-Origin-Embedder-Policy | Blocks cross-origin loads without CORP/CORS |
| Cross-Origin-Opener-Policy | Enables cross-origin isolation |
| Cross-Origin-Resource-Policy | Controls who may load the resource |

### Additional header notes (findings when applicable)

- **`Server` / `X-Powered-By` / framework headers**: technology leakage (see severity table).
- **`Access-Control-Allow-Origin`**: see CORS section.
- **`Strict-Transport-Security`**: if HTTPS and HSTS missing → include as **low** with the default-header group when appropriate.

## 3. Technology leakage

Inspect response headers and easy HTML/JS fingerprints (`Server`, `X-Powered-By`, `X-AspNet-Version`, generator meta, etc.).

- Product name only → **low**
- Exact version → **medium**
- Include the exact header/body snippet in proof

## 4. WAF / CDN and rate limiting

Heuristics:

- CDN/WAF clues: `cf-ray`, `x-vercel-id`, `x-amz-cf-id`, `x-cache`, `server: cloudflare`, Akamai/Fastly headers, etc.
- If **no** such clues: send a short burst of identical requests (e.g. 30–50 rapid GETs) and check for 429 / Retry-After / challenge pages.
- If still no rate limiting → **low** finding describing absence of WAF/CDN indicators and lack of rate-limit response.

Do not claim “no WAF” with certainty; phrase as “no common WAF/CDN indicators observed” plus rate-limit test result.

## 5. CORS

```bash
curl -sI -H "Origin: https://evil.example" "https://HOST/"
# If API endpoints known, repeat against one authenticated/API path
```

Create a finding when:

- `Access-Control-Allow-Origin: *` on application (non-CDN-static) responses
- Reflected `Origin` together with `Access-Control-Allow-Credentials: true`
- `null` origin accepted with credentials

Include request Origin and response ACAO/ACAC headers in proof.

## Workflow

1. Resolve the target URL/host from scope (`target_id`).
2. Run TLS (if HTTPS), header fetch, CORS probe, tech leak review, WAF/CDN + rate-limit check.
3. For each issue, call `judge_and_record_finding` with copy-pasteable proof.
4. Stop when the checklist above is done — do not expand into deep exploitation.
