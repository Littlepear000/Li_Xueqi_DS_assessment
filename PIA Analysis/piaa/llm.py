"""Thin LLM client with a deterministic mock.

Workflow steps call :meth:`LLMClient.complete_json` with a system prompt, a user
prompt and the name of the step. The real provider is the Anthropic Messages
API; the mock provider returns canned JSON shaped like the real answers so the
whole pipeline (and the web app) can be exercised without a key.

Every call is logged (prompt sizes, model, duration) so the web app can show
"raw prompts & responses" for a run.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from dataclasses import dataclass, field

from .config import LLMSettings


@dataclass
class LLMCall:
    step: str
    model: str
    input_chars: int
    output_chars: int
    seconds: float
    system: str = ""
    prompt: str = ""
    response: str = ""
    input_tokens: int = 0       # billed (non-cached) input tokens, as reported by the provider
    cached_tokens: int = 0      # input tokens served from the prompt cache
    output_tokens: int = 0
    cache_write_tokens: int = 0  # input tokens written to the prompt cache (Anthropic bills them at 1.25x the input price)
    from_cache: bool = False     # answer reused from the local response cache: no API call, no tokens

    def to_dict(self, include_text: bool = False) -> dict:
        d = {"step": self.step, "model": self.model, "input_chars": self.input_chars,
             "output_chars": self.output_chars, "seconds": round(self.seconds, 2),
             "input_tokens": self.input_tokens, "cached_tokens": self.cached_tokens, "output_tokens": self.output_tokens,
             "cache_write_tokens": self.cache_write_tokens, "from_cache": self.from_cache}
        if include_text:
            d.update({"system": self.system, "prompt": self.prompt, "response": self.response})
        return d


class LLMError(RuntimeError):
    pass


class LLMCancelled(LLMError):
    """Raised for every model call after the user pressed Stop."""


# USD per 1M tokens: (input cache miss, input cache hit, output). List prices, Nov 2026.
# DeepSeek bills half of these outside Beijing peak hours (Mon-Fri 09-12 and 14-18 Beijing time).
PRICES = {
    "claude-sonnet-4-5": (3.00, 0.30, 15.00),
    "claude-haiku-4-5": (1.00, 0.10, 5.00),
    "deepseek-flash": (0.30, 0.006, 1.20),
    "deepseek-v4-flash": (0.30, 0.006, 1.20),
    "deepseek-v4-pro": (1.32, 0.044, 3.96),
    "gpt-4.1-mini": (0.40, 0.10, 1.60),
}


CACHE_WRITE_FACTOR = {"claude": 1.25}   # model prefix -> multiplier of the input price for prompt-cache writes


def call_cost(c) -> float | None:
    """List-price cost of one call (None when the model is not in PRICES)."""
    price = PRICES.get(c.model)
    if price is None:
        return None
    write = next((f for k, f in CACHE_WRITE_FACTOR.items() if c.model.startswith(k)), 1.0)
    return (c.input_tokens * price[0] + c.cache_write_tokens * price[0] * write + c.cached_tokens * price[1] + c.output_tokens * price[2]) / 1e6


def usage_summary(calls: list) -> dict:
    """Totals over a list of :class:`LLMCall` plus a list-price cost estimate, priced call by call
    (steps may use different models). ``est_cost_usd`` is None when no call's model is in PRICES."""
    tot = {"calls": len(calls), "input_tokens": sum(c.input_tokens for c in calls), "cached_tokens": sum(c.cached_tokens for c in calls),
           "cache_write_tokens": sum(getattr(c, "cache_write_tokens", 0) for c in calls),
           "output_tokens": sum(c.output_tokens for c in calls), "seconds": round(sum(c.seconds for c in calls), 1),
           "reused_answers": sum(1 for c in calls if getattr(c, "from_cache", False))}
    models = list(dict.fromkeys(c.model for c in calls))
    tot["model"] = models[0] if len(models) == 1 else ", ".join(models)
    costs = [call_cost(c) for c in calls]
    tot["est_cost_usd"] = round(sum(x for x in costs if x is not None), 4) if any(x is not None for x in costs) else None
    return tot


def deepseek_peak_note(provider: str, now=None) -> str:
    """DeepSeek bills full price Mon-Fri 09-12 and 14-18 Beijing time and half price otherwise."""
    if provider != "deepseek":
        return ""
    import datetime as dt
    bj = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone(dt.timedelta(hours=8)))
    peak = bj.weekday() < 5 and (9 <= bj.hour < 12 or 14 <= bj.hour < 18)
    if not peak:
        return "[piaa] DeepSeek off-peak now (half price)"
    nxt = 12 if bj.hour < 12 else 18
    return f"[piaa] note: DeepSeek PEAK hours now (full price) until {nxt}:00 Beijing time; the same run is half price outside Mon-Fri 09-12 / 14-18 Beijing"


# Prompt-cache warm-up: the first call that carries a given system prompt runs alone; parallel calls
# with the same system prompt wait for it and then read the cache instead of each writing it.
_WARM_TTL = 240          # seconds; the Anthropic cache lives 5 minutes and is refreshed on every read
_WARM_LOCK = threading.Lock()
_WARM: dict = {}         # (provider, model, sha of system) -> [lock, time of last successful call]


_JSON_BLOCK = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json(text: str):
    """Pull the first JSON object/array out of a model answer."""
    m = _JSON_BLOCK.search(text)
    candidate = m.group(1) if m else text
    candidate = candidate.strip()
    # trim leading prose
    for opener in ("{", "["):
        i = candidate.find(opener)
        if i >= 0:
            candidate = candidate[i:]
            break
    # trim trailing prose
    last = max(candidate.rfind("}"), candidate.rfind("]"))
    if last >= 0:
        candidate = candidate[: last + 1]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        # Typical failure: an unescaped quote inside a verbatim evidence sentence.
        try:
            from json_repair import repair_json
        except ImportError:  # pragma: no cover
            raise
        repaired = repair_json(candidate, return_objects=True)
        if repaired in ("", None):
            raise
        return repaired


@dataclass
class LLMClient:
    settings: LLMSettings
    calls: list[LLMCall] = field(default_factory=list)
    _client: object = None
    cancel: object = None   # optional threading.Event: once set, every further call raises LLMCancelled

    # ------------------------------------------------------------------
    def complete(self, step: str, system: str, prompt: str, cache_system: bool = False, json_mode: bool = False) -> str:
        """``cache_system=True`` marks the system prompt as a prompt-cache block (Anthropic), so a
        long constant prefix (e.g. a taxonomy) is billed once and re-read cheaply. ``json_mode``
        asks OpenAI-compatible providers for a JSON object response."""
        if self.cancel is not None and self.cancel.is_set():
            raise LLMCancelled("run stopped by user")
        if len(prompt) > self.settings.max_input_chars:
            prompt = prompt[: self.settings.max_input_chars] + "\n\n[TRUNCATED]"
        model = self.settings.model_for(step)
        t0 = time.time()
        usage = {}
        if self.settings.provider == "mock":
            text = _mock_response(step, prompt)
        elif self.settings.provider not in ("anthropic", "deepseek", "openai"):
            raise LLMError(f"unknown provider {self.settings.provider}")
        elif self.settings.warm_cache and (cache_system or self.settings.provider == "deepseek"):
            text, usage = self._warm_call(model, system, prompt, cache_system, json_mode)
        else:
            text, usage = self._provider_call(model, system, prompt, cache_system, json_mode)
        self.calls.append(LLMCall(step, model, len(system) + len(prompt), len(text), time.time() - t0, system, prompt, text,
                                  usage.get("input", 0), usage.get("cached", 0), usage.get("output", 0), usage.get("cache_write", 0)))
        return text

    def _provider_call(self, model, system, prompt, cache_system, json_mode):
        if self.settings.provider == "anthropic":
            return self._anthropic(system, prompt, cache_system, model)
        return self._openai_compatible(system, prompt, json_mode, model)

    def _warm_call(self, model, system, prompt, cache_system, json_mode):
        """Run alone if no call with this system prompt succeeded in the last few minutes, so the
        calls queued behind it hit the prompt cache. Same request, same answer - only the order changes."""
        key = (self.settings.provider, model, hashlib.sha256(system.encode()).hexdigest())
        with _WARM_LOCK:
            entry = _WARM.setdefault(key, [threading.Lock(), 0.0])
        if time.time() - entry[1] > _WARM_TTL:
            with entry[0]:
                if time.time() - entry[1] > _WARM_TTL:
                    out = self._provider_call(model, system, prompt, cache_system, json_mode)
                    entry[1] = time.time()
                    return out
        out = self._provider_call(model, system, prompt, cache_system, json_mode)
        entry[1] = time.time()
        return out

    # ------------------------------------------------------------------
    def _cache_path(self, step: str, system: str, prompt: str):
        st = self.settings
        if not (st.response_cache and st.response_cache_dir) or st.provider == "mock":
            return None
        from pathlib import Path
        key = hashlib.sha256(json.dumps([st.provider, st.model_for(step), st.temperature, st.max_tokens, system, prompt]).encode()).hexdigest()
        return Path(st.response_cache_dir) / key[:2] / f"{key}.json"

    def _cache_get(self, step, system, prompt):
        path = self._cache_path(step, system, prompt)
        if path is None or not path.exists():
            return None
        try:
            text = json.loads(path.read_text(encoding="utf-8"))["text"]
            data = extract_json(text)
        except Exception:
            return None
        self.calls.append(LLMCall(step, self.settings.model_for(step), len(system) + len(prompt), len(text), 0.0, system, prompt, text, from_cache=True))
        return data

    def _cache_put(self, step, system, prompt, text):
        path = self._cache_path(step, system, prompt)
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(f".{threading.get_ident()}.tmp")
            tmp.write_text(json.dumps({"step": step, "model": self.settings.model_for(step), "text": text}), encoding="utf-8")
            tmp.replace(path)
        except OSError:
            pass

    def usage(self) -> dict:
        return usage_summary(self.calls)

    def complete_json(self, step: str, system: str, prompt: str, retries: int = 1, cache_system: bool = False):
        hit = self._cache_get(step, system, prompt)
        if hit is not None:
            return hit
        last_err = None
        for attempt in range(retries + 1):
            text = self.complete(step, system, prompt if attempt == 0 else prompt + "\n\nReturn ONLY valid JSON.", cache_system, json_mode=True)
            try:
                data = extract_json(text)
                self._cache_put(step, system, prompt, text)   # stored under the original prompt, only once it parses
                return data
            except (json.JSONDecodeError, ValueError) as e:  # pragma: no cover - depends on model
                last_err = e
        raise LLMError(f"step {step}: model did not return valid JSON ({last_err})")

    # ------------------------------------------------------------------
    def _anthropic(self, system: str, prompt: str, cache_system: bool = False, model: str | None = None) -> str:
        if self._client is None:
            try:
                import anthropic
            except ImportError as e:  # pragma: no cover
                raise LLMError("pip install anthropic") from e
            if not self.settings.api_key:
                raise LLMError("ANTHROPIC_API_KEY is not set (or use provider='mock')")
            self._client = anthropic.Anthropic(api_key=self.settings.api_key)
        sys_arg = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}] if cache_system else system
        kwargs = dict(model=model or self.settings.model, max_tokens=self.settings.max_tokens, system=sys_arg,
                      messages=[{"role": "user", "content": prompt}])
        last = None
        for attempt in range(6):
            try:
                try:
                    resp = self._client.messages.create(temperature=self.settings.temperature, **kwargs)
                except TypeError:  # newer SDKs may drop the temperature argument
                    resp = self._client.messages.create(**kwargs)
                break
            except Exception as e:  # rate limit / overloaded / network: back off and retry
                last = e
                name = type(e).__name__
                if attempt == 5 or not any(k in name for k in ("RateLimit", "Overloaded", "APIConnection", "APITimeout", "InternalServer", "APIStatus")):
                    raise
                time.sleep(min(60, 2 ** attempt * 3))
        else:  # pragma: no cover
            raise last
        u = getattr(resp, "usage", None)
        usage = {"input": getattr(u, "input_tokens", 0) or 0, "cached": getattr(u, "cache_read_input_tokens", 0) or 0,
                 "cache_write": getattr(u, "cache_creation_input_tokens", 0) or 0,
                 "output": getattr(u, "output_tokens", 0) or 0}
        return "".join(block.text for block in resp.content if getattr(block, "type", "") == "text"), usage

    def _openai_compatible(self, system: str, prompt: str, json_mode: bool = False, model: str | None = None) -> tuple[str, dict]:
        """Chat-completions call over plain HTTPS (DeepSeek and any OpenAI-compatible endpoint)."""
        import requests

        st = self.settings
        if not st.api_key:
            raise LLMError(f"{st.key_env_var} is not set (or use provider='mock')")
        url = st.base_url.rstrip("/") + "/chat/completions"
        body = {"model": model or st.model, "temperature": st.temperature, "max_tokens": st.max_tokens, "stream": False,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
        if json_mode:
            body["response_format"] = {"type": "json_object"}   # DeepSeek requires the word "json" in the prompt; our prompts carry it
        if st.provider == "deepseek":
            body["thinking"] = {"type": "disabled"}             # extraction is not a reasoning task; thinking tokens would bill as output
        headers = {"Authorization": f"Bearer {st.api_key}", "Content-Type": "application/json"}
        last = None
        for attempt in range(6):
            try:
                r = requests.post(url, json=body, headers=headers, timeout=600)
                if r.status_code in (429, 500, 502, 503, 504):
                    raise LLMError(f"HTTP {r.status_code}: {r.text[:200]}")
                if r.status_code != 200:
                    raise LLMError(f"HTTP {r.status_code}: {r.text[:300]}")  # 400/401/402: not retried
                data = r.json()
                break
            except (requests.RequestException, LLMError) as e:
                last = e
                retryable = isinstance(e, requests.RequestException) or str(e).startswith(("HTTP 429", "HTTP 5"))
                if attempt == 5 or not retryable:
                    raise
                time.sleep(min(60, 2 ** attempt * 3))
        else:  # pragma: no cover
            raise last
        choice = (data.get("choices") or [{}])[0]
        text = (choice.get("message") or {}).get("content") or ""
        u = data.get("usage") or {}
        cached = u.get("prompt_cache_hit_tokens") or (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
        usage = {"input": max(0, (u.get("prompt_tokens") or 0) - cached), "cached": cached, "output": u.get("completion_tokens") or 0}
        return text, usage


# ----------------------------------------------------------------------------
# Mock provider: shaped like the real answers, derived from the prompt so
# that evidence sentences really exist in the document.
# ----------------------------------------------------------------------------
def _mock_response(step: str, prompt: str) -> str:
    if step == "extract" and "=== UNITS ===" in prompt:  # workflow v5: one practice per unit that carries a digital cue
        units = []
        for m in re.finditer(r"--- (U\d+) \([^\n]*\n((?:\[\1\.s\d+\][^\n]*\n?)+)", prompt):
            uid, body = m.group(1), m.group(2)
            picked = [(sid, txt) for sid, txt in re.findall(r"\[(U\d+\.s\d+)\] ([^\n]+)", body)
                      if re.search(r"digital|mobile|platform|online|satellite|data|system", txt, re.IGNORECASE)]
            if picked:
                sid, txt = picked[0]
                adoption = "apply" if re.search(r"will (?:finance|support|establish|develop|deploy)|component|is financing", txt, re.IGNORECASE) else "prospect"
                cat = "Financial" if re.search(r"mobile money|payment|voucher|credit", txt, re.IGNORECASE) else "Technological"
                units.append({"unit_id": uid, "approaches": [{"practice": "mock " + " ".join(txt.split()[:6]), "what_is_done": "mock: " + txt[:80],
                                                              "category": cat, "adoption": adoption, "evidence": [sid], "reason": "mock"}]})
            else:
                units.append({"unit_id": uid, "approaches": []})
        return json.dumps({"units": units})
    if step == "validate":  # workflow v5 judge: accept everything; the first candidate of a first-round call asks for wider context
        ids = re.findall(r"^--- (A\d+)$", prompt, re.MULTILINE)
        vals = {aid: dict(zip(("practice", "category", "adoption"), m)) for aid, *m in
                re.findall(r"^--- (A\d+)\npractice: ([^\n]*)\n[^\n]*\ncategory: ([^;]*); adoption: ([^\n]*)", prompt, re.MULTILINE)}
        out = []
        for k, aid in enumerate(ids):
            if k == 0 and "=== CANDIDATE APPROACHES ===" in prompt:
                out.append({"approach_id": aid, "verdict": "expand", "reason": "mock: need more context"})
            else:
                out.append({"approach_id": aid, "verdict": "accept", **vals.get(aid, {}), "reason": "mock"})
        return json.dumps({"results": out})
    if step == "merge":
        ids = re.findall(r"^\[(A\d+)\]", prompt, re.MULTILINE)
        return json.dumps({"groups": [{"practice": "", "members": [i]} for i in ids]})
    if step == "extract":
        # pick up to two sentences from the prompt's document excerpt that contain a digital cue
        excerpt = prompt.split("=== DOCUMENT TEXT ===", 1)[-1]
        sents = re.split(r"(?<=[.!?])\s+", excerpt)
        cues = ("digital", "platform", "data", "online", "mobile", "AI", "system", "electronic", "e-")
        picked = [s.strip() for s in sents if 60 < len(s) < 400 and any(c in s for c in cues)][:2]
        items = []
        for i, s in enumerate(picked, 1):
            items.append({"approach_name": f"Mock approach {i}: " + " ".join(s.split()[:6]),
                          "description": "Mock description derived from the document excerpt.",
                          "evidence_sentence": s, "document_guid": _guid_from_prompt(prompt),
                          "why_innovative": "Mock rationale: the sentence describes a digital practice."})
        return json.dumps({"innovative": "Yes" if items else "No", "approaches": items})
    if step == "match":
        return json.dumps({"category": {"code": "P3", "confidence": 0.7, "rationale": "mock"},
                           "category_solution": {"code": "S6", "confidence": 0.6, "rationale": "mock"},
                           "sector": {"value": _first_option(prompt, "SECTORS"), "confidence": 0.6, "rationale": "mock"},
                           "theme": {"value": _first_option(prompt, "THEMES"), "confidence": 0.6, "rationale": "mock"}})
    if step == "validate":
        return json.dumps({"approaches": []})  # empty => everything confirmed as-is
    if step == "classify" and "cues=" in prompt:  # workflow v4 format
        out = []
        for m in re.finditer(r"\[(C\d+)\] doc=[^\n]*\n\s*BEFORE:[^\n]*\n\s*SENTENCE: ([^\n]+)", prompt):
            cid, sent = m.group(1), m.group(2)
            if any(c in sent.lower() for c in ("digital", "mobile", "platform", "online", "satellite", "data")):
                adoption = "apply" if re.search(r"will (?:finance|support|establish|develop|deploy)|component|is financing", sent, re.IGNORECASE) else "prospect"
                cat = "Financial" if re.search(r"mobile money|payment|voucher|credit", sent, re.IGNORECASE) else "Technological"
                out.append({"candidate_id": cid, "matches": [{"category": cat, "adoption": adoption, "label": "mock " + " ".join(sent.split()[:4]), "reason": "mock"}]})
            else:
                out.append({"candidate_id": cid, "matches": [], "excluded_reason": "mock: no digital innovation"})
        return json.dumps({"results": out})
    if step == "codes":
        ids = re.findall(r"^\[([AP]\d+)\]", prompt, re.MULTILINE)
        key = "approach_id" if ids and ids[0].startswith("A") else "passage_id"
        return json.dumps({"results": [{key: i, "sector": _first_option(prompt, "SECTORS (projects.csv)"), "theme": _first_option(prompt, "THEMES (projects.csv)"), "reason": "mock"} for i in ids]})
    if step == "classify":
        # one match per candidate that carries a digital cue; code = first candidate code listed for it
        out = []
        for m in re.finditer(r"\[(C\d+)\] \(candidates: ([0-9, ]+)\)[^\n]*\n\s*BEFORE:[^\n]*\n\s*SENTENCE: ([^\n]+)", prompt):
            cid, codes, sent = m.group(1), m.group(2).split(",")[0].strip(), m.group(3)
            if any(c in sent.lower() for c in ("digital", "data", "online", "mobile", "system", "platform", "electronic", "ai ")):
                out.append({"candidate_id": cid, "matches": [{"code": codes, "evidence_level": "L2", "status": "planned", "reason": "mock"}]})
            else:
                out.append({"candidate_id": cid, "matches": [], "excluded_reason": "mock: no digital activity"})
        return json.dumps({"results": out})
    if step == "solution":
        m = re.search(r"Candidate solutions: ([A-Z0-9]+)", prompt)
        return json.dumps({"solution": m.group(1) if m else "Unmapped", "reason": "mock"})
    if step == "adoption":
        applied = bool(re.search(r"will (?:finance|support|establish|develop|deploy)|is financing|component", prompt, re.IGNORECASE))
        return json.dumps({"adoption": "applied" if applied else "mentioned", "mention_for": "" if applied else "aspiration_or_vision",
                           "evidence_level": "L2", "confidence": 0.7, "reason": "mock"})
    if step == "replication":
        return json.dumps({"links": []})
    return "{}"


def _guid_from_prompt(prompt: str) -> str:
    m = re.search(r"guid=(\d+)", prompt)
    return m.group(1) if m else ""


def _first_option(prompt: str, header: str) -> str:
    m = re.search(rf"=== {header} ===[^\n]*\n- ([^\n]+)", prompt)
    val = m.group(1) if m else ""
    return re.sub(r"\s*\(\d+(?:\.\d+)?%\)\s*$", "", val)
