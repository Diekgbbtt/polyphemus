---
name: http-method-tampering
description: Bypassing authorization and authentication controls by manipulating HTTP methods, override headers, and verb-specific logic
metadata:
  version: '1.0'
---

# HTTP Method Tampering

Authorization controls are sometimes tied to the HTTP method rather than the resource. Switching from GET to POST (or vice versa), using method override headers, or sending unexpected verbs can bypass access controls, CSRF protections, and authentication checks.

## Core Technique: Method Switching

Many frameworks implement access control by method:
```python
@app.route("/admin/delete", methods=["POST"])
@require_admin
def delete(): ...

@app.route("/admin/delete", methods=["GET"])  # No auth decorator!
def delete_form(): ...
```

**Test every endpoint with every HTTP method:**
```python
import requests

url = "http://target/api/admin/users"
methods = ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD", "TRACE"]
session_cookie = {"session": "user_level_cookie"}

for method in methods:
    r = requests.request(method, url, cookies=session_cookie)
    print(f"{method:8} {r.status_code} {len(r.text):6}  {r.text[:80]}")
```

## Method Override Headers

Some frameworks support method overriding via headers (originally for HTML forms that only support GET/POST):

```
X-HTTP-Method-Override: DELETE
X-HTTP-Method: PUT
X-Method-Override: PATCH
_method=DELETE  (form field)
```

**Attack pattern:**
```python
# Bypass a DELETE restriction by sending POST with override header
r = requests.post(url,
    headers={"X-HTTP-Method-Override": "DELETE"},
    cookies=user_cookies)

# Or as a form field
r = requests.post(url, data={"_method": "DELETE", ...})
```

## Authorization Bypass Scenarios

**Scenario 1: GET bypasses auth on POST route**
- Endpoint requires auth for POST (create/modify)
- GET version of same endpoint lacks auth check
- Action is triggered by GET as well (e.g., state-changing GET handler)

**Scenario 2: OPTIONS reveals sensitive info**
- `OPTIONS /api/admin` may return `Allow: GET, POST, DELETE` with less strict auth

**Scenario 3: HEAD as reconnaissance**
- HEAD request returns headers without body — useful to probe endpoints that return 200 on HEAD but 403 on GET

**Scenario 4: TRACE for credential capture**
- If TRACE is enabled, it echoes the request back including cookies/auth headers

## Testing Pattern

```python
import requests

def test_method_bypass(base_url, path, cookies, data=None):
    """Test all HTTP methods on a path to find auth bypasses."""
    results = []
    for method in ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"]:
        try:
            r = requests.request(
                method, f"{base_url}{path}",
                cookies=cookies,
                data=data if method in ("POST", "PUT", "PATCH") else None,
                timeout=5,
                allow_redirects=False
            )
            results.append({
                "method": method,
                "status": r.status_code,
                "length": len(r.content),
                "location": r.headers.get("Location", ""),
            })
        except Exception as e:
            results.append({"method": method, "error": str(e)})
    return results

# Test admin endpoints with low-privilege session
for path in ["/admin", "/admin/users", "/api/v1/admin", "/api/delete"]:
    print(f"\n{path}:")
    for result in test_method_bypass("http://target", path, user_cookies):
        print(f"  {result['method']:8} {result['status']} {result['length']}")
```

## CORS and Preflight Bypass

Some endpoints check CORS only on non-simple requests (those triggering preflight):
- Simple requests: GET, POST with `text/plain` or `application/x-www-form-urlencoded`
- By changing `Content-Type` to `text/plain`, a state-changing POST may bypass CORS

```python
# Attempt CORS bypass via simple request
r = requests.post(url,
    data=json.dumps(payload),  # keep body as JSON
    headers={"Content-Type": "text/plain"})  # but claim text/plain
```

## Pro Tips

1. Always test GET/POST/PUT/DELETE/PATCH on ALL endpoints, not just obvious ones
2. Method override headers (`X-HTTP-Method-Override`) are widely supported in Rails, Django, Spring
3. Authorization checks are often tied to path pattern matching — PUT to a GET-only path may bypass auth
4. If POST /api/resource requires auth, try GET /api/resource — may return same data without auth
5. HEAD requests are often forgotten in access control logic
6. State-changing GET endpoints (`/action/delete?id=1`) are common in legacy apps and bypass CSRF tokens
