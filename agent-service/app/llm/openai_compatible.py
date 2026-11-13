import json

import httpx
from pydantic import ValidationError

from app.agent.prompts import phrase_selection_prompt, task_understanding_prompt
from app.domain.schemas import LLMTaskProposal


PHRASES = {
    "closed": {
        "brief": "This audit is recorded as closed. Review the cited facts and unresolved policy note.",
        "review": "The source record shows a closed audit; consult the facts and open policy note for context.",
    },
    "active": {
        "brief": "This audit is in an active lifecycle stage. Review the cited facts and next steps.",
        "review": "The audit remains active; the deterministic findings below identify the recorded work still in view.",
    },
    "attention": {
        "brief": "The records show items to address. Review the recommendations and source references.",
        "review": "Some recorded items need attention; use the cited facts to review the suggested next steps.",
    },
    "overview": {
        "brief": "Review the audit facts and cited source records below.",
        "review": "The following summary is based on the supplied source records.",
    },
}

_SAFE_PROVIDER_CODES = {
    "INVALID_ARGUMENT", "FAILED_PRECONDITION", "OUT_OF_RANGE", "UNAUTHENTICATED",
    "PERMISSION_DENIED", "NOT_FOUND", "RESOURCE_EXHAUSTED", "CANCELLED", "ABORTED",
    "INTERNAL", "UNAVAILABLE", "DEADLINE_EXCEEDED", "UNKNOWN", "DATA_LOSS",
    "invalid_api_key", "insufficient_quota", "rate_limit_exceeded", "model_not_found",
    "invalid_request_error", "server_error",
}


class OpenAICompatibleExplainer:
    """Optional phrase selector; model output never carries QMS business facts."""

    def __init__(self, api_key: str, base_url: str, model: str, timeout: float = 8.0, max_tokens: int = 24) -> None:
        self._api_key = api_key
        self._url = base_url.rstrip("/")
        if not self._url.endswith("/chat/completions"):
            self._url += "/chat/completions"
        self._model = model
        self._timeout = timeout
        self._max_tokens = max_tokens

    def explain(self, category: str) -> str:
        choices = PHRASES[category]
        prompt = phrase_selection_prompt(category)
        response = httpx.post(
            self._url,
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={
                "model": self._model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens": self._max_tokens,
                "response_format": {"type": "json_object"},
            },
            timeout=self._timeout,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        choice = json.loads(content).get("choice")
        if choice not in choices:
            raise ValueError("LLM returned an unsupported phrase selection")
        # Always map to locally reviewed text. Never return model-authored prose.
        return choices[choice]


class OpenAICompatibleTaskPlanner:
    """Single-call natural-language parser; output is strictly schema validated."""

    def __init__(self, api_key: str, base_url: str, model: str, timeout: float = 8.0, max_tokens: int = 120) -> None:
        self._api_key = api_key
        self._url = base_url.rstrip("/")
        if not self._url.endswith("/chat/completions"):
            self._url += "/chat/completions"
        self._model = model
        self._timeout = timeout
        self._max_tokens = max_tokens

    def propose(self, request_text: str) -> LLMTaskProposal:
        try:
            response = httpx.post(
                self._url,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self._model,
                    "messages": [{"role": "user", "content": task_understanding_prompt(request_text)}],
                    "max_tokens": self._max_tokens,
                    "response_format": {"type": "json_object"},
                },
                timeout=self._timeout,
            )
            response.raise_for_status()
            try:
                content = response.json()["choices"][0]["message"]["content"]
            except (ValueError, KeyError, IndexError, TypeError):
                raise LLMPlannerFailure(
                    "invalid_json", http_status_code=response.status_code,
                    sanitized_error_message="Provider response did not contain a valid chat-completion JSON result.",
                ) from None
            try:
                return LLMTaskProposal.model_validate_json(content)
            except ValidationError as exc:
                reason = "invalid_json" if any(
                    error.get("type") == "json_invalid" for error in exc.errors()
                ) else "schema_validation_error"
                message = (
                    "Provider response was not valid JSON."
                    if reason == "invalid_json" else "Provider JSON did not match the task proposal schema."
                )
                raise LLMPlannerFailure(
                    reason, http_status_code=response.status_code,
                    sanitized_error_message=message,
                ) from None
        except LLMPlannerFailure:
            raise
        except httpx.TimeoutException:
            raise LLMPlannerFailure("timeout", sanitized_error_message="LLM provider request timed out.") from None
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            reason = "authentication_error" if status in {401, 403} else "rate_limited" if status == 429 else "provider_error"
            raise LLMPlannerFailure(
                reason,
                http_status_code=status,
                provider_error_code=_safe_provider_error_code(exc.response),
                sanitized_error_message=_safe_provider_error_message(status),
            ) from None
        except Exception:
            # Do not retain or surface provider exception text, headers, or body.
            raise LLMPlannerFailure(
                "provider_error", sanitized_error_message="LLM provider request failed before a response was received."
            ) from None


class LLMPlannerFailure(Exception):
    """A sanitized planner failure category safe for task diagnostics."""

    def __init__(
        self,
        reason: str,
        *,
        http_status_code: int | None = None,
        provider_error_code: str | None = None,
        sanitized_error_message: str | None = None,
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.http_status_code = http_status_code
        self.provider_error_code = provider_error_code if provider_error_code in _SAFE_PROVIDER_CODES else None
        safe_messages = {
            _safe_planner_message(reason),
            "Provider rejected the request; check the model and supported parameters.",
            "Provider denied access to this model or endpoint.",
            "Provider endpoint or model was not found.",
            "Provider returned a server error.",
            "Provider rejected the request.",
            "Provider response did not contain a valid chat-completion JSON result.",
        }
        self.sanitized_error_message = (
            sanitized_error_message
            if sanitized_error_message in safe_messages
            else _safe_planner_message(reason)
        )


def _safe_provider_error_code(response: httpx.Response) -> str | None:
    """Extract only a provider code from JSON when it matches a fixed allowlist."""
    try:
        error = response.json().get("error", {})
        if not isinstance(error, dict):
            return None
        for candidate in (error.get("status"), error.get("code"), error.get("type")):
            if isinstance(candidate, str) and candidate in _SAFE_PROVIDER_CODES:
                return candidate
    except (ValueError, TypeError, AttributeError):
        pass
    return None


def _safe_provider_error_message(status: int) -> str:
    if status == 400:
        return "Provider rejected the request; check the model and supported parameters."
    if status == 401:
        return "Provider authentication failed."
    if status == 403:
        return "Provider denied access to this model or endpoint."
    if status == 404:
        return "Provider endpoint or model was not found."
    if status == 429:
        return "Provider quota or rate limit was exceeded."
    if status >= 500:
        return "Provider returned a server error."
    return "Provider rejected the request."


def _safe_planner_message(reason: str) -> str:
    return {
        "authentication_error": "Provider authentication failed.",
        "rate_limited": "Provider quota or rate limit was exceeded.",
        "timeout": "LLM provider request timed out.",
        "invalid_json": "Provider response was not valid JSON.",
        "schema_validation_error": "Provider JSON did not match the task proposal schema.",
        "provider_error": "LLM provider request failed.",
    }.get(reason, "LLM provider request failed.")


def configured_explainer():
    """Create an adapter only when all settings are present; otherwise stay deterministic."""
    import os

    key = os.getenv("LLM_API_KEY", "").strip()
    base_url = os.getenv("LLM_BASE_URL", "").strip()
    model = os.getenv("LLM_MODEL", "").strip()
    if not (key and base_url and model):
        return None
    timeout = _setting_float("LLM_TIMEOUT_SECONDS", 8.0, minimum=0.1, maximum=8.0)
    max_tokens = _setting_int("LLM_MAX_OUTPUT_TOKENS", 120, minimum=16, maximum=512)
    return OpenAICompatibleExplainer(key, base_url, model, timeout=timeout, max_tokens=max_tokens)


def configured_task_planner():
    """No implicit provider or paid fallback: configure one endpoint explicitly."""
    import os

    key = os.getenv("LLM_API_KEY", "").strip()
    base_url = os.getenv("LLM_BASE_URL", "").strip()
    model = os.getenv("LLM_MODEL", "").strip()
    if not (key and base_url and model):
        return None
    timeout = _setting_float("LLM_TIMEOUT_SECONDS", 8.0, minimum=0.1, maximum=8.0)
    max_tokens = _setting_int("LLM_MAX_OUTPUT_TOKENS", 120, minimum=16, maximum=512)
    return OpenAICompatibleTaskPlanner(key, base_url, model, timeout=timeout, max_tokens=max_tokens)


def _setting_float(name: str, default: float, *, minimum: float, maximum: float) -> float:
    import os

    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        return default
    return min(maximum, max(minimum, value))


def _setting_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    import os

    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return min(maximum, max(minimum, value))
