"""
Writes prescription images for demoing the safety checks.

    python scripts/make_demo_prescription.py [--out DIR]

Produces two printed prescriptions in `demo_prescriptions/`:

  pregnancy_unsafe.png
      Four medicines that are individually ordinary but contraindicated in
      pregnancy -- doxycycline, diclofenac, fluconazole, ramipril. Upload this
      while logged in as the pregnant demo profile and every one comes back
      flagged critical. Real prescribing errors look exactly like this: nothing
      exotic, just a drug chosen without the pregnancy in mind.

  banned_combination.png
      A fixed-dose combination prohibited by the CDSCO, to show the
      banned-medicine check firing on something the patient could buy over a
      counter today.

Printed rather than handwritten on purpose: the demo is about the safety
screening, and a handwriting misread would send the room's attention to OCR
instead.
"""
import argparse
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # pragma: no cover
    sys.exit("Pillow is required: pip install pillow")

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "demo_prescriptions"

SHEETS = {
    "pregnancy_unsafe.png": {
        "clinic": "SUNRISE POLYCLINIC",
        "sub": "Dr. R. Venkatesh, MBBS, MD  ·  Reg. No. KMC-48221",
        "patient": "Patient: Priya Sharma        Age: 28 / F        Date: today",
        "lines": [
            "1.  Doxycycline 100mg Tablet        1-0-1   x 7 days",
            "2.  Diclofenac 50mg Tablet          1-0-1   after food",
            "3.  Fluconazole 150mg Tablet        weekly  x 2 weeks",
            "4.  Ramipril 5mg Tablet             0-0-1   x 30 days",
        ],
        "footer": "Review after 2 weeks",
    },
    "banned_combination.png": {
        "clinic": "CITY CARE CLINIC",
        "sub": "Dr. A. Kulkarni, MBBS  ·  Reg. No. MMC-71330",
        "patient": "Patient: Priya Sharma        Age: 28 / F        Date: today",
        "lines": [
            "1.  Nimesulide 100mg + Paracetamol 325mg    1-0-1  x 5 days",
            "2.  Paracetamol 650mg Tablet                 SOS for fever",
        ],
        "footer": "Take after food. Return if fever persists.",
    },
}


def _font(size: int, bold: bool = False):
    for name in (("arialbd.ttf", "arial.ttf") if bold else ("arial.ttf",)):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render(spec: dict, path: Path) -> None:
    width, height = 1240, 780
    im = Image.new("RGB", (width, height), "white")
    d = ImageDraw.Draw(im)

    d.text((60, 44), spec["clinic"], fill="black", font=_font(38, bold=True))
    d.text((60, 96), spec["sub"], fill="#333333", font=_font(22))
    d.line([(60, 140), (width - 60, 140)], fill="#888888", width=2)

    d.text((60, 168), spec["patient"], fill="black", font=_font(24))
    d.line([(60, 208), (width - 60, 208)], fill="#cccccc", width=1)

    d.text((60, 240), "Rx", fill="black", font=_font(44, bold=True))

    y = 310
    for line in spec["lines"]:
        d.text((80, y), line, fill="black", font=_font(28))
        y += 62

    d.text((60, y + 40), spec["footer"], fill="#333333", font=_font(24))
    d.text(
        (60, height - 90),
        "Signature: ______________________",
        fill="#333333",
        font=_font(24),
    )

    im.save(path)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    for filename, spec in SHEETS.items():
        path = args.out / filename
        render(spec, path)
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
