"""Local visual provider for Ollama-backed multimodal models (for example LLaVA)."""

import base64
import io
import json
import re
import time
import urllib.error
import urllib.request
from typing import Dict, List, Optional

from PIL import Image

from submissions.kl2400033283.agent.config import OLLAMA_BASE_URL, OLLAMA_MODEL, OLLAMA_TIMEOUT_MS
from submissions.kl2400033283.agent.rules.authoritative_rules import HANDLING_MARKS
from submissions.kl2400033283.agent.schemas.evidence import ImageQuality
from submissions.kl2400033283.agent.vision.observations import UnitObservation, remap_views
from submissions.kl2400033283.agent.vision.providers.claude_provider import (
    STATE_GUIDE, SYSTEM_PROMPT, TOOL, validate_observations,
)
from submissions.kl2400033283.agent.vision.quality import LoadedImage


def _encode(img: LoadedImage) -> str:
    with Image.open(img.path) as im:
        im = im.convert("RGB")
        im.thumbnail((1024, 1024))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _extract_json(text: str) -> Optional[Dict]:
    if not text:
        return None
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        return json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except ValueError:
                return None
    return None


def _normalise_mark(mark: str) -> Optional[str]:
    value = str(mark).upper().strip()
    aliases = {
        "FRAGILE": "fragile",
        "FRAGILE - HANDLE WITH CARE": "fragile",
        "THIS WAY UP": "this_way_up",
        "UP": "this_way_up",
        "SOLD AS SET": "sold_as_set",
        "SOLD AS SET - DO NOT SEPARATE": "sold_as_set",
        "HEAVY": "team_lift",
        "HEAVY - TEAM LIFT": "team_lift",
        **{key.upper(): key for key in HANDLING_MARKS},
    }
    return aliases.get(value)


class OllamaVisionProvider:
    name = "ollama_vision"
    timeout_ms = OLLAMA_TIMEOUT_MS

    def __init__(self, base_url: str = OLLAMA_BASE_URL, model: str = OLLAMA_MODEL, transport=None,
                 disabled: bool = False):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.model_version = model
        self._transport = transport or self._http_post
        self._disabled = disabled
        self._probe = None

    @property
    def available(self) -> bool:
        """True only if the Ollama server answers AND has the configured model pulled.

        Cached for 60 s so routing does not probe the network on every inspection."""
        if not (self.model and self.base_url) or self._disabled:
            return False
        now = time.monotonic()
        if self._probe is not None and now - self._probe[0] < 60:
            return self._probe[1]
        ok = False
        try:
            req = urllib.request.Request(f"{self.base_url}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            names = {str(m.get("name", "")).lower() for m in payload.get("models") or [] if isinstance(m, dict)}
            want = self.model.lower()
            ok = want in names or (":" not in want and f"{want}:latest" in names)
        except Exception:
            ok = False
        self._probe = (now, ok)
        return ok

    def build_request(self, images: List[LoadedImage], context: Dict) -> Dict:
        encoded = [_encode(img) for img in images]
        prompt = (
            "Inspect the supplied product images as a visual evidence observer. "
            "Return observations only. Do not make compliance decisions or verdicts. "
            "Use the required check keys and their allowed state values from the "
            "provided JSON schema. If a visual property cannot be established clearly, "
            "use the appropriate INDETERMINATE or not-visible state. "
            f"Unit category: {context.get('category')}. "
            "Read any FNSKU code exactly as printed; do not guess."
        )
        return {
            "model": self.model,
            "stream": False,
            "prompt": prompt,
            "images": encoded,
            "format": TOOL["input_schema"],
            "options": {"temperature": 0, "num_predict": 500},
        }

    def _http_post(self, payload: Dict) -> Dict:
        req = urllib.request.Request(
            f"{self.base_url}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=max(5.0, self.timeout_ms / 1000.0 - 2)) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def observe(self, images: List[LoadedImage], qualities: List[ImageQuality], calibrated: bool,
                context: Dict = None) -> UnitObservation:
        usable = [img for img, q in zip(images, qualities) if q.usable]
        if not usable:
            raise ValueError("No usable images for Ollama vision")
        payload = self.build_request(usable, context or {})
        response = self._transport(payload)
        return remap_views(self.parse_response(response), qualities)

    def parse_response(self, response: Dict) -> UnitObservation:
        text = (response or {}).get("response") or ""
        if not text:
            text = ((response or {}).get("message") or {}).get("content") or ""
        payload = _extract_json(text)
        if isinstance(payload, dict):
            raw_handling = payload.get("handling_marks")
            if isinstance(raw_handling, dict):
                measurements = raw_handling.get("measurements")
                if isinstance(measurements, dict) and isinstance(measurements.get("detected_marks"), list):
                    marks = [_normalise_mark(mark) for mark in measurements["detected_marks"]]
                    if any(mark is None for mark in marks):
                        payload["handling_marks"] = {
                            "state": "INDETERMINATE",
                            "signal": 0,
                            "measurements": {},
                            "regions": raw_handling.get("regions", []),
                            "notes": ["Ollama returned an unsupported handling mark."],
                        }
                    else:
                        payload["handling_marks"] = {
                            **raw_handling,
                            "measurements": {
                                **measurements,
                                "detected_marks": list(dict.fromkeys(marks)),
                            },
                        }
        checks, notes = validate_observations(payload)
        return UnitObservation(
            provider=self.name,
            model_version=self.model_version,
            checks=checks,
            model_calls=1,
            cost_usd=0.0,
            raw_notes=notes,
        )
