"""Pod entry point for Prep (copy to agents/prep/app.py in the Round 3 pod repo).

Makes the Round 2 Prep Manager answer the CUBE v1.0 contract. Requires the
`submissions.kl2400033283` package on PYTHONPATH (e.g. vendor it under the pod root).
Run:  uvicorn agents.prep.app:app --port 8102
"""
from shared.utils.server import make_app

from submissions.kl2400033283.agent.config import AGENT_VERSION
from submissions.kl2400033283.agent.pod_adapter import handle as _handle

STAGE = "prep"


def handle(request: dict) -> dict:
    return _handle(request)


app = make_app(STAGE, handle, version=AGENT_VERSION)
