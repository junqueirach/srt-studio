"""Build the SRT Studio icon files from concept A ("caption bubble", chosen 2026-10-15).

    python tools/make_icon.py            → assets/icon.ico (16–256 px), assets/icon-*.png

Large sizes are drawn at 4x and reduced; 16–32 px are drawn on the pixel grid with simpler proportions
(thicker bars, smaller tail) so they stay sharp in the title bar and the taskbar. Needs Pillow (build only).
"""
from pathlib import Path

from PIL import Image, ImageDraw

NAVY, BLUE, WHITE, YELLOW = (29, 42, 60, 255), (61, 139, 253, 255), (255, 255, 255, 255), (255, 209, 102, 255)
OUT = Path(__file__).resolve().parents[1] / "assets"


def draw(size: int) -> Image.Image:
    small = size <= 32
    k = 1 if small else 4                      # supersampling for the large sizes
    S = size * k
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    u = S / 64                                 # the master drawing is on a 64-unit grid
    d.rounded_rectangle([0, 0, S - 1, S - 1], radius=round((10 if small else 14) * u), fill=NAVY)
    if small:
        # pixel-grid version: bubble 3..61 x 10..44, tail to y 55, bars 7 units high
        bx0, by0, bx1, by1 = 6 * u, 13 * u, 58 * u, 44 * u
        d.rounded_rectangle([round(bx0), round(by0), round(bx1), round(by1)], radius=max(1, round(5 * u)), fill=BLUE)
        d.polygon([(round(17 * u), round(43 * u)), (round(31 * u), round(43 * u)), (round(17 * u), round(56 * u))],
                  fill=BLUE)
        d.rectangle([round(12 * u), round(20 * u), round(52 * u), round(27 * u) - 1], fill=WHITE)
        d.rectangle([round(12 * u), round(31 * u), round(38 * u), round(38 * u) - 1], fill=YELLOW)
    else:
        d.rounded_rectangle([7 * u, 16 * u, 57 * u, 44 * u], radius=5 * u, fill=BLUE)
        d.polygon([(21 * u, 43 * u), (30 * u, 43 * u), (21 * u, 52 * u)], fill=BLUE)
        d.rounded_rectangle([15 * u, 25 * u, 49 * u, 30 * u], radius=2.5 * u, fill=WHITE)
        d.rounded_rectangle([15 * u, 33 * u, 37 * u, 38 * u], radius=2.5 * u, fill=YELLOW)
    return img if k == 1 else img.resize((size, size), Image.LANCZOS)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    images = {s: draw(s) for s in sizes}
    images[256].save(OUT / "icon.ico", sizes=[(s, s) for s in sizes],
                     append_images=[images[s] for s in sizes if s != 256])
    for s in (16, 20, 24, 32, 48, 64, 256):
        images[s].save(OUT / f"icon-{s}.png")
    print("written:", OUT / "icon.ico", "and icon-{16,20,24,32,48,64,256}.png")


if __name__ == "__main__":
    main()
