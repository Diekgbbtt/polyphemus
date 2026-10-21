# low-hanging-fruit - defence-bypass / proxy techniques (extracted)

*Extracted from the `low-hanging-fruit` skill per the operator's ruling: its CORS, CSP, WAF-bypass, header, and enumeration material is bypass/proxy technique content that strengthens adversarial capabilities, and is to be projected into the "proxy techniques" and "defence bypass techniques" notions of the relevant skills rather than kept as a standalone hygiene-checklist skill. The per-target severity table and the finding-recording workflow are not bypass/proxy content and were not preserved.*

## Security response headers and CSP assessment

### Default security headers (missing -> low)

| Header | Why it matters | Recommended |
|--------|----------------|-------------|
| Content-Security-Policy | Mitigates XSS by whitelisting content sources | Policy appropriate to the app |
| X-Frame-Options | Clickjacking defense | `SAMEORIGIN` (or CSP `frame-ancestors`) |
| X-Content-Type-Options | Stops MIME sniffing | `nosniff` |
| Referrer-Policy | Limits referrer leakage | e.g. `strict-origin-when-cross-origin` |
| Permissions-Policy | Restricts browser features/APIs | Explicit allowlist |

### If CSP is present - analyze it

Flag (usually low, escalate if clearly exploitable):

- `unsafe-inline` / `unsafe-eval` in `script-src`
- Wildcards like `*` or overly broad CDNs in `script-src` / `default-src`
- Missing `object-src 'none'` / `base-uri` / `frame-ancestors` when relevant
- Report the raw CSP value in the proof

### Cross-origin headers (missing -> low)

| Header | Purpose |
|--------|---------|
| Cross-Origin-Embedder-Policy | Blocks cross-origin loads without CORP/CORS |
| Cross-Origin-Opener-Policy | Enables cross-origin isolation |
| Cross-Origin-Resource-Policy | Controls who may load the resource |

### Additional header notes

- `Server` / `X-Powered-By` / framework headers: technology leakage.
- `Access-Control-Allow-Origin`: see CORS below.
- `Strict-Transport-Security`: if HTTPS and HSTS missing, include as low with the default-header group when appropriate.

## CORS

```bash
curl -sI -H "Origin: https://evil.example" "https://HOST/"
# If API endpoints known, repeat against one authenticated/API path
```

Create a finding when:

- `Access-Control-Allow-Origin: *` on application (non-CDN-static) responses
- Reflected `Origin` together with `Access-Control-Allow-Credentials: true`
- `null` origin accepted with credentials

Include the request Origin and the response ACAO/ACAC headers in proof.

## WAF / CDN and rate limiting

Heuristics:

- CDN/WAF clues: `cf-ray`, `x-vercel-id`, `x-amz-cf-id`, `x-cache`, `server: cloudflare`, Akamai/Fastly headers, etc.
- If no such clues: send a short burst of identical requests (e.g. 30-50 rapid GETs) and check for 429 / Retry-After / challenge pages.
- If still no rate limiting, note the absence of WAF/CDN indicators and of a rate-limit response.

Do not claim "no WAF" with certainty; phrase as "no common WAF/CDN indicators observed" plus the rate-limit test result.

## Technology leakage enumeration

Inspect response headers and easy HTML/JS fingerprints (`Server`, `X-Powered-By`, `X-AspNet-Version`, generator meta, etc.).

- Product name only -> low
- Exact version -> medium
- Include the exact header/body snippet in proof

## TLS version enumeration

For HTTPS hosts, probe supported protocols:

```bash
# Replace HOST:443
for v in tls1 tls1_1 tls1_2 tls1_3; do
  echo "=== $v ==="
  openssl s_client -connect HOST:443 -$v </dev/null 2>/dev/null | openssl x509 -noout -subject 2>/dev/null && echo OK || echo FAIL
done
```

- If `tls1` or `tls1_1` succeeds, legacy TLS is supported.
- If `tls1_3` fails while TLS 1.2 works, note it.
- Skip TLS checks for plain HTTP-only targets.
