#!/usr/bin/env python3
"""Cold-login reCAPTCHA challenge probe (#237/#220 diagnosis).

The reported failure: a cold, non-stealth login on magnific.com is held by a
visible reCAPTCHA Enterprise challenge (a low score), where a warm browser
identity is not. This probe reproduces that symptom as a tight pass/fail
signal:

  GREEN (exit 0)  the login reached the authenticated landing, no challenge
  RED   (exit 1)  a reCAPTCHA challenge frame appeared (the reported symptom)
  UNKNOWN (exit 2) neither within the window (silent hold or unexpected state)

It drives the exact path under test: a fresh Steel session (optionally a
mounted profile), the email-first form, and ONE submit - no blind retries.
The challenge is detected, never solved, so no human is required to run it.

Usage:
  MAGNIFIC_USER=... MAGNIFIC_PASS=... \
    python3 tests/e2e/harness/recaptcha_challenge_probe.py \
    [--stealth] [--proxy URL] [--profile NAME] [--timeout 60]

Credentials come from the environment only and are never echoed.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import uuid

LOGIN_URL = "https://www.magnific.com/log-in"
AUTHENTICATED_PREFIX = "/app"


def _steel(*args: str, timeout: int = 120) -> tuple[int, str]:
    exe = shutil.which("steel") or os.path.expanduser("~/.steel/bin/steel")
    proc = subprocess.run(
        [exe, *args], capture_output=True, text=True, timeout=timeout
    )
    return proc.returncode, (proc.stdout or proc.stderr or "").strip()


def _eval(session: str, js: str, timeout: int = 60) -> str:
    rc, out = _steel("browser", "eval", "--session", session, "--json", js,
                     timeout=timeout)
    if rc != 0:
        return ""
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            body = json.loads(line)
        except json.JSONDecodeError:
            continue
        data = body.get("data")
        return data if isinstance(data, str) else json.dumps(data)
    return ""


_STATE_JS = """(() => {
  const frames = [...document.querySelectorAll('iframe')];
  const challenge = frames.some(f => {
    const s = (f.title || '') + ' ' + (f.src || '');
    return /recaptcha/i.test(s) && /(bframe|challenge)/i.test(s)
      && f.offsetWidth > 300 && f.offsetHeight > 200;
  });
  return JSON.stringify({path: location.pathname, challenge});
})()"""

_SET_INPUT_JS = """(() => {
  const i = document.querySelector(%s);
  if (!i) return 'no-input';
  const set = Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype, 'value').set;
  set.call(i, %s);
  i.dispatchEvent(new Event('input', {bubbles: true}));
  i.dispatchEvent(new Event('change', {bubbles: true}));
  return 'set';
})()"""

_CLICK_TEXT_JS = """(() => {
  const b = [...document.querySelectorAll('button, a')]
    .find(x => x.textContent.trim().toLowerCase() === %s);
  if (!b) return 'no-button';
  b.click();
  return 'clicked';
})()"""

_CONSENT_JS = """(() => {
  const words = ['accept all', 'accept cookies', 'accept', 'reject all',
                 'i agree', 'agree', 'consent', 'got it', 'ok'];
  const b = [...document.querySelectorAll('button, a')]
    .find(x => words.some(w =>
      x.textContent.trim().toLowerCase().startsWith(w)));
  if (!b) return 'none';
  b.click();
  return 'consent-clicked';
})()"""


def _js_str(value: str) -> str:
    return json.dumps(value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stealth", action="store_true")
    parser.add_argument("--proxy", default=None)
    parser.add_argument("--profile", default=None)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument(
        "--retry-storm", action="store_true",
        help="mimic the observed failing pattern: after the first submit, "
             "blindly resubmit up to 3 times instead of waiting on a "
             "condition (the run-2 behaviour)")
    args = parser.parse_args()

    user = os.environ.get("MAGNIFIC_USER")
    password = os.environ.get("MAGNIFIC_PASS")
    if not user or not password:
        print("set MAGNIFIC_USER and MAGNIFIC_PASS", file=sys.stderr)
        return 2

    tag = uuid.uuid4().hex[:8]
    session = f"challenge-probe-{tag}"
    scratch = args.profile is None
    profile = args.profile or f"challenge-probe-tmp-{tag}"
    started = False
    try:
        start_args = ["browser", "start", "--session", session,
                      "--profile", profile, "--session-timeout", "600000"]
        if scratch:
            start_args.append("--update-profile")
        if args.stealth:
            start_args.append("--stealth")
        if args.proxy:
            start_args += ["--proxy", args.proxy]
        start_args.append("--json")
        rc, out = _steel(*start_args, timeout=180)
        if rc != 0:
            print(f"start failed: {out[:200]}", file=sys.stderr)
            return 2
        started = True

        _steel("browser", "navigate", LOGIN_URL, "--session", session,
               "--wait-until", "load", "--json", timeout=120)
        time.sleep(2)
        # `/log-in` lands on the homepage for an anonymous session; the login
        # route is reached by the "Log in" link.
        _eval(session, _CLICK_TEXT_JS % _js_str("log in"))
        time.sleep(3)
        _eval(session, _CONSENT_JS)

        _eval(session, _SET_INPUT_JS % (
            "'input[type=email], input[name=email], #email'", _js_str(user)))
        _eval(session, _CLICK_TEXT_JS % _js_str("continue"))
        time.sleep(2)

        _eval(session, _SET_INPUT_JS % (
            "'input[type=password], input[name=password], #password'",
            _js_str(password)))
        _eval(session, _CLICK_TEXT_JS % _js_str("log in"))

        if args.retry_storm:
            for _ in range(3):
                time.sleep(10)
                raw = _eval(session, _STATE_JS, timeout=30)
                try:
                    state = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    state = {}
                if state.get("challenge") or str(
                    state.get("path", "")
                ).startswith(AUTHENTICATED_PREFIX):
                    break
                _eval(session, _CLICK_TEXT_JS % _js_str("log in"))

        verdict = "UNKNOWN"
        deadline = time.time() + args.timeout
        while time.time() < deadline:
            raw = _eval(session, _STATE_JS, timeout=30)
            try:
                state = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                state = {}
            path = str(state.get("path", ""))
            if state.get("challenge"):
                verdict = "RED"
                break
            if path.startswith(AUTHENTICATED_PREFIX):
                verdict = "GREEN"
                break
            time.sleep(3)

        print(json.dumps({
            "verdict": verdict,
            "stealth": args.stealth,
            "proxy": bool(args.proxy),
            "profile": "scratch" if scratch else profile,
            "session": session,
        }))
        return {"GREEN": 0, "RED": 1, "UNKNOWN": 2}[verdict]
    finally:
        if started:
            _steel("browser", "stop", "--session", session, "--json",
                   timeout=60)
        if scratch:
            _steel("profile", "delete", "--name", profile, "--json",
                   timeout=60)


if __name__ == "__main__":
    sys.exit(main())
