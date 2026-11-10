"""
Policy-aware model routing across local and cloud providers.

    router = ModelRouter(settings)
    router.set_sensitivity(True)                      # confidential documents in this request
    routed = router.chat("master", messages, tools=..., complexity="low")
    routed.routing  -> {"strategy", "candidates", "excluded": {entry: reason}, "attempts"}

Selection, per role (master | fast | verifier | vision), in this order:
  1. candidate chain (llm/catalog.chain_for_settings): MANUAL_MODEL first, then the configured priority
     order (env override > profile default), plus OpenAI / Anthropic / Bedrock / Ollama when configured;
  2. exclusions: provider not configured · LLM_MODE (local → only Ollama, cloud → no Ollama) ·
     DATA SENSITIVITY (confidential/PII requests never reach a cloud model unless ALLOW_SENSITIVE_CLOUD=true,
     and then only providers in CLOUD_PROVIDERS_ALLOWED) · context window too small · circuit breaker open;
  3. ordering (ROUTING_STRATEGY): priority (default) · cost · latency (observed EWMA) ·
     auto (= cost+latency for low-complexity requests, priority otherwise).
Execution: each candidate is retried LLM_MAX_RETRIES times with exponential backoff for transient errors
(timeout, connection, 5xx); a 429 is retried once only if Retry-After ≤ 2 s, otherwise the next candidate
is tried. Auth errors, moderation refusals and malformed requests stop at once. Consecutive failures open
a per-model circuit for CIRCUIT_COOLDOWN_S. Tokens, cost, latency and failures are tracked per model.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from config.settings import Settings, get_logger
from llm.catalog import LOCAL_PROVIDERS, PROVIDERS, ROLES, VISION_CAPABLE, split
from llm.pricing import blended, context_window
from llm.providers import FALLBACK_KINDS, ChatResult, KeyInfo, LLMError, make_provider

log = get_logger("router")

__all__ = ["ModelRouter", "RoutedResult", "ProviderStatus", "ROLES", "USAGE", "reset_state"]

_ROLE_REASONING = {"fast": "none", "verifier": "none", "vision": "none"}
_RETRY_KINDS = {"timeout", "connection", "unavailable"}
_USED_FOR = {"groq": "text answers (free tier)", "openrouter": "images (figures, scanned pages)",
             "ollama": "local / offline answers", "openai": "cloud answers", "anthropic": "cloud answers",
             "bedrock": "cloud answers (AWS)"}


@dataclass
class ProviderStatus:
    name: str
    label: str
    configured: bool
    connected: bool = False
    models: List[str] = field(default_factory=list)
    message: str = ""
    key: Optional[KeyInfo] = None
    used_for: str = ""
    local: bool = False


@dataclass
class RoutedResult:
    result: ChatResult
    attempts: List[Tuple[str, str, str]]  # (provider, model, outcome)
    latency_ms: float
    routing: Dict[str, Any] = field(default_factory=dict)

    @property
    def cost(self) -> float:
        return self.result.cost


# ------------------------------------------------------------- process-wide state
_LOCK = threading.Lock()
_CIRCUIT: Dict[str, Dict[str, float]] = {}     # entry -> {"fails", "open_until"}
_LATENCY: Dict[str, float] = {}                # entry -> EWMA ms
USAGE: Dict[str, Dict[str, float]] = {}        # entry -> calls, failures, tokens, cost, latency_ms


def reset_state() -> None:
    with _LOCK:
        _CIRCUIT.clear()
        _LATENCY.clear()
        USAGE.clear()


def _record(entry: str, ok: bool, ms: float = 0.0, tokens: int = 0, cost: float = 0.0,
            threshold: int = 3, cooldown: float = 60.0, outcome: str = "") -> None:
    try:
        from monitoring.metrics import observe_llm
        observe_llm(entry, "ok" if ok else (outcome or "error"))
    except Exception:
        pass
    with _LOCK:
        u = USAGE.setdefault(entry, {"calls": 0, "failures": 0, "tokens": 0, "cost": 0.0, "latency_ms": 0.0})
        u["calls"] += 1
        c = _CIRCUIT.setdefault(entry, {"fails": 0, "open_until": 0.0})
        if ok:
            u["tokens"] += tokens
            u["cost"] += cost
            u["latency_ms"] += ms
            c["fails"], c["open_until"] = 0, 0.0
            _LATENCY[entry] = ms if entry not in _LATENCY else 0.7 * _LATENCY[entry] + 0.3 * ms
        else:
            u["failures"] += 1
            c["fails"] += 1
            if c["fails"] >= threshold:
                c["open_until"] = time.time() + cooldown
                log.warning("circuit opened for %s (%d consecutive failures)", entry, int(c["fails"]))


def circuit_open(entry: str) -> bool:
    with _LOCK:
        return _CIRCUIT.get(entry, {}).get("open_until", 0.0) > time.time()


def _estimate_tokens(messages: Sequence[Dict[str, Any]], max_tokens: int) -> int:
    chars = 0
    for m in messages:
        c = m.get("content")
        chars += len(c) if isinstance(c, str) else sum(len(str(p.get("text", ""))) for p in c or [])
    return chars // 4 + max_tokens


class ModelRouter:
    def __init__(self, settings: Settings, sensitive: bool = False):
        self.settings = settings
        self.sensitive = sensitive
        self.complexity_hint = "normal"          # set per question by the pipeline (low | normal | high)
        self.last_routing: Dict[str, Any] = {}   # explanation of the most recent choice (shown in the UI)
        self.by_name = {name: make_provider(name, settings) for name in PROVIDERS}
        self.providers = [p for p in self.by_name.values() if p.configured()]

    def set_sensitivity(self, sensitive: bool) -> None:
        self.sensitive = bool(sensitive)

    # ------------------------------------------------------------------ planning
    def _exclusion(self, provider_name: str, model: str, role: str, need_tokens: int) -> str:
        s = self.settings
        p = self.by_name.get(provider_name)
        if p is None:
            return "unknown provider"
        if not p.configured():
            return "not configured"
        local = provider_name in LOCAL_PROVIDERS
        if s.llm_mode == "local" and not local:
            return "LLM_MODE=local"
        if s.llm_mode == "cloud" and local:
            return "LLM_MODE=cloud"
        if not local:
            if self.sensitive and not s.allow_sensitive_cloud:
                return "sensitive data: cloud models not allowed"
            if s.cloud_providers_allowed and provider_name not in s.cloud_providers_allowed:
                return "provider not allowed by policy"
        if role == "vision" and provider_name not in VISION_CAPABLE and not (local and s.ollama_vision_model):
            return "no vision support"
        if need_tokens and context_window(provider_name, model) < need_tokens:
            return f"context window too small (needs ~{need_tokens} tokens)"
        if circuit_open(f"{provider_name}:{model}"):
            return "circuit open (recent failures)"
        return ""

    def plan(self, role: str, need_tokens: int = 0, complexity: str = "normal") -> Tuple[list, Dict[str, str]]:
        cands, excluded, circuit_only = [], {}, []
        for entry in self.settings.models_for(role):
            name, model = split(entry)
            why = self._exclusion(name, model, role, need_tokens)
            if why.startswith("circuit open"):
                circuit_only.append((self.by_name[name], model, entry))
            if why:
                excluded[entry] = why
            else:
                cands.append((self.by_name[name], model, entry))
        if not cands and circuit_only:  # everything is cooling down: still try rather than fail
            cands = circuit_only
        strategy = self.settings.routing_strategy
        if strategy == "auto":
            strategy = "cost" if complexity == "low" else "priority"
        if strategy == "cost":
            cands.sort(key=lambda c: (blended(c[0].name, c[1]), _LATENCY.get(c[2], 1e9)))
        elif strategy == "latency":
            cands.sort(key=lambda c: _LATENCY.get(c[2], 1e9))
        return cands, excluded

    def chain(self, role: str):
        """[(provider, model)] usable for the role right now (after policy filters)."""
        return [(p, m) for p, m, _ in self.plan(role)[0]]

    def has_role(self, role: str) -> bool:
        return bool(self.chain(role))

    @property
    def enabled(self) -> bool:
        return bool(self.providers)

    # -------------------------------------------------------------------- chat
    def chat(self, role: str, messages: List[Dict[str, Any]], tools: Optional[List[Dict]] = None,
             tool_choice: str = "auto", images: Optional[Sequence[bytes]] = None,
             max_tokens: Optional[int] = None, reasoning: Optional[str] = None,
             json_mode: bool = False, temperature: Optional[float] = None,
             complexity: str = "normal") -> RoutedResult:
        s = self.settings
        t0 = time.perf_counter()
        max_tokens = max_tokens or s.max_output_tokens
        if complexity == "normal":
            complexity = self.complexity_hint
        cands, excluded = self.plan(role, _estimate_tokens(messages, max_tokens), complexity)
        routing: Dict[str, Any] = {"role": role, "strategy": s.routing_strategy, "mode": s.llm_mode,
                                   "complexity": complexity, "sensitive": self.sensitive,
                                   "candidates": [c[2] for c in cands], "excluded": excluded}
        self.last_routing = routing
        attempts: List[Tuple[str, str, str]] = []
        if not cands:
            if self.sensitive and any("sensitive" in v for v in excluded.values()):
                msg = ("This request involves confidential documents, which may only be processed by a local "
                       "model, and no local model (Ollama) is configured. Set OLLAMA_BASE_URL or ask an admin.")
            elif s.llm_mode == "local":
                msg = "Local-only mode is on but no local model is configured. Set OLLAMA_BASE_URL."
            elif role == "vision":
                msg = "No vision model is configured (OPENROUTER_API_KEY, OpenAI, Anthropic or OLLAMA_VISION_MODEL)."
            else:
                msg = ("No AI model is configured for this task. Add GROQ_API_KEY (free at console.groq.com/keys), "
                       "another provider key, or OLLAMA_BASE_URL for a local model.")
            err = LLMError(msg, "no_provider")
            err.routing = routing  # type: ignore[attr-defined]
            raise err
        effort = reasoning or _ROLE_REASONING.get(role) or s.reasoning_effort
        temp = s.llm_temperature if temperature is None else temperature
        last: Optional[LLMError] = None
        for provider, model, entry in cands:
            for attempt in range(s.llm_max_retries + 1):
                t_call = time.perf_counter()
                try:
                    result = provider.chat(model, messages, tools=tools, tool_choice=tool_choice, temperature=temp,
                                           max_tokens=max_tokens, images=images, reasoning=effort,
                                           json_mode=json_mode)
                    ms = (time.perf_counter() - t_call) * 1000
                    _record(entry, True, ms, result.tokens, result.cost, s.circuit_failures, s.circuit_cooldown_s)
                    attempts.append((provider.name, model, "ok"))
                    routing["attempts"] = attempts
                    routing["chosen"] = entry
                    return RoutedResult(result, attempts, (time.perf_counter() - t0) * 1000, routing)
                except LLMError as exc:
                    _record(entry, False, threshold=s.circuit_failures, cooldown=s.circuit_cooldown_s,
                            outcome=exc.kind)
                    attempts.append((provider.name, model, exc.kind))
                    last = exc
                    if exc.kind not in FALLBACK_KINDS:
                        exc.routing = routing  # type: ignore[attr-defined]
                        raise
                    wait = float(getattr(exc, "retry_after", 0.0) or 0.0)
                    retry = attempt < s.llm_max_retries and (
                        exc.kind in _RETRY_KINDS or (exc.kind == "rate_limit" and 0 < wait <= 2.0))
                    if not retry:
                        break
                    time.sleep(wait if exc.kind == "rate_limit" else min(0.4 * 2 ** attempt, 4.0))
            log.warning("%s failed (%s); trying the next model for '%s'", entry, last.kind if last else "?", role)
        assert last is not None
        last.user_message += " No other model in the chain could answer."
        last.routing = routing  # type: ignore[attr-defined]
        raise last

    # ------------------------------------------------------------------ status
    def status(self) -> List[ProviderStatus]:
        out = []
        for name, p in self.by_name.items():
            st = ProviderStatus(name, p.label, p.configured(), used_for=_USED_FOR.get(name, ""),
                                local=name in LOCAL_PROVIDERS)
            if st.configured:
                try:
                    st.key = p.key_info()
                    st.connected = True
                except LLMError as exc:
                    st.message = exc.user_message
                except Exception as exc:  # e.g. boto3 credential errors
                    st.message = f"{type(exc).__name__}"
                if st.connected:
                    try:
                        st.models = p.list_models()
                    except Exception:
                        st.models = []
            out.append(st)
        return out

    def health(self) -> Dict[str, bool]:
        """Cheap liveness per configured provider (used by /readyz and the Models page)."""
        return {s.name: s.connected for s in self.status() if s.configured}
