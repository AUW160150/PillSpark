"""Block Convey PRISM wrapper. Every LLM call and every finished order is traced; no-op without keys."""
import time
import uuid
from typing import Any, Dict, List, Optional

from . import config

try:
    from prismtrace import PRISMtrace
except Exception:  # SDK missing → stay silent but functional
    PRISMtrace = None  # type: ignore


class Prism:
    def __init__(self):
        self.enabled = bool(config.PRISM_ENABLED and PRISMtrace is not None)
        self.client = None
        self.agent_id = "pillspark-fax-intake"
        if self.enabled:
            try:
                self.client = PRISMtrace(api_key=config.PRISM_API_KEY, host=config.PRISM_HOST,
                                         project_id=config.PRISM_PROJECT_ID)
            except Exception as e:
                self.enabled = False
                self.last_error = str(e)

    def trace_llm(self, *, model: str, prompt_messages: List[Dict[str, Any]], output: str, latency_ms: int,
                  session_id: str, agent_name: str, metadata: Dict[str, Any], tokens_in: int = 0, tokens_out: int = 0) -> Optional[str]:
        """Logs one vision call. Image bytes are replaced by a placeholder so PHI-free traces stay small."""
        if not self.enabled or not self.client:
            return None
        trace_id = str(uuid.uuid4())
        try:
            self.client.trace_llm(model=model, input_messages=prompt_messages, output=output, latency_ms=latency_ms,
                                  token_count_input=tokens_in, token_count_output=tokens_out, trace_id=trace_id,
                                  agent_id=self.agent_id, agent_name=agent_name, session_id=session_id, metadata=metadata)
            return trace_id
        except Exception as e:
            self.last_error = str(e)
            return None

    def submit_trajectory(self, *, steps: List[Dict[str, Any]], session_id: str, final_status: str, model: str) -> Optional[Dict[str, Any]]:
        if not self.enabled or not self.client:
            return None
        try:
            return self.client.submit_trajectory(steps=steps, agent_name="PillSpark Fax Intake", agent_id=self.agent_id,
                                                 conversation_id=session_id, model=model, final_status=final_status)
        except Exception as e:
            self.last_error = str(e)
            return None

    def flush(self):
        if self.client:
            try:
                self.client.flush(timeout=3.0)
            except Exception:
                pass

    def handshake(self) -> Dict[str, Any]:
        """Diagnostic: POST /api/setup-doctor/handshake with a test trace."""
        if not config.PRISM_ENABLED:
            return {"ok": False, "reason": "PRISM keys not configured"}
        import httpx
        try:
            r = httpx.post(f"{config.PRISM_HOST}/api/setup-doctor/handshake",
                           headers={"X-PRISMtrace-Key": config.PRISM_API_KEY},
                           json={"project_id": config.PRISM_PROJECT_ID, "send_test_trace": True}, timeout=20)
            return {"ok": r.status_code == 200, "status": r.status_code, "body": r.text[:500]}
        except Exception as e:
            return {"ok": False, "reason": str(e)}


prism = Prism()
