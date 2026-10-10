"""Six-agent pipeline. Each agent appends events (for the live UI) and mutates the Order.
Intake → Extraction → Consensus → Verification → Triage → Order."""
import json
import re
import time
import io
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import numpy as np
from PIL import Image, ImageFilter

from . import config, llm, registries as reg
from .config import FIELDS, REQUIRED_FIELDS
from .prism import prism
from .schemas import Candidate, FieldResult, Order

AGENTS = ["intake", "extraction", "consensus", "verification", "triage", "order"]
AGENT_LABELS = {
    "intake": "Intake Agent", "extraction": "Extraction Agent (Nicrron vision)", "consensus": "Consensus Agent",
    "verification": "Verification Agent", "triage": "Uncertainty Triage Agent", "order": "Order Agent",
}
Emit = Callable[[Dict[str, Any]], None]


# ------------------------------------------------------------------ helpers
def _norm_date(v: Any) -> Optional[str]:
    if not v:
        return None
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%d %b %Y", "%b %d, %Y", "%B %d, %Y", "%d-%b-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except Exception:
            continue
    return s


def normalize(field: str, v: Any) -> Optional[str]:
    if v is None:
        return None
    if field == "strength":
        return reg.norm_strength(v)
    if field in ("patient_dob", "date_written"):
        return _norm_date(v)
    if field in ("quantity", "refills"):
        m = re.search(r"\d+", str(v))
        return m.group(0) if m else reg.norm_text(v)
    if field == "prescriber_npi":
        return re.sub(r"\D", "", str(v)) or None
    if field == "prescriber_dea":
        return re.sub(r"[^A-Za-z0-9]", "", str(v)).upper() or None
    if field == "sig":
        t = reg.norm_text(v)
        t = re.sub(r"\b(tabs?|tablets?)\b", "tab", t)
        t = re.sub(r"\b(caps?|capsules?)\b", "cap", t)
        t = re.sub(r"\bby mouth\b|\borally\b", "po", t)
        t = re.sub(r"\btwice (a |per )?daily\b|\btwice a day\b", "bid", t)
        t = re.sub(r"\bthree times (a |per )?daily\b|\bthree times a day\b", "tid", t)
        t = re.sub(r"\bfour times (a |per )?daily\b|\bfour times a day\b", "qid", t)
        t = re.sub(r"\bonce daily\b|\bevery day\b|\bonce a day\b", "daily", t)
        t = re.sub(r"\bfor\b", "x", t)
        t = re.sub(r"\b(\d+)\s*d\b|\b(\d+)\s*days?\b", lambda m: f"{m.group(1) or m.group(2)} days", t)
        t = re.sub(r"[.]", "", t)
        return re.sub(r"\s+", " ", t).strip()
    if field == "dosage_form":
        t = reg.norm_text(v)
        t = re.sub(r"\btabs?\b|\btablets?\b", "tablet", t)
        t = re.sub(r"\bcaps?\b|\bcapsules?\b", "capsule", t)
        return t
    return reg.norm_text(v)


class Ctx:
    def __init__(self, order: Order, emit: Optional[Emit]):
        self.order = order
        self.t0 = time.perf_counter()
        self.emit_cb = emit
        self.steps: List[Dict[str, Any]] = []     # PRISM trajectory steps

    def emit(self, agent: str, kind: str, text: str, **data):
        ev = {"t": int((time.perf_counter() - self.t0) * 1000), "agent": agent, "kind": kind, "text": text}
        if data:
            ev.update(data)
        self.order.events.append(ev)
        if self.emit_cb:
            self.emit_cb(ev)

    def stage(self, agent: str, idx: int):
        self.order.stage = AGENT_LABELS[agent]
        self.order.progress = int(idx / len(AGENTS) * 100)
        self.emit(agent, "stage", f"{AGENT_LABELS[agent]} started", state="running")

    def done(self, agent: str, summary: str, **step):
        self.emit(agent, "stage", summary, state="done")
        self.steps.append({"step_type": step.get("step_type", "reasoning"), "label": AGENT_LABELS[agent],
                           "output_summary": summary, "duration_ms": int((time.perf_counter() - self.t0) * 1000),
                           "status": step.get("status", "success"), **({"tool_name": step["tool_name"]} if "tool_name" in step else {})})


# ------------------------------------------------------------------ 1. intake
def agent_intake(ctx: Ctx, image_bytes: bytes) -> Dict[str, Any]:
    ctx.stage("intake", 0)
    im = Image.open(io.BytesIO(image_bytes))
    w, h = im.size
    g = np.asarray(im.convert("L").resize((min(w, 1200), int(h * min(w, 1200) / w))), dtype=np.float32)
    # Laplacian variance = sharpness; std = contrast; ink ratio = how much is dark
    lap = (np.abs(np.diff(g, 2, axis=0))[:, :-2] + np.abs(np.diff(g, 2, axis=1))[:-2, :])
    sharp = float(lap.var())
    contrast = float(g.std())
    ink = float((g < 110).mean())
    quality = max(0.0, min(1.0, 0.5 * min(sharp / 900.0, 1.0) + 0.3 * min(contrast / 70.0, 1.0) + 0.2 * (1.0 if 0.01 < ink < 0.35 else 0.3)))
    q = {"width": w, "height": h, "sharpness": round(sharp, 1), "contrast": round(contrast, 1), "ink_ratio": round(ink, 3), "quality": round(quality, 2)}
    ctx.order.metrics["image_quality"] = q
    ctx.emit("intake", "file", f"{Path(ctx.order.source_image).name}", fmt=Path(ctx.order.source_image).suffix[1:].upper(), size=f"{w}×{h}")
    ctx.emit("intake", "info", f"Sharpness {q['sharpness']} · contrast {q['contrast']} · ink {q['ink_ratio']:.1%}")
    if quality < 0.45:
        ctx.emit("intake", "warning", f"Low fax quality ({quality:.2f}) — expect more fields to need review")
    ctx.done("intake", f"Image normalised · quality score {quality:.2f}", tool_name="image_quality", step_type="tool_call")
    return q


# ------------------------------------------------------------------ 2. extraction
def agent_extraction(ctx: Ctx, image_bytes: bytes, ground_truth: Optional[Dict[str, Any]], seed: int) -> List[Dict[str, Any]]:
    ctx.stage("extraction", 1)
    passes = []
    plan = llm.plan_passes()
    ctx.emit("extraction", "info", f"{len(plan)} independent passes via Nicrron gateway ({config.LLM_MODE} mode): " + ", ".join(f"{m}@T{t}" for m, t in plan))
    for i, (model, temp) in enumerate(plan):
        p = llm.run_pass(image_bytes, model, temp, i + 1, ground_truth=ground_truth, seed=seed)
        passes.append(p)
        if p.get("error"):
            ctx.emit("extraction", "warning", f"Pass {i+1} ({model}) failed: {p['error']}")
            ctx.steps.append({"step_type": "tool_call", "tool_name": "nicrron.chat.completions", "label": f"pass {i+1} {model}",
                              "output_summary": p["error"], "status": "error"})
            continue
        f = p["parsed"]["fields"]
        illegible = [k for k, v in f.items() if not v["legible"]]
        ctx.emit("extraction", "pass", f"Pass {i+1} · {p['model']} · {p['latency_ms']} ms · {len(illegible)} field(s) marked illegible",
                 model=p["model"], latency_ms=p["latency_ms"], illegible=illegible,
                 drug=f["drug_name"]["value"], strength=f["strength"]["value"], sig=f["sig"]["value"])
        meta = {"pass": i + 1, "temperature": temp, "illegible_fields": illegible, "order_id": ctx.order.order_id,
                "field_confidence": {k: v["confidence"] for k, v in f.items()}}
        tid = prism.trace_llm(model=p["model"], prompt_messages=p["prompt_for_trace"], output=p["raw_text"][:4000],
                              latency_ms=p["latency_ms"], session_id=ctx.order.order_id, agent_name="Extraction Agent",
                              metadata=meta, tokens_in=p["tokens_in"], tokens_out=p["tokens_out"])
        if tid:
            ctx.order.prism.setdefault("trace_ids", []).append(tid)
        ctx.steps.append({"step_type": "tool_call", "tool_name": "nicrron.chat.completions", "label": f"pass {i+1} {model}",
                          "output_summary": f"{len(illegible)} illegible; drug={f['drug_name']['value']}", "duration_ms": p["latency_ms"],
                          "token_count": p["tokens_in"] + p["tokens_out"], "status": "success"})
    ctx.order.raw_passes = [{k: v for k, v in p.items() if k != "prompt_for_trace"} for p in passes]
    ctx.order.models = sorted({p["model"] for p in passes})
    ok = [p for p in passes if p.get("parsed")]
    ctx.done("extraction", f"{len(ok)}/{len(passes)} passes returned structured readings")
    return ok


# ------------------------------------------------------------------ 3. consensus
def agent_consensus(ctx: Ctx, passes: List[Dict[str, Any]]) -> Dict[str, FieldResult]:
    ctx.stage("consensus", 2)
    fields: Dict[str, FieldResult] = {}
    n = len(passes)
    for f in FIELDS:
        fr = FieldResult(name=f)
        readings = [p["parsed"]["fields"][f] for p in passes]
        votes: Counter = Counter()
        raw_by_norm: Dict[str, Any] = {}
        srcs: Dict[str, List[str]] = {}
        for p, r in zip(passes, readings):
            key = normalize(f, r["value"]) if r["legible"] and r["value"] is not None else "__illegible__" if not r["legible"] else "__absent__"
            votes[key] += 1
            raw_by_norm.setdefault(key, r["value"])
            srcs.setdefault(key, []).append(p["model"])
            for alt in r.get("alternatives") or []:
                ak = normalize(f, alt)
                if ak and ak not in raw_by_norm:
                    raw_by_norm[ak] = alt
                    srcs.setdefault(ak, []).append(f"{p['model']} (alt)")
        fr.candidates = [Candidate(value=raw_by_norm[k], votes=c, sources=srcs.get(k, [])) for k, c in votes.most_common()]
        fr.candidates += [Candidate(value=raw_by_norm[k], votes=0, sources=srcs.get(k, [])) for k in raw_by_norm if k not in votes]
        if n == 0:
            fr.status, fr.reasons = "missing", ["no successful extraction pass"]
            fields[f] = fr
            continue
        # tie-break: a legible reading beats "illegible" beats "absent" at equal votes
        prio = {"__illegible__": 1, "__absent__": 0}
        top, top_votes = max(votes.items(), key=lambda kv: (kv[1], prio.get(kv[0], 2)))
        illegible_votes = votes.get("__illegible__", 0)
        absent_votes = votes.get("__absent__", 0)
        fr.agreement = round(top_votes / n, 3)
        if top == "__absent__" and absent_votes == n:
            fr.status, fr.value, fr.confidence = "missing", None, 1.0
            fr.reasons.append("not present on the page (all passes agree)")
        elif top in ("__illegible__", "__absent__"):
            fr.status, fr.value = "unreadable", None
            fr.self_confidence = 0.3
            fr.confidence = 0.3
            fr.reasons.append(f"{illegible_votes}/{n} passes could not read this field")
        else:
            fr.value = raw_by_norm[top]
            agreeing = [r for r in readings if r["legible"] and normalize(f, r["value"]) == top]
            fr.self_confidence = round(sum(r["confidence"] for r in agreeing) / max(1, len(agreeing)), 3)
            fr.confidence = round(0.5 * fr.self_confidence + 0.5 * fr.agreement, 3)
            if top_votes < n:
                others = [f"{c.value!r}×{c.votes}" for c in fr.candidates if c.votes and normalize(f, c.value) != top and c.value is not None]
                fr.reasons.append(f"{top_votes}/{n} passes read {fr.value!r}" + (f"; others: {', '.join(others)}" if others else "") + (f"; {illegible_votes} illegible" if illegible_votes else ""))
            if illegible_votes:
                fr.confidence = min(fr.confidence, config.REVIEW_MIN - 0.01)
                fr.reasons.append("at least one pass marked it illegible → cannot auto-verify")
            if n < 2:
                fr.confidence = min(fr.confidence, config.VERIFIED_MIN - 0.01)
                fr.reasons.append(f"only {n} extraction pass succeeded — no cross-check possible")
            fr.status = "needs_review"  # provisional; triage decides
        fields[f] = fr
        if fr.value is not None or fr.status == "unreadable":
            ctx.emit("consensus", "field", f"{f}: {fr.value!r} · agreement {fr.agreement:.0%} · self-conf {fr.self_confidence or 0:.2f}",
                     field=f, value=fr.value, agreement=fr.agreement, conf=fr.confidence, flag=(fr.agreement or 0) < 1.0 or fr.status == "unreadable")
    split = [f for f, fr in fields.items() if (fr.agreement or 1) < 1.0]
    ctx.done("consensus", f"{len(FIELDS)} fields voted · {len(split)} with disagreement: {', '.join(split) or 'none'}")
    return fields


# ------------------------------------------------------------------ 4. verification
def agent_verification(ctx: Ctx, fields: Dict[str, FieldResult]):
    ctx.stage("verification", 3)
    drug, strength, form = fields["drug_name"], fields["strength"], fields["dosage_form"]
    checks = 0
    # --- drug name vs RxNorm
    if drug.value:
        m = reg.rxnav_drug_match(str(drug.value)); checks += 1
        drug.evidence["rxnorm"] = m
        if m.get("ok") is None:
            drug.registry_score = None; drug.reasons.append("RxNorm unreachable — registry check skipped")
            ctx.emit("verification", "warning", "RxNorm unreachable; drug name not registry-verified")
        else:
            drug.registry_score = m.get("score", 0.0)
            if m.get("ok"):
                ctx.emit("verification", "confirm", f"RxNorm ✓ {m['match']['name']} (rxcui {m['match']['rxcui']}, similarity {m['score']:.2f})")
            else:
                sugg = ", ".join(m.get("suggestions") or []) or "none"
                drug.reasons.append(f"RxNorm best match '{(m.get('match') or {}).get('name','—')}' similarity {m.get('score',0):.2f}; spelling suggestions: {sugg}")
                ctx.emit("verification", "warning", f"RxNorm ✗ '{drug.value}' not a confident match (best {m.get('score',0):.2f}); suggestions: {sugg}")
                for s in (m.get("suggestions") or [])[:2]:
                    drug.candidates.append(Candidate(value=s, votes=0, sources=["RxNorm spelling"]))
        partner = reg.lasa_partner(str(drug.value))
        if partner:
            drug.evidence["lasa_partner"] = partner
            if (drug.agreement or 0) < 1.0 or not (m.get("ok") is True):
                drug.reasons.append(f"look-alike/sound-alike pair: {drug.value} ↔ {partner} — passes disagree or registry unsure")
                ctx.emit("verification", "warning", f"LASA alert: '{drug.value}' is confusable with '{partner}' and readings are not unanimous")
            else:
                ctx.emit("verification", "info", f"LASA note: '{drug.value}' ↔ '{partner}' — unanimous + RxNorm-confirmed, kept as advisory")
    # --- strength exists for that drug
    if drug.value and strength.value:
        s = reg.rxnav_strength_exists(str(drug.value), str(strength.value), str(form.value or "")); checks += 1
        strength.evidence["rxnorm_strength"] = s
        if s.get("ok") is None:
            strength.registry_score = None
        elif s.get("ok"):
            strength.registry_score = 1.0
            ctx.emit("verification", "confirm", f"RxNorm ✓ {drug.value} {strength.value} is a marketed strength")
        else:
            strength.registry_score = 0.2
            avail = ", ".join(s.get("available_strengths") or []) or "unknown"
            strength.reasons.append(f"RxNorm lists no {drug.value} at {strength.value}; available: {avail}")
            ctx.emit("verification", "warning", f"RxNorm ✗ no {drug.value} {strength.value}; available: {avail}")
            for a in (s.get("available_strengths") or [])[:3]:
                strength.candidates.append(Candidate(value=a, votes=0, sources=["RxNorm strengths"]))
        rng = reg.dose_in_range(str(drug.value), str(strength.value))
        if rng:
            strength.evidence["dose_range"] = rng
            if rng.get("ok") is False:
                strength.reasons.append(f"{rng['mg']} mg is outside the usual single-dose range {rng['range_mg']} mg")
                ctx.emit("verification", "warning", f"Dose range ✗ {rng['mg']} mg outside usual {rng['range_mg']} mg for {drug.value}")
    # --- sig
    sig = fields["sig"]
    if sig.value:
        p = reg.parse_sig(sig.value); checks += 1
        sig.evidence["parsed"] = p
        if not p["parsed"]:
            sig.reasons.append("directions could not be parsed into dose/frequency")
            sig.registry_score = 0.5
        else:
            sig.registry_score = 1.0
            ctx.emit("verification", "confirm", f"Sig parsed: {p['dose'] or '?'} · {p['route'] or '?'} · {p['frequency'] or '?'}" + (f" · {p['duration']}" if p['duration'] else ""))
        if p["error_prone_abbrev"]:
            sig.registry_score = 0.5
            sig.reasons.append(f"ISMP error-prone abbreviation: {', '.join(p['error_prone_abbrev'])} (qd↔qid confusion)")
            ctx.emit("verification", "warning", f"Error-prone abbreviation in sig: {', '.join(p['error_prone_abbrev'])}")
    # --- prescriber
    pres, npi, dea = fields["prescriber_name"], fields["prescriber_npi"], fields["prescriber_dea"]
    if npi.value:
        checks += 1
        ok = reg.npi_valid(npi.value)
        npi.evidence["luhn"] = ok
        if not ok:
            npi.registry_score = 0.0
            npi.reasons.append("NPI fails Luhn check digit")
            ctx.emit("verification", "warning", f"NPI {npi.value} fails checksum")
    if pres.value or npi.value:
        look = reg.nppes_lookup(str(pres.value or ""), str(npi.value) if npi.value and reg.npi_valid(npi.value) else None); checks += 1
        pres.evidence["nppes"] = look
        if look.get("ok") is None:
            pres.registry_score = None
        elif look.get("ok"):
            pres.registry_score = look.get("score", 1.0) if look.get("by") == "npi" else (0.85 if look.get("ambiguous") else 1.0)
            if npi.value and look.get("by") == "npi":
                npi.registry_score = 1.0
            ctx.emit("verification", "confirm", f"NPPES ✓ {look.get('found_name')} · NPI {look.get('npi')} · {look.get('taxonomy') or ''}")
            if look.get("ambiguous"):
                pres.reasons.append(f"{look['result_count']} NPPES records share this name — confirm by NPI")
        else:
            pres.registry_score = 0.3
            pres.reasons.append(f"NPPES: {look.get('reason')}")
            ctx.emit("verification", "warning", f"NPPES ✗ {look.get('reason')}")
            if npi.value and look.get("by") == "npi":
                npi.registry_score = 0.3
                npi.reasons.append("NPI passes checksum but has no NPPES record")
    if dea.value:
        checks += 1
        d = reg.dea_valid(dea.value, str(pres.value or "").split(" ")[-1])
        dea.evidence["dea"] = d
        dea.registry_score = 1.0 if d["ok"] else 0.0
        if not d["ok"]:
            dea.reasons.append(f"DEA number fails {d['reason']} check")
            ctx.emit("verification", "warning", f"DEA {dea.value} fails {d['reason']}")
        elif d.get("name_initial_mismatch"):
            dea.registry_score = 0.6
            dea.reasons.append("DEA second letter does not match prescriber surname initial")
    # --- dates
    for f in ("patient_dob", "date_written"):
        fr = fields[f]
        if fr.value:
            iso = _norm_date(fr.value)
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", iso or ""):
                fr.reasons.append("date not parseable"); fr.registry_score = 0.4
            else:
                y = int(iso[:4])
                if f == "patient_dob" and not (1900 <= y <= datetime.now().year):
                    fr.reasons.append("implausible birth year"); fr.registry_score = 0.2
                if f == "date_written" and (datetime.now() - datetime.strptime(iso, "%Y-%m-%d")).days > 365:
                    fr.reasons.append("prescription older than 1 year"); fr.registry_score = 0.5
    # --- required-but-missing
    for f in REQUIRED_FIELDS:
        if fields[f].status == "missing":
            fields[f].reasons.append("required field missing from fax")
    ctx.done("verification", f"{checks} registry/safety checks run (RxNorm, NPPES, Luhn/DEA, sig, dose range, LASA)", step_type="tool_call", tool_name="registries")


# ------------------------------------------------------------------ 5. triage
def agent_triage(ctx: Ctx, fields: Dict[str, FieldResult]):
    ctx.stage("triage", 4)
    queue = []
    for f in FIELDS:
        fr = fields[f]
        if fr.status == "missing":
            if f in REQUIRED_FIELDS:
                fr.pharmacist_question = f"'{f.replace('_', ' ')}' is not on the fax. Obtain from prescriber or patient record."
                queue.append(f)
            continue
        if fr.status == "unreadable":
            fr.confidence = min(fr.confidence, config.REVIEW_MIN - 0.01)
        else:
            read_conf = fr.confidence                      # transcription certainty (self-report ⊕ agreement ⊕ legibility)
            conf = read_conf
            if fr.registry_score is not None:
                conf = conf * (0.6 + 0.4 * fr.registry_score)
            safety_hit = any(k in " ".join(fr.reasons) for k in ("look-alike", "error-prone", "outside the usual", "fails", "no RxNorm", "lists no", "no NPPES"))
            if safety_hit and (fr.agreement or 0) < 1.0:
                conf = min(conf, config.REVIEW_MIN - 0.01)
            elif safety_hit:
                conf = min(conf, config.VERIFIED_MIN - 0.01)
            fr.confidence = round(conf, 3)
            if fr.confidence >= config.VERIFIED_MIN and not fr.reasons:
                fr.status = "verified"
            elif read_conf < config.REVIEW_MIN:
                # we are not sure what the page SAYS → withhold the value (never guess)
                fr.status = "unreadable"
                fr.reasons.append(f"reading confidence {read_conf:.3f} below {config.REVIEW_MIN} — value withheld, candidates shown")
                fr.value = None
            else:
                # we can read it, but a registry/safety check disagrees → show it, with the doubt attached
                fr.status = "needs_review"
        if fr.status != "verified":
            cands = [c for c in fr.candidates if c.value is not None]
            opts = "; ".join(f"{c.value!r} ({c.votes} vote{'s' if c.votes != 1 else ''}{', ' + c.sources[0] if c.sources and c.votes == 0 else ''})" for c in cands[:4])
            why = "; ".join(fr.reasons) or "low confidence"
            fr.pharmacist_question = f"Confirm {f.replace('_', ' ')}. {why}. Candidates: {opts or 'none'}."
            queue.append(f)
            ctx.emit("triage", "flag", f"⚑ {f}: {fr.status} (conf {fr.confidence:.2f}) — {why}", field=f, status=fr.status, conf=fr.confidence, candidates=[c.value for c in cands[:4]])
        else:
            ctx.emit("triage", "confirm", f"{f}: verified ({fr.confidence:.2f}) — {fr.value}", field=f, conf=fr.confidence)
    ctx.order.review_queue = queue
    verified = sum(1 for fr in fields.values() if fr.status == "verified")
    ctx.order.metrics.update({"fields_total": len(FIELDS), "verified": verified, "needs_review": sum(1 for fr in fields.values() if fr.status == "needs_review"),
                              "unreadable": sum(1 for fr in fields.values() if fr.status == "unreadable"),
                              "missing": sum(1 for fr in fields.values() if fr.status == "missing"),
                              "mean_confidence": round(sum(fr.confidence for fr in fields.values()) / len(FIELDS), 3)})
    ctx.done("triage", f"{verified} verified · {len(queue)} flagged for pharmacist: {', '.join(queue) or 'none'}")


# ------------------------------------------------------------------ 6. order
def agent_order(ctx: Ctx, fields: Dict[str, FieldResult]):
    ctx.stage("order", 5)
    o = ctx.order
    o.fields = fields
    o.status = "blocked" if o.review_queue else "ready"
    o.completed_at = time.time()
    o.progress = 100
    o.stage = "Complete"
    out = config.OUTPUT_DIR / f"{o.order_id}.order.json"
    out.write_text(o.model_dump_json(indent=2))
    ctx.steps.append({"step_type": "final_answer", "label": "Order Agent", "output_summary": f"status={o.status}; flagged={o.review_queue}", "status": "success"})
    traj = prism.submit_trajectory(steps=ctx.steps, session_id=o.order_id, final_status=("success" if o.status == "ready" else "needs_review"),
                                   model=o.models[0] if o.models else "mock")
    if traj:
        o.prism["trajectory"] = traj
    o.prism["enabled"] = prism.enabled
    ctx.emit("order", "file", out.name, fmt="JSON", size=f"{out.stat().st_size // 1024} KB")
    ctx.emit("order", "complete", f"✓ Order {o.status.upper()} · {o.metrics['verified']}/{len(FIELDS)} fields verified · {len(o.review_queue)} to pharmacist · {o.events[-1]['t'] / 1000:.1f}s")
    ctx.done("order", f"Order written: {out.name} ({o.status})")


# ------------------------------------------------------------------ entry
def run_order(order: Order, image_path: Path, ground_truth: Optional[Dict[str, Any]] = None, emit: Optional[Emit] = None, seed: int = 0) -> Order:
    ctx = Ctx(order, emit)
    order.status = "processing"
    order.llm_mode = config.LLM_MODE
    try:
        image_bytes = Path(image_path).read_bytes()
        agent_intake(ctx, image_bytes)
        passes = agent_extraction(ctx, image_bytes, ground_truth, seed)
        if not passes:
            raise RuntimeError("all extraction passes failed")
        fields = agent_consensus(ctx, passes)
        agent_verification(ctx, fields)
        agent_triage(ctx, fields)
        agent_order(ctx, fields)
    except Exception as e:
        order.status = "error"; order.error = f"{type(e).__name__}: {e}"; order.stage = "Error"
        ctx.emit("order", "warning", f"Pipeline error: {order.error}")
        (config.OUTPUT_DIR / f"{order.order_id}.order.json").write_text(order.model_dump_json(indent=2))
    return order


def load_ground_truth(image_path: Path) -> Optional[Dict[str, Any]]:
    """Sidecar JSON next to the image, or — for printed/photographed/faxed copies in data/user_photos named like
    rx_004*.jpg — the synthetic spec whose id starts with the same rx_NNN prefix."""
    image_path = Path(image_path)
    gt = image_path.with_suffix(".json")
    if gt.exists():
        try:
            return json.loads(gt.read_text())
        except Exception:
            return None
    m = re.match(r"(rx_\d{3})", image_path.stem)
    if m:
        for cand in sorted(config.SYNTHETIC_DIR.glob(f"{m.group(1)}_*.json")):
            try:
                return json.loads(cand.read_text())
            except Exception:
                continue
    return None
