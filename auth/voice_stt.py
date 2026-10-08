"""c1-13b Phase 1 — Voice STT relay layer (P1-P3 trial).

Boss-signed 實施令 2026-10-04: Azure Speech (East Asia) is the main provider
(EN WER 1.11%, mixed-language CER 9.53% — 2.3x better than Deepgram), Deepgram
nova-3 ships in the same PR as a dormant backup behind ``STT_PROVIDER``.

Red lines enforced here (not by convention — by code):

* The DeepTutor engine image (``hkuds/deeptutor:v1.5.8``) is untouched. Speech
  to text lives entirely in this relay: browser mic -> ``POST
  /api/voice/transcribe`` -> provider -> transcript back to the browser, which
  puts it in the child's input box. Nothing is auto-sent to the engine from
  here.
* 原音即毁: the audio bytes are a function argument for the duration of one
  request. They are never written to disk, never stored in SQLite and never
  logged. The DB only ever sees minute counts — never audio, never the
  transcript (see migrations/phase9_voice_stt.sql).
* No voiceprint, no training use. ``student_id`` is never sent to a provider —
  neither payload below carries an identifier of any kind.
* ``mip_opt_out=true`` is sent on every Deepgram call: the 對測 numbers (and
  the data terms behind them) only hold with that parameter present.
* No credential is invented here. A missing key raises ``stt_not_configured``
  and the caller reports "unavailable" — the relay never guesses a fallback.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import httpx
import yaml

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "voice_stt.yaml"

AZURE_KEY_ENV = "AZURE_SPEECH_KEY"
AZURE_REGION_ENV = "AZURE_SPEECH_REGION"
DEEPGRAM_KEY_ENV = "DEEPGRAM_API_KEY"
PROVIDER_ENV = "STT_PROVIDER"

SUPPORTED_PROVIDERS = ("azure", "deepgram")

#: Short-audio REST (<= 60 s) instead of the Speech SDK: the segment cap is
#: 60 s by design, so the streaming SDK adds a dependency without adding
#: value, and the engine/relay split stays exactly as the 實施令 requires.
_AZURE_STT_PATH = "/speech/recognition/conversation/cognitiveservices/v1"
_DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"

_DEFAULT_HTTP_TIMEOUT = 15.0

_config_cache: Optional[dict[str, Any]] = None


class SttError(Exception):
    """Provider/relay failure carrying a safe, non-leaky error code."""

    def __init__(self, code: str, *, detail: str = "") -> None:
        super().__init__(code)
        self.code = code
        #: Operator-facing detail. Never contains audio, key material or the
        #: student id; the kid-facing layer ignores it entirely.
        self.detail = detail


@dataclass(frozen=True)
class SttResult:
    text: str
    provider: str
    latency_ms: int


def load_config(*, force: bool = False) -> dict[str, Any]:
    """Read config/voice_stt.yaml once. A broken file degrades to defaults."""
    global _config_cache
    if _config_cache is not None and not force:
        return _config_cache
    try:
        with open(CONFIG_PATH, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        if not isinstance(data, dict):
            data = {}
    except (OSError, yaml.YAMLError):
        logger.warning("voice_stt: config unreadable (%s), using defaults", CONFIG_PATH)
        data = {}
    _config_cache = data
    return data


def provider_name() -> str:
    """`STT_PROVIDER` env wins; otherwise the YAML default (azure)."""
    raw = (os.environ.get(PROVIDER_ENV) or "").strip().lower()
    if raw in SUPPORTED_PROVIDERS:
        return raw
    configured = str(load_config().get("stt", {}).get("provider", "azure")).strip().lower()
    return configured if configured in SUPPORTED_PROVIDERS else "azure"


def language_for(lang_hint: Optional[str]) -> str:
    """Map the UI language to a provider language tag (EN is the default)."""
    stt_cfg = load_config().get("stt", {}) or {}
    azure_cfg = stt_cfg.get("azure", {}) or {}
    mapping = azure_cfg.get("language_map") or {}
    if lang_hint and lang_hint in mapping:
        return str(mapping[lang_hint])
    return str(azure_cfg.get("language_default", "en-US"))


def _azure_endpoint() -> tuple[str, str]:
    region = (
        os.environ.get(AZURE_REGION_ENV)
        or str((load_config().get("stt", {}) or {}).get("azure", {}).get("region", "eastasia"))
    ).strip()
    key = (os.environ.get(AZURE_KEY_ENV) or "").strip()
    if not key:
        # No key on this host: report unavailable, never invent one.
        raise SttError("stt_not_configured", detail="AZURE_SPEECH_KEY missing")
    url = f"https://{region}.stt.speech.microsoft.com{_AZURE_STT_PATH}"
    return url, key


def _deepgram_params() -> dict[str, str]:
    cfg = (load_config().get("stt", {}) or {}).get("deepgram", {}) or {}
    params = {
        "model": str(cfg.get("model", "nova-3")),
        "smart_format": "true" if cfg.get("smart_format", True) else "false",
    }
    # MANDATORY (對測 parameter): never send a Deepgram request without it.
    params["mip_opt_out"] = "true" if cfg.get("mip_opt_out", True) else "false"
    return params


def _deepgram_key() -> str:
    key = (os.environ.get(DEEPGRAM_KEY_ENV) or "").strip()
    if not key:
        raise SttError("stt_not_configured", detail="DEEPGRAM_API_KEY missing")
    return key


async def transcribe(
    audio: bytes,
    *,
    content_type: str,
    lang_hint: Optional[str] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> SttResult:
    """Transcribe one <=60 s clip. Audio is never persisted or logged.

    ``client`` is injectable so the test suite can drive both adapters without
    touching the network.
    """
    if not audio:
        raise SttError("empty_audio")

    provider = provider_name()
    language = language_for(lang_hint)
    started = time.perf_counter()

    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=_DEFAULT_HTTP_TIMEOUT)
    try:
        if provider == "azure":
            text = await _transcribe_azure(client, audio, content_type, language)
        else:
            text = await _transcribe_deepgram(client, audio, content_type, language)
    except SttError:
        raise
    except httpx.TimeoutException as exc:
        raise SttError("stt_timeout", detail=type(exc).__name__) from exc
    except httpx.HTTPError as exc:
        raise SttError("stt_unreachable", detail=type(exc).__name__) from exc
    finally:
        if owns_client:
            await client.aclose()

    latency_ms = int((time.perf_counter() - started) * 1000)
    return SttResult(text=text.strip(), provider=provider, latency_ms=latency_ms)


async def _transcribe_azure(
    client: httpx.AsyncClient, audio: bytes, content_type: str, language: str
) -> str:
    url, key = _azure_endpoint()
    resp = await client.post(
        url,
        params={"language": language, "format": "simple"},
        headers={
            "Ocp-Apim-Subscription-Key": key,  # host .env only, never logged
            "Content-Type": content_type or "audio/wav",
            "Accept": "application/json",
        },
        content=audio,
    )
    return _parse_azure(resp)


def _parse_azure(resp: httpx.Response) -> str:
    if resp.status_code == 401:
        raise SttError("stt_auth_failed", detail="azure 401")
    if resp.status_code == 400:
        # Wrong container/codec or bad language tag — an operator problem, and
        # the kid must never see it (the button just goes quiet).
        raise SttError("unsupported_audio_format", detail="azure 400")
    if resp.status_code == 429:
        raise SttError("stt_rate_limited", detail="azure 429")
    if resp.status_code >= 400:
        raise SttError("stt_failed", detail=f"azure {resp.status_code}")
    try:
        payload = resp.json()
    except ValueError as exc:
        raise SttError("stt_bad_response", detail="azure body not json") from exc
    # "simple" format: {"RecognitionStatus": "Success", "DisplayText": "..."}
    status = str(payload.get("RecognitionStatus", ""))
    if status and status != "Success":
        # NoSpeech / InitialSilenceTimeout are normal for a shy child, not
        # failures: an empty transcript is the honest answer.
        return ""
    return str(payload.get("DisplayText") or "")


async def _transcribe_deepgram(
    client: httpx.AsyncClient, audio: bytes, content_type: str, language: str
) -> str:
    params = _deepgram_params()
    params["language"] = language
    resp = await client.post(
        _DEEPGRAM_URL,
        params=params,
        headers={
            "Authorization": f"Token {_deepgram_key()}",  # host .env only
            "Content-Type": content_type or "audio/wav",
        },
        content=audio,
    )
    return _parse_deepgram(resp)


def _parse_deepgram(resp: httpx.Response) -> str:
    if resp.status_code in (401, 403):
        raise SttError("stt_auth_failed", detail=f"deepgram {resp.status_code}")
    if resp.status_code == 429:
        raise SttError("stt_rate_limited", detail="deepgram 429")
    if resp.status_code >= 400:
        raise SttError("stt_failed", detail=f"deepgram {resp.status_code}")
    try:
        payload = resp.json()
    except ValueError as exc:
        raise SttError("stt_bad_response", detail="deepgram body not json") from exc
    try:
        alternatives = (
            payload["results"]["channels"][0]["alternatives"]
        )
        return str(alternatives[0].get("transcript") or "")
    except (KeyError, IndexError, TypeError):
        raise SttError("stt_bad_response", detail="deepgram shape unexpected")
