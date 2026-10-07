"""Free cloud vision provider (OpenAI-compatible chat API; OpenRouter `:free` models by default).

Same contract as the Claude provider: one call per unit carrying every image and
every check, the model may only return *observations* (closed vocabulary, schema
validated - extra fields like a smuggled "verdict" are rejected), and the
deterministic rules engine decides. Verdicts never come from the model.

Cost guard: only model ids ending in ":free" are accepted, so this provider can
never route a request to a paid model. If the free service is unavailable (rate
limit, outage, model withdrawn) the provider falls back to the offline OCR engine
and says so in the record - the line still gets a safe answer.
"""

import base64
import io
import json
import re
import threading
import time
import urllib.error
import urllib.request
from typing import Dict, List, Optional

from PIL import Image

from submissions.kl2400033283.agent.config import (
    FREE_VISION_API_KEY, FREE_VISION_MAX_EDGE, FREE_VISION_MODELS, FREE_VISION_TIMEOUT_MS, FREE_VISION_URL,
)
from submissions.kl2400033283.agent.schemas.evidence import ImageQuality
from submissions.kl2400033283.agent.vision.observations import UnitObservation, remap_views
from submissions.kl2400033283.agent.vision.providers.claude_provider import (
    STATE_GUIDE, SYSTEM_PROMPT, TOOL, validate_observations,
)
from submissions.kl2400033283.agent.vision.quality import LoadedImage


class PaidModelRefused(ValueError):
    pass


def _encode(img: LoadedImage) -> str:
    with Image.open(img.path) as im:
        im = im.convert("RGB")
        im.thumbnail((FREE_VISION_MAX_EDGE, FREE_VISION_MAX_EDGE))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _extract_json(text: str) -> Optional[Dict]:
    """Models sometimes wrap JSON in ```json fences or add a sentence; take the outermost object."""
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


class FreeVisionProvider:
    name = "free_vision"
    timeout_ms = FREE_VISION_TIMEOUT_MS

    def __init__(self, api_key: str = FREE_VISION_API_KEY, model: Optional[str] = None,
                 url: str = FREE_VISION_URL, transport=None, fallback=None, models: Optional[List[str]] = None):
        self.models = list(models or ([model] if model else FREE_VISION_MODELS))
        for m in self.models:
            if not m.endswith(":free"):
                raise PaidModelRefused(f"Refusing non-free model '{m}': only ':free' model ids are allowed.")
        self.api_key = api_key
        self.model = self.models[0]
        self.model_version = self.model
        self.url = url
        self._transport = transport or self._http_post
        self._fallback = fallback

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def build_request(self, images: List[LoadedImage], context: Dict) -> Dict:
        content: List[Dict] = []
        for i, img in enumerate(images):
            content.append({"type": "text", "text": f"Image view_index={i}"})
            content.append({"type": "image_url", "image_url": {"url": _encode(img)}})
        schema = json.dumps(TOOL["input_schema"], separators=(",", ":"))
        content.append({"type": "text", "text": (
            f"Unit context (from the work order, may be wrong): category={context.get('category')}. "
            f"Read any FNSKU code exactly as printed; do not guess.\n{STATE_GUIDE}\n\n"
            "Reply with ONLY one JSON object (no prose, no markdown) that matches this JSON Schema, "
            f"with an entry for every check:\n{schema}")})
        return {
            "model": self.model,
            "temperature": 0,
            "max_tokens": 2000,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": content}],
        }

    def _http_post(self, payload: Dict) -> Dict:
        req = urllib.request.Request(
            self.url, data=json.dumps(payload).encode("utf-8"), method="POST",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json",
                     "HTTP-Referer": "http://127.0.0.1:8765", "X-Title": "CUBE Prep Manager"})
        with urllib.request.urlopen(req, timeout=payload.pop("_timeout_s", self.timeout_ms / 1000.0 - 2)) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _call_models(self, base: Dict, deadline: float):
        """Try each free model in order (one retry round if all are busy). Returns (observation, notes)."""
        tried: List[str] = []
        for round_no in range(2):
            for model in self.models:
                remaining = deadline - time.monotonic()
                if remaining < 8:
                    return None, tried
                try:
                    response = self._transport(dict(base, model=model, _timeout_s=max(5.0, remaining - 2)))
                    if response.get("error"):
                        code = (response["error"] or {}).get("code", "error") if isinstance(response["error"], dict) else "error"
                        raise RuntimeError(f"{code}")
                    obs = self.parse_response(response)
                    if all(o.state == "INDETERMINATE" for o in obs.checks.values()):
                        raise ValueError("empty or unparseable reply")
                    obs.model_version = model
                    return obs, tried
                except Exception as exc:
                    tried.append(f"{model.split('/')[-1]}: {getattr(exc, 'code', '') or exc}"[:80])
            if round_no == 0 and deadline - time.monotonic() > 20:
                time.sleep(4)  # free pools free up quickly; one short pause, then one more round
        return None, tried

    def observe(self, images: List[LoadedImage], qualities: List[ImageQuality], calibrated: bool,
                context: Dict = None) -> UnitObservation:
        usable = [img for img, q in zip(images, qualities) if q.usable]
        base = self.build_request(usable, context or {})
        # Hard stopwatch for the free model. Network timeouts alone are not enough: free services send
        # keep-alive bytes while a model thinks, so a socket read never times out. The model gets
        # ~65% of the budget on the wall clock; after that we stop waiting and use the offline text
        # engine (which ran in parallel), so the agent's own budget is never reached.
        budget_s = self.timeout_ms / 1000.0
        started = time.monotonic()
        deadline = started + budget_s * 0.65

        # The offline text engine runs in parallel: it is free, deterministic and fills gaps.
        ocr_result: Dict = {}
        ocr_thread = None
        if self._fallback is not None and getattr(self._fallback, "available", False):
            def run_ocr():
                try:
                    ocr_result["obs"] = self._fallback.observe(images, qualities, calibrated, context=context)
                except Exception as exc:  # OCR failure must not sink the inspection
                    ocr_result["err"] = exc
            ocr_thread = threading.Thread(target=run_ocr, daemon=True)
            ocr_thread.start()

        box: Dict = {}

        def run_models():
            box["res"] = self._call_models(base, deadline)

        model_thread = threading.Thread(target=run_models, daemon=True)
        model_thread.start()
        model_thread.join(timeout=max(0.0, deadline - time.monotonic()))
        vlm, tried = box.get("res", (None, []))
        if vlm is None and not tried:
            tried = [f"no free model answered within {int(deadline - started)} s"]
        elif vlm is None and "res" not in box:
            tried = tried + [f"no free model answered within {int(deadline - started)} s"]
        if ocr_thread is not None:
            ocr_thread.join(timeout=max(1.0, started + budget_s * 0.9 - time.monotonic()))
        ocr = ocr_result.get("obs")

        if vlm is not None:
            remap_views(vlm, qualities)
            if tried:
                vlm.raw_notes.append("Skipped busy free models: " + "; ".join(tried))
            return fuse(vlm, ocr) if ocr is not None else vlm
        if ocr is not None:
            ocr.raw_notes.append("Free AI vision unavailable (" + "; ".join(tried) + "); used the offline text engine.")
            ocr.model_calls = 1  # attempted remote call counts against the per-unit budget
            return ocr
        raise RuntimeError("Free vision models unavailable and no offline fallback: " + "; ".join(tried))

    def parse_response(self, response: Dict) -> UnitObservation:
        if response.get("error"):
            raise RuntimeError(f"Free vision API error: {str(response['error'])[:160]}")
        text = ""
        choices = response.get("choices") or []
        if choices:
            text = (choices[0].get("message") or {}).get("content") or ""
        checks, notes = validate_observations(_extract_json(text))
        model_used = response.get("model", self.model)
        if model_used and not str(model_used).endswith(":free") and model_used != self.model:
            notes.append(f"Router reported model '{model_used}'.")
        return UnitObservation(provider=self.name, model_version=self.model_version, checks=checks,
                               model_calls=1, cost_usd=0.0, raw_notes=notes)


TEXT_FACTS = ("fnsku_text", "date_text", "warning_text", "wording_ok")


def fuse(vlm: UnitObservation, ocr: UnitObservation) -> UnitObservation:
    """Merge a vision-model observation with the offline OCR observation.

    * Where the model could not tell (INDETERMINATE) but OCR read hard evidence, use OCR's observation.
    * Text the OCR read (FNSKU code, date, warning wording) is attached to the model's observation,
      so deterministic text rules (FNSKU mismatch, date format) still apply.
    * Handling stickers: union of what either engine found.
    """
    for k, v in vlm.checks.items():
        o = ocr.checks.get(k)
        if o is None:
            continue
        if v.state == "INDETERMINATE" and o.state != "INDETERMINATE":
            o.notes = [f"From offline text engine: {o.notes[0] if o.notes else ''}".strip()]
            vlm.checks[k] = o
            continue
        for key in TEXT_FACTS:
            if key in o.measurements and o.measurements[key] not in (None, "") and not v.measurements.get(key):
                v.measurements[key] = o.measurements[key]
        if k == "handling_marks":
            marks = set(v.measurements.get("detected_marks", [])) | set(o.measurements.get("detected_marks", []))
            v.measurements["detected_marks"] = sorted(marks)
    vlm.raw_notes.append("Fused with offline OCR text evidence.")
    return vlm
