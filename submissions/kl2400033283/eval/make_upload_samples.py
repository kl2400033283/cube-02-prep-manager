"""Generate test photos of one prepped unit (general merchandise) to upload in the console.

PASS_unit_front + PASS_unit_back should PASS (FNSKU flat, original barcode covered).
PASS_unit_front + FAIL_unit_back_barcode_exposed should FAIL (retail UPC exposed).
Usage: python eval/make_upload_samples.py [out_dir]
"""
import sys
from pathlib import Path

import numpy as np
import zxingcpp
from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "fixtures" / "upload_samples"
OUT.mkdir(parents=True, exist_ok=True)
W, H = 1600, 1200
FNSKU = "X003K7P2QD"


def font(size, bold=False):
    for name in (("arialbd.ttf" if bold else "arial.ttf"), "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def background():
    rng = np.random.default_rng(7)
    bg = np.full((H, W, 3), (205, 208, 212), np.float32)            # grey bench
    bg += rng.normal(0, 2.0, bg.shape)
    img = Image.fromarray(np.clip(bg, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(img)
    # cardboard face of the box, evenly lit
    box = (200, 150, 1400, 1050)
    face = np.full((box[3] - box[1], box[2] - box[0], 3), (176, 136, 92), np.float32)
    face += rng.normal(0, 3.0, face.shape)                           # fibre texture
    img.paste(Image.fromarray(np.clip(face, 0, 255).astype(np.uint8)), box[:2])
    d.rectangle(box, outline=(120, 90, 60), width=4)
    return img, d, box


def barcode(text, fmt, height):
    b = zxingcpp.create_barcode(text, getattr(zxingcpp.BarcodeFormat, fmt))
    im = Image.fromarray(np.array(zxingcpp.write_barcode_to_image(b, scale=3, add_hrt=False, add_quiet_zones=True)))
    return im.convert("RGB").resize((im.width, height), Image.NEAREST)


def fnsku_label(img, d, x, y):
    bc = barcode(FNSKU, "Code128", 130)
    lw, lh = max(520, bc.width + 60), 330
    d.rectangle([x, y, x + lw, y + lh], fill=(250, 250, 250))
    img.paste(bc, (x + (lw - bc.width) // 2, y + 25))
    d.text((x + 30, y + 195), FNSKU, fill=(0, 0, 0), font=font(38))
    d.text((x + 30, y + 250), "Wireless Mouse - Black", fill=(20, 20, 20), font=font(32))
    d.text((x + 30, y + 290), "New", fill=(20, 20, 20), font=font(28))


def front():
    img, d, box = background()
    fnsku_label(img, d, 330, 330)
    d.text((1000, 900), "MADE IN INDIA", fill=(60, 40, 25), font=font(40, True))
    return img.filter(ImageFilter.GaussianBlur(0.6))


def back(exposed=False):
    img, d, box = background()
    d.text((330, 300), "GAME GEAR INC.", fill=(60, 40, 25), font=font(56, True))
    d.text((330, 380), "KEEP DRY", fill=(60, 40, 25), font=font(44, True))
    if exposed:   # a retail UPC left uncovered (bad prep)
        bc = barcode("012345678905", "UPCA", 180)
        d.rectangle([700, 600, 700 + bc.width + 40, 860], fill=(250, 250, 250))
        img.paste(bc, (720, 620))
        d.text((740, 810), "0 12345 67890 5", fill=(0, 0, 0), font=font(40))
    else:         # original UPC covered by an opaque blank label (good prep)
        d.rectangle([700, 600, 1150, 860], fill=(246, 246, 244))
    return img.filter(ImageFilter.GaussianBlur(0.6))


front().save(OUT / "PASS_unit_front.png")
back().save(OUT / "PASS_unit_back.png")
back(exposed=True).save(OUT / "FAIL_unit_back_barcode_exposed.png")
print("ok", FNSKU)
