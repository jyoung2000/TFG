"""LLM providers for the AI Director (Gemini, OpenRouter).

Pure request/response adaptation over the fakeable ``HTTPClient`` service —
no provider module ever touches settings or state, so the handler owns the
secret and passes it in. Providers never log or echo the key: HTTP errors are
surfaced with the remote status text only.

Both providers speak the same tiny chat contract (``LLMMessage`` in,
``LLMReply`` out, optional tool calls), which is what lets the director run one
tool-calling loop regardless of the vendor.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal, cast

from pydantic import BaseModel, Field, ValidationError

from _routes._errors import HTTPError
from services.interfaces import HTTPClient, HttpTimeoutError, JSONValue

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODELS_URL = f"{OPENROUTER_BASE_URL}/models"
OPENROUTER_CHAT_URL = f"{OPENROUTER_BASE_URL}/chat/completions"
OPENROUTER_AUTH_KEY_URL = f"{OPENROUTER_BASE_URL}/auth/key"
GEMINI_DEFAULT_MODEL = "gemini-2.0-flash"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

# Attribution headers OpenRouter asks apps to send (public, not secrets).
_OPENROUTER_APP_HEADERS = {
    "HTTP-Referer": "https://github.com/jyoung2000/TFG",
    "X-Title": "LTX Desktop Filmmaker",
}

MessageRole = Literal["system", "user", "assistant", "tool"]


@dataclass(slots=True)
class LLMToolCall:
    id: str
    name: str
    arguments: dict[str, object]


@dataclass(slots=True)
class LLMMessage:
    role: MessageRole
    content: str = ""
    tool_calls: list[LLMToolCall] = field(default_factory=list[LLMToolCall])
    # For role == "tool": which call this answers and the tool's name.
    tool_call_id: str = ""
    name: str = ""


@dataclass(slots=True)
class LLMUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass(slots=True)
class LLMReply:
    text: str
    tool_calls: list[LLMToolCall]
    model: str
    usage: LLMUsage | None = None


@dataclass(slots=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, object]  # JSON schema (object)


class LLMProvider:
    """Base contract; subclasses adapt to one vendor's wire format."""

    name: str = "base"
    model: str = ""

    def chat(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[ToolSpec] | None = None,
        *,
        json_mode: bool = False,
        timeout: int = 90,
    ) -> LLMReply:
        raise NotImplementedError


def _messages_chars(messages: Sequence[LLMMessage]) -> int:
    return sum(len(m.content) for m in messages)


def _tool_call_arguments(raw: object) -> dict[str, object]:
    if isinstance(raw, dict):
        return {str(k): v for k, v in cast(dict[object, object], raw).items()}
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw or "{}")
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return {str(k): v for k, v in cast(dict[object, object], parsed).items()}
    return {}


# ---------------------------------------------------------------------------
# OpenRouter (OpenAI-compatible chat completions)
# ---------------------------------------------------------------------------


class _ORFunction(BaseModel):
    name: str = ""
    arguments: object = "{}"


class _ORToolCall(BaseModel):
    id: str = ""
    function: _ORFunction = Field(default_factory=_ORFunction)


class _ORMessage(BaseModel):
    content: str | None = None
    tool_calls: list[_ORToolCall] | None = None


class _ORChoice(BaseModel):
    message: _ORMessage = Field(default_factory=_ORMessage)
    finish_reason: str | None = None


class _ORUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0


class _ORError(BaseModel):
    message: str = ""
    code: int | str | None = None


class _ORChatResponse(BaseModel):
    choices: list[_ORChoice] = Field(default_factory=list[_ORChoice])
    model: str = ""
    usage: _ORUsage | None = None
    error: _ORError | None = None


class OpenRouterModel(BaseModel):
    id: str
    name: str = ""
    context_length: int | None = None
    prompt_price: str = ""
    completion_price: str = ""
    supports_tools: bool = False
    supports_json: bool = False


class _ORPricing(BaseModel):
    prompt: str = ""
    completion: str = ""


class _ORModelEntry(BaseModel):
    id: str
    name: str = ""
    context_length: int | None = None
    pricing: _ORPricing = Field(default_factory=_ORPricing)
    supported_parameters: list[str] = Field(default_factory=list[str])


class _ORModelsResponse(BaseModel):
    data: list[_ORModelEntry] = Field(default_factory=list[_ORModelEntry])


class OpenRouterKeyInfo(BaseModel):
    label: str = ""
    usage: float | None = None
    limit: float | None = None
    is_free_tier: bool | None = None


class _ORKeyResponse(BaseModel):
    data: OpenRouterKeyInfo = Field(default_factory=OpenRouterKeyInfo)


def _openrouter_headers(api_key: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json", **_OPENROUTER_APP_HEADERS}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _raise_for_openrouter_status(status_code: int, text: str) -> None:
    if status_code == 200:
        return
    detail = text.strip()[:400]
    if status_code == 401:
        raise HTTPError(401, "OPENROUTER_KEY_INVALID: OpenRouter rejected the API key")
    if status_code == 402:
        raise HTTPError(402, f"OPENROUTER_CREDITS: OpenRouter reports insufficient credits. {detail}")
    if status_code == 404:
        raise HTTPError(404, f"OPENROUTER_MODEL_NOT_FOUND: {detail or 'model not available'}")
    if status_code == 429:
        raise HTTPError(429, "OPENROUTER_RATE_LIMITED: OpenRouter rate limit hit, retry shortly")
    raise HTTPError(502 if status_code >= 500 else status_code, f"OpenRouter API error ({status_code}): {detail}")


def openrouter_list_models(http: HTTPClient, api_key: str, *, timeout: int = 30) -> list[OpenRouterModel]:
    try:
        response = http.get(OPENROUTER_MODELS_URL, headers=_openrouter_headers(api_key), timeout=timeout)
    except HttpTimeoutError as exc:
        raise HTTPError(504, "OpenRouter model list request timed out") from exc
    except Exception as exc:
        raise HTTPError(502, f"OpenRouter unreachable: {exc}") from exc
    _raise_for_openrouter_status(response.status_code, response.text)
    try:
        parsed = _ORModelsResponse.model_validate(response.json())
    except (ValidationError, ValueError) as exc:
        raise HTTPError(502, "OpenRouter returned an unexpected model list payload") from exc
    models: list[OpenRouterModel] = []
    for entry in parsed.data:
        params = set(entry.supported_parameters)
        models.append(
            OpenRouterModel(
                id=entry.id,
                name=entry.name or entry.id,
                context_length=entry.context_length,
                prompt_price=entry.pricing.prompt,
                completion_price=entry.pricing.completion,
                supports_tools="tools" in params or "tool_choice" in params,
                supports_json="response_format" in params or "structured_outputs" in params,
            )
        )
    models.sort(key=lambda m: m.id)
    return models


def openrouter_validate_key(http: HTTPClient, api_key: str, *, timeout: int = 20) -> OpenRouterKeyInfo:
    if not api_key:
        raise HTTPError(400, "OPENROUTER_KEY_MISSING: no OpenRouter API key configured")
    try:
        response = http.get(OPENROUTER_AUTH_KEY_URL, headers=_openrouter_headers(api_key), timeout=timeout)
    except HttpTimeoutError as exc:
        raise HTTPError(504, "OpenRouter key validation timed out") from exc
    except Exception as exc:
        raise HTTPError(502, f"OpenRouter unreachable: {exc}") from exc
    _raise_for_openrouter_status(response.status_code, response.text)
    try:
        return _ORKeyResponse.model_validate(response.json()).data
    except (ValidationError, ValueError) as exc:
        raise HTTPError(502, "OpenRouter returned an unexpected key payload") from exc


class OpenAICompatibleProvider(LLMProvider):
    """Chat-completions provider for any OpenAI-compatible endpoint (OpenRouter,
    LM Studio, vLLM, local gateways). ``base_url`` is the ``/v1`` root."""

    name = "openai_compatible"

    def __init__(self, http: HTTPClient, api_key: str, model: str, *, base_url: str, name: str | None = None) -> None:
        self._http = http
        self._api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        if name:
            self.name = name

    @property
    def chat_url(self) -> str:
        return f"{self.base_url}/chat/completions"

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _require_key(self) -> None:
        # Local OpenAI-compatible servers often need no key; only OpenRouter insists.
        return

    def _raise_for_status(self, status_code: int, text: str) -> None:
        if status_code == 200:
            return
        detail = text.strip()[:400]
        label = self.name.upper()
        if status_code == 401:
            raise HTTPError(401, f"{label}_KEY_INVALID: the provider rejected the API key")
        if status_code == 404:
            raise HTTPError(404, f"{label}_MODEL_NOT_FOUND: {detail or 'model not available'}")
        if status_code == 429:
            raise HTTPError(429, f"{label}_RATE_LIMITED: rate limit hit, retry shortly")
        raise HTTPError(502 if status_code >= 500 else status_code, f"{self.name} API error ({status_code}): {detail}")

    @staticmethod
    def _encode_messages(messages: Sequence[LLMMessage]) -> list[JSONValue]:
        encoded: list[JSONValue] = []
        for message in messages:
            if message.role == "tool":
                encoded.append(
                    {
                        "role": "tool",
                        "tool_call_id": message.tool_call_id,
                        "name": message.name,
                        "content": message.content,
                    }
                )
                continue
            item: dict[str, JSONValue] = {"role": message.role, "content": message.content}
            if message.tool_calls:
                item["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
                    }
                    for call in message.tool_calls
                ]
            encoded.append(item)
        return encoded

    def list_models(self, *, timeout: int = 30) -> list[OpenRouterModel]:
        try:
            response = self._http.get(f"{self.base_url}/models", headers=self._headers(), timeout=timeout)
        except HttpTimeoutError as exc:
            raise HTTPError(504, f"{self.name} model list request timed out") from exc
        except Exception as exc:
            raise HTTPError(502, f"{self.name} unreachable: {exc}") from exc
        self._raise_for_status(response.status_code, response.text)
        try:
            parsed = _ORModelsResponse.model_validate(response.json())
        except (ValidationError, ValueError) as exc:
            raise HTTPError(502, f"{self.name} returned an unexpected model list payload") from exc
        models = [
            OpenRouterModel(
                id=entry.id,
                name=entry.name or entry.id,
                context_length=entry.context_length,
                prompt_price=entry.pricing.prompt,
                completion_price=entry.pricing.completion,
                supports_tools="tools" in set(entry.supported_parameters) or "tool_choice" in set(entry.supported_parameters),
                supports_json="response_format" in set(entry.supported_parameters) or "structured_outputs" in set(entry.supported_parameters),
            )
            for entry in parsed.data
        ]
        models.sort(key=lambda m: m.id)
        return models

    def chat(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[ToolSpec] | None = None,
        *,
        json_mode: bool = False,
        timeout: int = 90,
    ) -> LLMReply:
        self._require_key()
        payload: dict[str, JSONValue] = {
            "model": self.model,
            "messages": self._encode_messages(messages),
            "temperature": 0.4,
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": cast(JSONValue, tool.parameters),
                    },
                }
                for tool in tools
            ]
            payload["tool_choice"] = "auto"
        elif json_mode:
            payload["response_format"] = {"type": "json_object"}
        try:
            response = self._http.post(self.chat_url, headers=self._headers(), json_payload=payload, timeout=timeout)
        except HttpTimeoutError as exc:
            raise HTTPError(504, f"{self.name} request timed out") from exc
        except Exception as exc:
            raise HTTPError(502, f"{self.name} unreachable: {exc}") from exc
        self._raise_for_status(response.status_code, response.text)
        try:
            parsed = _ORChatResponse.model_validate(response.json())
        except (ValidationError, ValueError) as exc:
            raise HTTPError(502, f"{self.name} returned an unexpected chat payload") from exc
        if parsed.error is not None and parsed.error.message:
            raise HTTPError(502, f"{self.name} error: {parsed.error.message[:300]}")
        if not parsed.choices:
            raise HTTPError(502, f"{self.name} returned no choices")
        message = parsed.choices[0].message
        calls = [
            LLMToolCall(
                id=call.id or f"call_{index}",
                name=call.function.name,
                arguments=_tool_call_arguments(call.function.arguments),
            )
            for index, call in enumerate(message.tool_calls or [])
            if call.function.name
        ]
        usage = (
            LLMUsage(prompt_tokens=parsed.usage.prompt_tokens, completion_tokens=parsed.usage.completion_tokens)
            if parsed.usage is not None
            else None
        )
        return LLMReply(text=message.content or "", tool_calls=calls, model=parsed.model or self.model, usage=usage)


class OpenRouterProvider(OpenAICompatibleProvider):
    name = "openrouter"

    def __init__(self, http: HTTPClient, api_key: str, model: str) -> None:
        super().__init__(http, api_key, model, base_url=OPENROUTER_BASE_URL, name="openrouter")

    def _headers(self) -> dict[str, str]:
        return _openrouter_headers(self._api_key)

    def _require_key(self) -> None:
        if not self._api_key:
            raise HTTPError(400, "OPENROUTER_KEY_MISSING: no OpenRouter API key configured")

    def _raise_for_status(self, status_code: int, text: str) -> None:
        _raise_for_openrouter_status(status_code, text)


# ---------------------------------------------------------------------------
# Gemini (generateContent)
# ---------------------------------------------------------------------------


class _GeminiFunctionCall(BaseModel):
    name: str = ""
    args: dict[str, object] = Field(default_factory=dict)


class _GeminiPart(BaseModel):
    text: str | None = None
    functionCall: _GeminiFunctionCall | None = None  # noqa: N815 - wire name


class _GeminiContent(BaseModel):
    parts: list[_GeminiPart] = Field(default_factory=list[_GeminiPart])


class _GeminiCandidate(BaseModel):
    content: _GeminiContent = Field(default_factory=_GeminiContent)


class _GeminiUsage(BaseModel):
    promptTokenCount: int = 0  # noqa: N815 - wire name
    candidatesTokenCount: int = 0  # noqa: N815 - wire name


class _GeminiResponsePayload(BaseModel):
    candidates: list[_GeminiCandidate] = Field(default_factory=list[_GeminiCandidate])
    usageMetadata: _GeminiUsage | None = None  # noqa: N815 - wire name


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self, http: HTTPClient, api_key: str, model: str = GEMINI_DEFAULT_MODEL) -> None:
        self._http = http
        self._api_key = api_key
        self.model = model

    @staticmethod
    def _encode_contents(messages: Sequence[LLMMessage]) -> tuple[str, list[JSONValue]]:
        system_text = "\n\n".join(m.content for m in messages if m.role == "system")
        contents: list[JSONValue] = []
        for message in messages:
            if message.role == "system":
                continue
            if message.role == "tool":
                result: JSONValue
                try:
                    result = cast(JSONValue, json.loads(message.content))
                except json.JSONDecodeError:
                    result = message.content
                contents.append(
                    {
                        "role": "user",
                        "parts": [{"functionResponse": {"name": message.name, "response": {"result": result}}}],
                    }
                )
                continue
            parts: list[JSONValue] = []
            if message.content:
                parts.append({"text": message.content})
            for call in message.tool_calls:
                parts.append({"functionCall": {"name": call.name, "args": cast(JSONValue, call.arguments)}})
            if not parts:
                parts.append({"text": ""})
            contents.append({"role": "model" if message.role == "assistant" else "user", "parts": parts})
        return system_text, contents

    def chat(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[ToolSpec] | None = None,
        *,
        json_mode: bool = False,
        timeout: int = 90,
    ) -> LLMReply:
        if not self._api_key:
            raise HTTPError(400, "GEMINI_API_KEY_MISSING: no Gemini API key configured")
        system_text, contents = self._encode_contents(messages)
        generation_config: dict[str, JSONValue] = {"temperature": 0.4, "maxOutputTokens": 8192}
        if json_mode and not tools:
            generation_config["responseMimeType"] = "application/json"
        payload: dict[str, JSONValue] = {
            "contents": contents,
            "systemInstruction": {"parts": [{"text": system_text}]},
            "generationConfig": generation_config,
        }
        if tools:
            payload["tools"] = [
                {
                    "functionDeclarations": [
                        {
                            "name": tool.name,
                            "description": tool.description,
                            "parameters": cast(JSONValue, tool.parameters),
                        }
                        for tool in tools
                    ]
                }
            ]
        url = f"{GEMINI_BASE_URL}/{self.model}:generateContent"
        try:
            response = self._http.post(
                url,
                headers={"Content-Type": "application/json", "x-goog-api-key": self._api_key},
                json_payload=payload,
                timeout=timeout,
            )
        except HttpTimeoutError as exc:
            raise HTTPError(504, "Gemini API request timed out") from exc
        except Exception as exc:
            raise HTTPError(502, f"Gemini unreachable: {exc}") from exc
        if response.status_code == 401 or response.status_code == 403:
            raise HTTPError(401, "GEMINI_KEY_INVALID: Gemini rejected the API key")
        if response.status_code != 200:
            raise HTTPError(
                502 if response.status_code >= 500 else response.status_code,
                f"Gemini API error ({response.status_code}): {response.text.strip()[:400]}",
            )
        try:
            parsed = _GeminiResponsePayload.model_validate(response.json())
        except (ValidationError, ValueError) as exc:
            raise HTTPError(502, "GEMINI_PARSE_ERROR: unexpected Gemini payload") from exc
        if not parsed.candidates:
            raise HTTPError(502, "Gemini returned no candidates")
        parts = parsed.candidates[0].content.parts
        text = "\n".join(part.text for part in parts if part.text)
        calls = [
            LLMToolCall(
                id=f"call_{index}",
                name=part.functionCall.name,
                arguments=dict(part.functionCall.args),
            )
            for index, part in enumerate(parts)
            if part.functionCall is not None and part.functionCall.name
        ]
        usage = (
            LLMUsage(
                prompt_tokens=parsed.usageMetadata.promptTokenCount,
                completion_tokens=parsed.usageMetadata.candidatesTokenCount,
            )
            if parsed.usageMetadata is not None
            else None
        )
        return LLMReply(text=text, tool_calls=calls, model=self.model, usage=usage)


def parse_json_block(text: str) -> object:
    """Parse a JSON object from LLM text, tolerating ``` fences and prose around it."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                pass
    raise HTTPError(502, "LLM returned invalid JSON")


def messages_chars(messages: Sequence[LLMMessage]) -> int:
    return _messages_chars(messages)
