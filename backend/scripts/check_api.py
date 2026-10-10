"""Gate oracle: boot the API on a spare port, submit a sample, poll to completion, assert the order contract.
Prints 'API CHECK PASSED' only when every assertion holds. Honors LLM_MODE from the environment."""
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PORT = int(os.environ.get("PILLSPARK_CHECK_PORT", "8765"))
PY = ROOT / "backend" / ".venv" / "bin" / "python"


def get(path):
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}{path}", timeout=10) as r:
        return json.loads(r.read())


def post(path, body):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def main():
    env = dict(os.environ)
    proc = subprocess.Popen([str(PY), "-m", "uvicorn", "app.main:app", "--port", str(PORT), "--log-level", "warning"],
                            cwd=str(ROOT / "backend"), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        for _ in range(60):
            try:
                h = get("/api/health"); break
            except Exception:
                time.sleep(0.5)
        else:
            raise SystemExit("server did not start: " + proc.stderr.read().decode()[-800:])
        assert h["status"] == "ok", h
        assert set(a["key"] for a in h["agents"]) == {"intake", "extraction", "consensus", "verification", "triage", "order"}
        samples = get("/api/samples")["samples"]
        synth = [s for s in samples if s["kind"] == "synthetic"]
        assert len(synth) >= 12, f"expected ≥12 synthetic samples, got {len(synth)}"
        name = os.environ.get("PILLSPARK_CHECK_SAMPLE", synth[0]["name"])
        created = post("/api/orders", {"sample": name})
        oid = created["order_id"]
        seen = 0
        for _ in range(240):
            st = get(f"/api/orders/{oid}/status?since={seen}")
            seen = st["next"]
            if st["status"] in ("blocked", "ready", "error"):
                break
            time.sleep(0.5)
        assert st["status"] in ("blocked", "ready"), f"order ended {st['status']}: {st.get('error')}"
        o = get(f"/api/orders/{oid}")
        fields = o["fields"]
        assert len(fields) == 12, len(fields)
        allowed = {"verified", "needs_review", "unreadable", "missing", "resolved"}
        for k, f in fields.items():
            assert f["status"] in allowed, (k, f["status"])
            if f["status"] == "verified":
                assert f["value"] is not None, f"verified field {k} has no value"
            if f["status"] == "unreadable":
                assert f["value"] is None, f"unreadable field {k} still shows a value (guessing!)"
                assert f["pharmacist_question"], f"unreadable field {k} has no pharmacist question"
            if f["status"] in ("needs_review", "unreadable"):
                assert f["reasons"], f"flagged field {k} has no reasons"
        assert (o["status"] == "blocked") == bool(o["review_queue"]), (o["status"], o["review_queue"])
        agents_seen = {e["agent"] for e in o["events"]}
        assert {"intake", "extraction", "consensus", "verification", "triage", "order"} <= agents_seen, agents_seen
        assert o["llm_mode"] == h["llm_mode"]
        # pharmacist resolve flow on first flagged field (if any)
        if o["review_queue"]:
            f0 = o["review_queue"][0]
            r = post(f"/api/orders/{oid}/resolve", {"field": f0, "value": "pharmacist-entered", "note": "gate check", "action": "accept"})
            assert r["field"]["status"] == "resolved" and f0 not in r["review_queue"], r
        print(json.dumps({"order": oid, "mode": o["llm_mode"], "status": o["status"], "metrics": o["metrics"], "review_queue": o["review_queue"]}))
        print("API CHECK PASSED")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    main()
