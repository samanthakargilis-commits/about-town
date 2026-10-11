"""Draw the Fogbook icons: a pumpkin tile, a cream datebook page and a puff of fog."""
import pathlib
from PIL import Image, ImageDraw

OUT = pathlib.Path(__file__).resolve().parent.parent / "app" / "icons"
PUMPKIN, CREAM, COCOA, CHERRY, FOG = (233, 135, 75), (251, 245, 236), (61, 43, 38), (184, 71, 58), (255, 253, 248)


def tile(size, pad_ratio=0.0):
    k = 4                                   # draw big, shrink for smooth edges
    S = size * k
    img = Image.new("RGB", (S, S), PUMPKIN)
    d = ImageDraw.Draw(img)
    s = S * (1 - pad_ratio)
    o = (S - s) / 2
    # datebook page
    x0, y0, x1, y1 = o + s * .2, o + s * .2, o + s * .8, o + s * .76
    d.rounded_rectangle([x0, y0, x1, y1], radius=s * .07, fill=CREAM)
    d.rounded_rectangle([x0, y0, x1, y0 + s * .15], radius=s * .07, fill=COCOA)
    d.rectangle([x0, y0 + s * .08, x1, y0 + s * .15], fill=COCOA)
    for cx in (x0 + s * .14, x1 - s * .14):
        d.rounded_rectangle([cx - s * .028, y0 - s * .06, cx + s * .028, y0 + s * .05], radius=s * .028, fill=CREAM)
    # a planned day: one cherry dot in the grid
    for i in range(3):
        for j in range(2):
            cx, cy = x0 + s * (.13 + i * .17), y0 + s * (.26 + j * .14)
            r = s * .035
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=CHERRY if (i, j) == (1, 0) else (234, 223, 210))
    # fog rolling in over the bottom
    for cx, cy, r in ((.30, .74, .11), (.47, .69, .14), (.65, .73, .12), (.78, .78, .08)):
        d.ellipse([o + s * (cx - r), o + s * (cy - r), o + s * (cx + r), o + s * (cy + r)], fill=FOG)
    d.rounded_rectangle([o + s * .2, o + s * .74, o + s * .86, o + s * .86], radius=s * .06, fill=FOG)
    return img.resize((size, size), Image.LANCZOS)


OUT.mkdir(parents=True, exist_ok=True)
tile(192).save(OUT / "icon-192.png")
tile(512).save(OUT / "icon-512.png")
tile(512, pad_ratio=.2).save(OUT / "icon-512-maskable.png")
tile(180).save(OUT / "apple-touch-icon.png")
print("icons written")
