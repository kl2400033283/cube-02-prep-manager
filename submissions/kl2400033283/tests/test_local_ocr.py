"""Local OCR provider: real-photo path that needs no API key (offline RapidOCR + zxing-cpp)."""

import tempfile
import unittest
from pathlib import Path

from _helpers import make_agent, scenario_input
from submissions.kl2400033283.agent.schemas.evidence import PrepInspectionInput
from submissions.kl2400033283.agent.sim.scene_renderer import SceneSpec, render_scene
from submissions.kl2400033283.agent.vision.providers.ocr_provider import LocalOCRProvider, available


class _Unavailable(LocalOCRProvider):
    @property
    def available(self):
        return False


@unittest.skipUnless(available(), "rapidocr-onnxruntime / zxing-cpp not installed")
class TestLocalOCR(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.agent = make_agent(mode="ocr")

    def verdicts(self, rec):
        return {c.check_key: (c.verdict.value, c.reason_code) for c in rec.checks}

    def test_reads_warning_but_never_guesses_bag_or_geometry(self):
        rec = self.agent.inspect(scenario_input("sealed-polybag", station_calibrated=False))
        v = self.verdicts(rec)
        self.assertEqual(v["suffocation_warning"][0], "PASS")
        self.assertEqual(v["polybag_present_sealed"][0], "UNCERTAIN")
        self.assertEqual(v["fnsku_label_placement"][0], "UNCERTAIN")
        self.assertEqual(rec.perception.provider, "local_ocr")
        self.assertEqual(rec.perception.cost_usd, 0.0)

    def test_reads_expiry_and_marks(self):
        rec = self.agent.inspect(scenario_input("correct-prep", station_calibrated=False))
        v = self.verdicts(rec)
        self.assertEqual(v["expiry_date"], ("PASS", "EXPIRY_VISIBLE"))
        self.assertEqual(v["handling_marks"][0], "PASS")

    def test_wrong_fnsku_on_label_fails(self):
        rec = self.agent.inspect(scenario_input("correct-prep", station_calibrated=False, fnsku="X00ZZZZ999"))
        self.assertEqual(self.verdicts(rec)["fnsku_label_placement"], ("FAIL", "FNSKU_MISMATCH"))

    def test_iso_expiry_format_fails(self):
        path = Path(tempfile.mkdtemp()) / "iso.jpg"
        render_scene(SceneSpec("U-ISO", 321, "box", expiry="legible", expiry_text="2027-08-15",
                               fnsku_text="X00ISO0001"), path)
        rec = self.agent.inspect(PrepInspectionInput(unit_id="U-ISO", org_id="org_demo_alpha", fnsku="X00ISO0001",
                                                     category="consumable_dated", wo_expiry_date=True,
                                                     image_paths=[str(path)]))
        self.assertEqual(self.verdicts(rec)["expiry_date"], ("FAIL", "EXPIRY_FORMAT_INVALID"))

    def test_auto_routing_without_key(self):
        agent = make_agent(mode="auto")
        self.assertEqual(agent.route(calibrated=False)[0].name, "local_ocr")
        self.assertEqual(agent.route(calibrated=True)[0].name, "station_cv")
        self.assertEqual(make_agent(mode="auto", ocr=_Unavailable()).route(calibrated=False)[0].name, "station_cv")


if __name__ == "__main__":
    unittest.main()
