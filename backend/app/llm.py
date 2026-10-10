"""Nicrron vision extraction (OpenAI-compatible) + deterministic mock mode.
One call = one independent 'pass'. The pipeline runs several passes and votes."""
import base64
import io
import json
import random
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image

from . import config
from .config import FIELDS

SYSTEM_PROMPT = """You are a pharmacy intake transcriptionist reading a FAXED prescription image.
Your job is to transcribe, not to guess. Pharmacists will act on what you mark as legible.

Return ONLY a JSON object with this exact shape (no prose, no markdown):
{
  "fields": {
    "patient_name":   {"value": string|null, "confidence": 0.0-1.0, "legible": true|false, "alternatives": [string], "raw": string|null},
    "patient_dob":    {... same keys; value as YYYY-MM-DD if determinable ...},
    "drug_name":      {...},
    "strength":       {... value like "500 mg" ...},
    "dosage_form":    {... e.g. "tablet", "capsule", "solution", "inhaler" ...},
    "quantity":       {... numeric string e.g. "30" ...},
    "sig":            {... directions exactly as written, e.g. "1 tab PO BID x 10 days" ...},
    "refills":        {... numeric string, "0" if it says none/NR ...},
    "prescriber_name":{...},
    "prescriber_npi": {... 10 digits or null ...},
    "prescriber_dea": {... e.g. "BS1234563" or null ...},
    "date_written":   {... YYYY-MM-DD ...}
  },
  "raw_transcription": string,
  "image_quality_notes": string
}
Rules:
- "confidence" is your calibrated probability that the value is exactly right as written on the page.
- If any character of a value is smudged, cut off, or ambiguous (e.g. 1 vs 7, 0 vs 6, qd vs qid, mg vs mcg), set legible=false, put your best readings in "alternatives" (max 3) and set value to null.
- If a field is absent from the page, set value null, legible true, confidence 1.0, raw null.
- Never normalise a drug name to what is 'probably meant'. Transcribe what is written; put the suspected intended drug in alternatives.
- Keep "raw" as the verbatim characters you see for that field.
"""

USER_PROMPT = "Transcribe this faxed prescription into the JSON schema. Flag anything you are not certain of."


def _image_to_data_url(image_bytes: bytes, max_side: int = 1800) -> Tuple[str, Tuple[int, int]]:
    im = Image.open(io.BytesIO(image_bytes))
    im = im.convert("RGB")
    w, h = im.size
    scale = min(1.0, max_side / max(w, h))
    if scale < 1.0:
        im = im.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=88)
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/jpeg;base64,{b64}", im.size


def _parse_json(text: str) -> Dict[str, Any]:
    """Models occasionally emit unescaped quotes / trailing prose. Try strict, then the outer {...}, then json_repair."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.S)
    try:
        return json.loads(t)
    except Exception:
        pass
    m = re.search(r"\{.*\}", t, flags=re.S)
    frag = m.group(0) if m else t
    try:
        return json.loads(frag)
    except Exception:
        pass
    from json_repair import repair_json
    out = repair_json(frag, return_objects=True)
    if not isinstance(out, dict) or "fields" not in out:
        raise ValueError("model output is not the expected JSON object")
    return out


def _coerce(parsed: Dict[str, Any]) -> Dict[str, Any]:
    """Guarantee every field exists with the expected keys."""
    fields = parsed.get("fields") or {}
    out = {}
    for f in FIELDS:
        v = fields.get(f) or {}
        if not isinstance(v, dict):
            v = {"value": v}
        val = v.get("value")
        if isinstance(val, (int, float)):
            val = str(val)
        out[f] = {
            "value": val if val not in ("", "null", "N/A", "n/a") else None,
            "confidence": float(v.get("confidence", 0.5) or 0.0),
            "legible": bool(v.get("legible", True)),
            "alternatives": [str(a) for a in (v.get("alternatives") or [])][:3],
            "raw": v.get("raw"),
        }
    return {"fields": out, "raw_transcription": parsed.get("raw_transcription", ""),
            "image_quality_notes": parsed.get("image_quality_notes", "")}


# ------------------------------------------------------------------ live
_client = None


def _get_client():
    global _client
    if _client is None:
        from openai import OpenAI
        _client = OpenAI(api_key=config.NICRRON_API_KEY, base_url=config.NICRRON_BASE_URL)
    return _client


def live_pass(image_bytes: bytes, model: str, temperature: float, pass_idx: int) -> Dict[str, Any]:
    data_url, size = _image_to_data_url(image_bytes)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": [
            {"type": "text", "text": USER_PROMPT},
            {"type": "image_url", "image_url": {"url": data_url, "detail": "high"}},
        ]},
    ]
    kwargs = {"model": model, "messages": messages, "max_tokens": 1800}
    # Anthropic Claude 5-family rejects `temperature` through the gateway ("deprecated for this model");
    # pass diversity for those comes from the second model + repeated sampling instead.
    if not model.startswith("anthropic/"):
        kwargs["temperature"] = temperature
    if model.startswith("openai/"):
        kwargs["response_format"] = {"type": "json_object"}
    t0 = time.perf_counter()
    resp = _get_client().chat.completions.create(**kwargs)
    latency_ms = int((time.perf_counter() - t0) * 1000)
    text = resp.choices[0].message.content or ""
    usage = getattr(resp, "usage", None)
    parsed = _coerce(_parse_json(text))
    return {
        "pass": pass_idx, "mode": "live", "model": getattr(resp, "model", model) or model, "requested_model": model,
        "temperature": temperature, "latency_ms": latency_ms, "raw_text": text, "parsed": parsed,
        "tokens_in": getattr(usage, "prompt_tokens", 0) or 0, "tokens_out": getattr(usage, "completion_tokens", 0) or 0,
        "image_size": size,
        # what we send to PRISM (no image bytes)
        "prompt_for_trace": [{"role": "system", "content": SYSTEM_PROMPT[:400] + " …"},
                             {"role": "user", "content": f"{USER_PROMPT} [image {size[0]}x{size[1]} omitted from trace]"}],
    }


# ------------------------------------------------------------------ mock
_NOISE = {
    "strength": lambda v: [v.replace("10 ", "40 "), v.replace("500", "600"), v.replace("mg", "mcg")],
    "quantity": lambda v: [str(int(v) + 10) if str(v).isdigit() else "?", "1" + str(v)],
    "patient_dob": lambda v: [v[:-1] + ("1" if v[-1] != "1" else "7")],
    "sig": lambda v: [v.replace("BID", "TID").replace("daily", "qid")],
    "refills": lambda v: [str(int(v) + 1) if str(v).isdigit() else "1"],
    "drug_name": lambda v: [v[:-2] + "ne" if len(v) > 4 else v + "e"],
}


def mock_pass(ground_truth: Optional[Dict[str, Any]], model: str, temperature: float, pass_idx: int, seed: int) -> Dict[str, Any]:
    """Perturbs ground truth so consensus/verification/triage logic can be exercised offline.
    Fields listed in ground_truth['ambiguous'] get disagreeing/illegible readings; others are mostly right."""
    rng = random.Random(seed * 1000 + pass_idx)
    gt_fields = (ground_truth or {}).get("fields") or {}
    ambiguous = set((ground_truth or {}).get("ambiguous") or [])
    fields = {}
    for f in FIELDS:
        truth = gt_fields.get(f)
        if truth is None:
            fields[f] = {"value": None, "confidence": 1.0, "legible": True, "alternatives": [], "raw": None}
            continue
        truth = str(truth)
        if f in ambiguous:
            alts = _NOISE.get(f, lambda v: [v + "?"])(truth)
            roll = rng.random()
            if roll < 0.45:       # illegible → withhold
                fields[f] = {"value": None, "confidence": 0.35, "legible": False, "alternatives": [truth] + alts[:2], "raw": truth[:-1] + "?"}
            elif roll < 0.75:     # confidently wrong reading (what a naive OCR would 'guess')
                fields[f] = {"value": alts[0], "confidence": 0.62, "legible": True, "alternatives": [truth], "raw": alts[0]}
            else:
                fields[f] = {"value": truth, "confidence": 0.58, "legible": True, "alternatives": alts[:1], "raw": truth}
        else:
            if rng.random() < 0.04:   # rare slip on a clean field
                fields[f] = {"value": _NOISE.get(f, lambda v: [v + "x"])(truth)[0], "confidence": 0.8, "legible": True, "alternatives": [], "raw": truth}
            else:
                fields[f] = {"value": truth, "confidence": round(rng.uniform(0.9, 0.99), 2), "legible": True, "alternatives": [], "raw": truth}
    parsed = {"fields": fields, "raw_transcription": "(mock) " + " | ".join(f"{k}: {v}" for k, v in gt_fields.items()),
              "image_quality_notes": "mock mode — perturbed ground truth"}
    return {"pass": pass_idx, "mode": "mock", "model": f"mock:{model}", "requested_model": model, "temperature": temperature,
            "latency_ms": rng.randint(400, 900), "raw_text": json.dumps(parsed), "parsed": parsed,
            "tokens_in": 0, "tokens_out": 0, "image_size": None,
            "prompt_for_trace": [{"role": "user", "content": "(mock pass) transcribe faxed prescription"}]}


def plan_passes() -> List[Tuple[str, float]]:
    """K passes: primary model at two temperatures, then the second-opinion model, then repeat."""
    plan = [(config.MODEL_PRIMARY, 0.1), (config.MODEL_SECOND, 0.1), (config.MODEL_PRIMARY, 0.6), (config.MODEL_SECOND, 0.6)]
    return plan[:config.PASSES] if config.PASSES <= len(plan) else (plan * 3)[:config.PASSES]


def run_pass(image_bytes: bytes, model: str, temperature: float, pass_idx: int,
             ground_truth: Optional[Dict[str, Any]] = None, seed: int = 0) -> Dict[str, Any]:
    if config.LLM_MODE == "live":
        try:
            return live_pass(image_bytes, model, temperature, pass_idx)
        except Exception as e:
            return {"pass": pass_idx, "mode": "live", "model": model, "requested_model": model, "temperature": temperature,
                    "latency_ms": 0, "raw_text": "", "parsed": None, "error": f"{type(e).__name__}: {e}",
                    "tokens_in": 0, "tokens_out": 0, "image_size": None,
                    "prompt_for_trace": [{"role": "user", "content": USER_PROMPT}]}
    return mock_pass(ground_truth, model, temperature, pass_idx, seed)
