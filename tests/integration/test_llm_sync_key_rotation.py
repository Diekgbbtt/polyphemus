"""#193 contract: a provider API-key rotation propagates to the gateway.

Runs the REAL sync pipeline (`run_sync` -> `build_desired` -> `diff_desired`
-> push) against a stateful, recording stand-in for the litellm management
API - the contract tier's "recording/fake gateway" pattern. DB-free, no live
stack, no network.

The recording client mirrors the wire semantics the sync depends on,
verified against the litellm 1.96 proxy source:

- `GET /model/info` MASKs `api_key` (`remove_sensitive_info_from_deployment`
  pops it from every deployment), so the registered side is NEVER diffable
  for the key - the sync must track it independently (#193).
- `POST /model/new` stores the deployment; `PATCH /model/{id}/update` merges
  `litellm_params` (a fresh `api_key` is re-encrypted server-side and
  persisted, then the router cache is cleared), so an update carrying the new
  key is exactly what rotates it.

Assertions: the first run registers the models; a key rotation for ONE
provider makes the next sync fire the update path for THAT provider's models
with the NEW key in `litellm_params`, and the other provider is untouched.
A third run with the unchanged key is a fully idle no-op (idempotent, D9).
"""

from urllib.parse import urlparse

import httpx

from polymerhus.app.llm import sync as S

CATALOG = {
    "providers": {
        "opencode": {
            "id": "opencode",
            "api": "https://opencode.ai/zen/v1",
            "models": {
                "deepseek-v4-flash": {
                    "id": "deepseek-v4-flash",
                    "tool_call": True,
                    "limit": {"context": 128000, "output": 32768},
                },
            },
        },
        "openai": {
            "id": "openai",
            "api": "https://api.openai.com/v1",
            "models": {
                "gpt-4o": {
                    "id": "gpt-4o",
                    "tool_call": True,
                    "limit": {"context": 128000, "output": 16384},
                },
            },
        },
    },
    "models": {},
}

PROVIDER_MODEL_IDS = {
    "opencode": {"deepseek-v4-flash"},
    "openai": {"gpt-4o"},
}

PROVIDERS = {"opencode": "https://opencode.ai/zen/v1",
             "openai": "https://api.openai.com/v1"}

SYNCED_AT = "2026-08-11T12:00:00+00:00"


class RecordingGatewayAPI:
    """A stateful, recording stand-in for the litellm management API."""

    def __init__(self):
        self.records: dict[str, dict] = {}
        self.virtual_keys: dict[str, list[str]] = {}
        self.calls: list[tuple[str, str, dict | None]] = []
        self._seq = 0

    def _response(self, payload, status=200):
        class _Response:
            status_code = status

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise httpx.HTTPStatusError(
                        "bad status", request=None, response=self)

            def json(self):
                return payload

        return _Response()

    def request(self, method, url, *, json=None, headers=None, timeout=None):
        path = urlparse(url).path
        self.calls.append((method, path, json))
        if method in ("POST", "PATCH"):
            assert json is not None, "management writes always carry a body"
        if method == "GET" and path == "/model/info":
            data = []
            for record in self.records.values():
                entry = dict(record)
                params = dict(entry["litellm_params"])
                params.pop("api_key", None)  # litellm masks the stored key
                entry["litellm_params"] = params
                data.append(entry)
            return self._response({"data": data})
        if method == "POST" and path == "/model/new":
            self._seq += 1
            mid = f"mid-{self._seq}"
            self.records[mid] = {
                "model_name": json["model_name"],
                "litellm_params": dict(json["litellm_params"]),
                "model_info": {**json["model_info"], "id": mid},
            }
            return self._response({})
        if method == "PATCH" and path.startswith("/model/") and path.endswith("/update"):
            mid = path.split("/")[2]
            record = self.records[mid]
            record["litellm_params"] = {**record["litellm_params"],
                                        **json["litellm_params"]}
            record["model_info"] = {**record["model_info"], **json["model_info"]}
            return self._response({})
        if method == "POST" and path == "/model/delete":
            self.records.pop(json["id"], None)
            return self._response({})
        if method == "POST" and path == "/key/generate":
            self.virtual_keys[json["key"]] = list(json["models"])
            return self._response({})
        if method == "POST" and path == "/key/update":
            self.virtual_keys[json["key"]] = list(json["models"])
            return self._response({})
        raise AssertionError(f"unexpected management call: {method} {path} {json}")

    def get(self, url, *, headers=None, timeout=None):
        path = urlparse(url).path
        self.calls.append(("GET", path, None))
        if path == "/key/info":
            key = urlparse(url).query.removeprefix("key=")
            if key in self.virtual_keys:
                return self._response({"info": {"models": self.virtual_keys[key]}})
            return self._response({}, status=404)
        raise AssertionError(f"unexpected management GET: {path}")


def _run(recorder, key_for):
    return S.run_sync(
        fetch_catalog=lambda: CATALOG,
        fetch_provider_models=lambda provider, key: PROVIDER_MODEL_IDS[provider],
        gateway=S.GatewayClient("http://127.0.0.1:4000", "sk-master",
                                client=recorder),
        providers=PROVIDERS,
        read_api_key=key_for,
        synced_at=SYNCED_AT,
    )


def test_provider_key_rotation_updates_that_providers_models_with_new_key():
    recorder = RecordingGatewayAPI()

    # First bootstrap: register both providers with the ORIGINAL keys.
    def original_keys(provider):
        return {"opencode": "sk-opencode-OLD", "openai": "sk-openai"}[provider]

    assert _run(recorder, original_keys) == S.SYNC_OK
    assert [c[0] for c in recorder.calls].count("POST") >= 2  # /model/new x2
    for name in ("opencode/deepseek-v4-flash", "openai/gpt-4o"):
        record = next(r for r in recorder.records.values()
                      if r["model_name"] == name)
        assert record["litellm_params"]["api_key"] in (
            "sk-opencode-OLD", "sk-openai")

    # Rotate ONLY the opencode key; the rest of the world is unchanged.
    def rotated_keys(provider):
        return {"opencode": "sk-opencode-NEW", "openai": "sk-openai"}[provider]

    assert _run(recorder, rotated_keys) == S.SYNC_OK

    # The update (PATCH /model/{id}/update) path fires for the rotated
    # provider's model, carrying the NEW key in litellm_params so litellm
    # re-encrypts and persists it (#193). The untouched provider is not
    # re-pushed.
    patches = [call for call in recorder.calls
               if call[0] == "PATCH" and call[1].endswith("/update")
               and call[2] and call[2].get("model_name") != S.SNAPSHOT_MODEL_NAME]
    assert len(patches) == 1, f"exactly the rotated provider must update, got {patches}"
    _method, path, body = patches[0]
    assert body["model_name"] == "opencode/deepseek-v4-flash"
    assert body["litellm_params"]["api_key"] == "sk-opencode-NEW"

    # The new key LANDED in the persisted record.
    opencode_row = next(r for r in recorder.records.values()
                        if r["model_name"] == "opencode/deepseek-v4-flash")
    assert opencode_row["litellm_params"]["api_key"] == "sk-opencode-NEW"
    openai_row = next(r for r in recorder.records.values()
                      if r["model_name"] == "openai/gpt-4o")
    assert openai_row["litellm_params"]["api_key"] == "sk-openai"

    # A third run with the SAME key is fully idle (idempotent, D9): only the
    # read surface is touched (GET /model/info + one key_info per provider),
    # no model or snapshot write fires.
    writes = len(recorder.calls)
    assert _run(recorder, rotated_keys) == S.SYNC_OK
    assert len(recorder.calls) == writes + 3
    assert all(call[0] == "GET" for call in recorder.calls[writes:])