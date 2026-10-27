import json
import os
import re
import time
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "https://api.tokenfactory.nebius.com/v1/"
DEFAULT_MODEL = "nvidia/nemotron-3-super-120b-a12b"


class LLMError(RuntimeError):
    pass


OFFLINE_MARK = "[offline]"
AWAITING_REVIEW = "[awaiting review]"    # a proposed state change waits for the user's decision
REJECTED_BY_USER = "[rejected by user]"  # the user declined the proposed change; evidence is kept


class ModelUnavailable(LLMError):
    """The model service can't be reached (no network, DNS, timeout). Updates are queued."""


def retryable(error_text):
    """Errors worth retrying automatically later: offline, rate limits, server errors."""
    e = error_text or ""
    # 401/403 are included: they are fixed by correcting the key, after which the update should apply
    return (e.startswith(OFFLINE_MARK) or e.startswith("cannot reach")
            or any(f"HTTP {c}" in e for c in (401, 403, 429, 500, 502, 503, 504)))


def load_dotenv(path=".env"):
    """Minimal .env loader (KEY=VALUE lines); existing environment variables win."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def extract_json(text):
    """Pull the first JSON object out of a model response (tolerates think blocks and fences)."""
    if text is None:
        raise LLMError("empty model response")
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    text = re.sub(r"```(?:json)?", "", text)
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    raise LLMError(f"no JSON object in model response: {text[:200]!r}")


class NebiusClient:
    def __init__(self, api_key=None, base_url=None, model=None, temperature=0.1, timeout=180):
        self.api_key = api_key or os.environ.get("NEBIUS_API_KEY")
        if not self.api_key:
            raise LLMError("NEBIUS_API_KEY is not set (put it in .env or the environment)")
        self.base_url = (base_url or os.environ.get("NEBIUS_BASE_URL") or DEFAULT_BASE_URL).rstrip("/") + "/"
        self.model = model or os.environ.get("NEBIUS_MODEL") or DEFAULT_MODEL
        self.temperature = temperature
        self.timeout = timeout
        extra = os.environ.get("NEBIUS_EXTRA_BODY")
        self.extra_body = json.loads(extra) if extra else {}
        self._json_mode = True
        self.last_usage = None

    @property
    def name(self):
        return self.model

    def _request(self, method, path, body=None, timeout=None, retries=3):
        req = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(body).encode() if body is not None else None,
            method=method,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        delay = 2.0
        for attempt in range(retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                    return json.loads(resp.read().decode())
            except urllib.error.HTTPError as e:
                detail = e.read().decode(errors="replace")[:500]
                if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise LLMError(f"HTTP {e.code} from {path}: {detail}") from e
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                # No network / DNS / refused / timed out: fail fast so the update is queued offline
                # instead of making the user wait through retries.
                raise ModelUnavailable(f"{OFFLINE_MARK} cannot reach {self.base_url}: {getattr(e, 'reason', e)}") from e

    def list_models(self):
        return [m["id"] for m in self._request("GET", "models").get("data", [])]

    def ping(self, timeout=6):
        """True if Nebius answers (cheap: lists models, no tokens)."""
        try:
            self._request("GET", "models", timeout=timeout, retries=0)
            return True
        except LLMError:
            return False

    def chat(self, system, user, json_mode=False, max_tokens=4096):
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": self.temperature,
            "max_tokens": max_tokens,
            **self.extra_body,
        }
        if json_mode and self._json_mode:
            body["response_format"] = {"type": "json_object"}
        try:
            data = self._request("POST", "chat/completions", body)
        except LLMError as e:
            # Some hosted models reject response_format; fall back to prompt-only JSON.
            if json_mode and self._json_mode and "HTTP 400" in str(e):
                self._json_mode = False
                body.pop("response_format", None)
                data = self._request("POST", "chat/completions", body)
            else:
                raise
        self.last_usage = data.get("usage")
        return data["choices"][0]["message"].get("content") or ""

    def chat_json(self, system, user):
        text = self.chat(system, user, json_mode=True)
        try:
            return extract_json(text), text
        except LLMError:
            retry = user + "\n\nYour previous reply was not valid JSON. Reply with ONLY the JSON object."
            text = self.chat(system, retry, json_mode=True)
            return extract_json(text), text


class ScriptedLLM:
    """Replays hand-written operations keyed by evidence id. For offline demos and tests only."""

    name = "scripted (offline, hand-written operations - not a model)"

    def __init__(self, script):
        self.script = script
        self.last_usage = None

    @classmethod
    def from_file(cls, path):
        with open(path, encoding="utf-8") as fh:
            return cls(json.load(fh))

    def chat_json(self, system, user):
        match = re.search(r"^id: (E\d+)$", user, flags=re.M)
        ops = self.script.get(match.group(1), []) if match else []
        payload = {"operations": ops or [{"op": "NOOP", "rationale": "no scripted operations"}]}
        return payload, json.dumps(payload)

    def chat(self, system, user, json_mode=False, max_tokens=0):
        raise LLMError("free-form questions need a live model (set NEBIUS_API_KEY)")
