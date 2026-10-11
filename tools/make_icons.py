"""Draw the app icons (a sunset-gradient tile with a calendar and a star)."""
import pathlib
from PIL import Image, ImageDraw

OUT = pathlib.Path(__file__).resolve().parent.parent / "app" / "icons"


def tile(size, pad_ratio=0.0):
    img = Image.new("RGB", (size, size))
    top, mid, bot = (255, 154, 139), (255, 90, 120), (123, 92, 255)
    px = img.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * size)
            a, b, u = (top, mid, t * 2) if t < .5 else (mid, bot, (t - .5) * 2)
            px[x, y] = tuple(int(a[i] + (b[i] - a[i]) * u) for i in range(3))
    d = ImageDraw.Draw(img)
    s = size * (1 - pad_ratio)
    o = (size - s) / 2
    # calendar body
    x0, y0, x1, y1 = o + s * .22, o + s * .26, o + s * .78, o + s * .80
    d.rounded_rectangle([x0, y0, x1, y1], radius=s * .08, fill=(255, 250, 245))
    d.rounded_rectangle([x0, y0, x1, y0 + s * .14], radius=s * .08, fill=(34, 26, 43))
    d.rectangle([x0, y0 + s * .08, x1, y0 + s * .14], fill=(34, 26, 43))
    for cx in (x0 + s * .14, x1 - s * .14):
        d.rounded_rectangle([cx - s * .03, y0 - s * .06, cx + s * .03, y0 + s * .05], radius=s * .03, fill=(255, 250, 245))
    # star
    import math
    cx, cy, r1, r2 = size / 2, o + s * .56, s * .15, s * .065
    pts = []
    for i in range(10):
        ang = -math.pi / 2 + i * math.pi / 5
        r = r1 if i % 2 == 0 else r2
        pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    d.polygon(pts, fill=(255, 182, 39))
    return img


OUT.mkdir(parents=True, exist_ok=True)
tile(192).save(OUT / "icon-192.png")
tile(512).save(OUT / "icon-512.png")
tile(512, pad_ratio=.2).save(OUT / "icon-512-maskable.png")
tile(180).save(OUT / "apple-touch-icon.png")
print("icons written")
