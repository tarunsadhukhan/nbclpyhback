"""Lift the NBJ mark off the annual-report photo into a clean transparent PNG.

The scan is navy ink on off-white paper under uneven light, so a flat cutoff
either eats the thin strokes or keeps the paper's grey cast. Instead the
luminance is ramped between two thresholds: that keeps the antialiased stroke
edges soft while dropping the paper entirely.
"""
from PIL import Image

SRC = "images/1.jpg"
CROP = (1150, 720, 1720, 1220)
OUT = "scratchpad/nbj-logo.png"

# Ink is fully opaque below LO, fully transparent above HI; between = ramp.
LO, HI = 45, 130  # paper measures ~168, ink ~5-30
NAVY = (26, 42, 112)  # sampled from the darkest ink pixels, flattened

src = Image.open(SRC).convert("RGB").crop(CROP)
w, h = src.size
px = src.load()

out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
op = out.load()
for y in range(h):
    for x in range(w):
        r, g, b = px[x, y]
        lum = 0.299 * r + 0.587 * g + 0.114 * b
        if lum >= HI:
            continue
        a = 255 if lum <= LO else int(255 * (HI - lum) / (HI - LO))
        op[x, y] = (*NAVY, a)

# Trim to the ink, then pad 6% so the mark is not flush to the edge.
box = out.getbbox()
out = out.crop(box)
pad = int(max(out.size) * 0.06)
side = max(out.size) + 2 * pad
canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
canvas.paste(out, ((side - out.width) // 2, (side - out.height) // 2))
canvas = canvas.resize((300, 300), Image.LANCZOS)  # backend thumbnails anything >500px to 300
canvas.save(OUT)
print(f"ink bbox={box} -> {OUT} {canvas.size}")
