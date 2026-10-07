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

    def test_reads_warning_never_guesses_bag_and_flat_only_when_clean(self):
        rec = self.agent.inspect(scenario_input("sealed-polybag", station_calibrated=False))
        v = self.verdicts(rec)
        self.assertEqual(v["suffocation_warning"][0], "PASS")
        self.assertEqual(v["polybag_present_sealed"][0], "UNCERTAIN")
        self.assertEqual(v["fnsku_label_placement"][0], "PASS")  # clean, evenly lit rectangle

    def test_seam_and_curve_labels_are_never_called_flat(self):
        for sid in ("fnsku-on-seam", "fnsku-on-curve"):
            v = self.verdicts(self.agent.inspect(scenario_input(sid, station_calibrated=False)))
            self.assertNotEqual(v["fnsku_label_placement"][0], "PASS", sid)

    def test_printed_retail_number_under_bars_is_exposed(self):
        from submissions.kl2400033283.agent.vision.providers.ocr_provider import bars_above
        from submissions.kl2400033283.agent.vision.quality import load_image
        import numpy as np, tempfile
        from pathlib import Path
        from PIL import Image, ImageDraw, ImageFont
        im = Image.new("RGB", (900, 600), (190, 150, 100))
        d = ImageDraw.Draw(im)
        d.rectangle([250, 200, 650, 420], fill=(250, 250, 250))
        rng = np.random.default_rng(1)
        x = 280
        while x < 620:
            wbar = int(rng.integers(2, 7))
            d.rectangle([x, 220, x + wbar, 350], fill=(10, 10, 10))
            x += wbar + int(rng.integers(2, 6))
        try:
            font = ImageFont.truetype("arial.ttf", 40)
        except OSError:
            font = ImageFont.load_default()
        d.text((300, 360), "0 12345 67890 5", fill=(0, 0, 0), font=font)
        p = Path(tempfile.mkdtemp()) / "upc.png"
        im.save(p)
        self.assertGreater(bars_above(load_image(p), [300 / 900, 360 / 600, 600 / 900, 400 / 600]), 3.0)
        rec = self.agent.inspect(scenario_input("correct-prep", station_calibrated=False,
                                                image_paths=[str(p)], image_asset_ids=["test"]))
        self.assertEqual(self.verdicts(rec)["original_barcode_covered"][0], "FAIL")
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


class TestTwoViewUnit(unittest.TestCase):
    """Generated upload samples: covered needs >= 2 views; an exposed UPC on the back is caught."""

    @classmethod
    def setUpClass(cls):
        import subprocess, sys, tempfile
        from pathlib import Path
        if not available():
            raise unittest.SkipTest("offline OCR / zxing not installed")
        cls.dir = Path(tempfile.mkdtemp())
        gen = Path(__file__).resolve().parent.parent / "eval" / "make_upload_samples.py"
        subprocess.run([sys.executable, str(gen), str(cls.dir)], check=True, capture_output=True)

    def run_views(self, *names):
        from submissions.kl2400033283.agent.vision.quality import assess_quality, load_image
        from submissions.kl2400033283.agent.vision.providers.ocr_provider import LocalOCRProvider
        imgs = [load_image(self.dir / n) for n in names]
        return LocalOCRProvider().observe(imgs, [assess_quality(i) for i in imgs], False).checks

    @unittest.skipUnless(available(), "offline OCR not installed")
    def test_good_unit_two_views(self):
        c = self.run_views("PASS_unit_front.png", "PASS_unit_back.png")
        self.assertEqual(c["fnsku_label_placement"].state, "FLAT")
        self.assertEqual(c["original_barcode_covered"].state, "COVERED")

    @unittest.skipUnless(available(), "offline OCR not installed")
    def test_exposed_upc_on_back_is_caught(self):
        c = self.run_views("PASS_unit_front.png", "FAIL_unit_back_barcode_exposed.png")
        self.assertEqual(c["original_barcode_covered"].state, "EXPOSED")

    @unittest.skipUnless(available(), "offline OCR not installed")
    def test_one_view_never_claims_covered(self):
        c = self.run_views("PASS_unit_front.png")
        self.assertEqual(c["original_barcode_covered"].state, "INDETERMINATE")
