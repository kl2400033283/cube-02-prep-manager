"""Shared test helpers: isolated temp database per test, scenario inputs."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from submissions.kl2400033283.agent.core.prep_agent import PrepManagerAgent  # noqa: E402
from submissions.kl2400033283.agent.db.database import TenantDatabase  # noqa: E402
from submissions.kl2400033283.agent.schemas.evidence import PrepInspectionInput  # noqa: E402
from submissions.kl2400033283.agent.sim.scenarios import BY_ID  # noqa: E402


def temp_db() -> TenantDatabase:
    d = Path(tempfile.mkdtemp(prefix="prepmgr-test-"))
    return TenantDatabase(d / "test.db", d / "uploads")


def make_agent(**kw) -> PrepManagerAgent:
    from submissions.kl2400033283.agent.vision.providers.free_vision_provider import FreeVisionProvider
    kw.setdefault("mode", "cv")
    # Tests never reach a real network service unless they inject a transport explicitly.
    from submissions.kl2400033283.agent.vision.providers.ollama_provider import OllamaVisionProvider
    kw.setdefault("free_vision", FreeVisionProvider(api_key=""))
    kw.setdefault("ollama", OllamaVisionProvider(disabled=True))  # a developer's local Ollama must not change routing
    return PrepManagerAgent(db=kw.pop("db", None) or temp_db(), **kw)


def scenario_input(scenario_id: str, org: str = "org_demo_alpha", **overrides) -> PrepInspectionInput:
    s = BY_ID[scenario_id]
    unit = dict(s.unit)
    calibrated = overrides.pop("station_calibrated", True)
    unit.update(overrides)
    return PrepInspectionInput(org_id=org, image_paths=[str(s.ensure_rendered())],
                               image_asset_ids=[f"scenario:{scenario_id}"], station_calibrated=calibrated, **unit)
