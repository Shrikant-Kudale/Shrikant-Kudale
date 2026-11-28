#!/usr/bin/env python3
"""
Builds assets/gallery.svg, an animated photo carousel for the GitHub profile README.

* Reads every image in the gallery/ folder (sorted by file name).
* Images enter small from the right, grow with a white frame in the centre,
  then shrink and fade as they leave to the left. One image every 2 seconds.
* Everything is embedded inside the one SVG, so it plays inside a README.
"""
import base64
import io
import math
import re
import sys
from pathlib import Path

from PIL import Image, ImageOps

# ------------------------------------------------------------------ settings
ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "gallery"
OUT_FILE = ROOT / "assets" / "gallery.svg"
EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

SECONDS_PER_IMAGE = 2.0          # time for the reel to move one image along
CANVAS_W, CANVAS_H = 1200, 360   # SVG canvas (it scales to the README width)
IMG_W, IMG_H = 360, 270          # centre image size (4:3)
FRAME_PX = 8                     # white frame thickness around the centre image
PANEL_COLOR = "#16122E"          # dark panel behind the reel, None = transparent
PANEL_BORDER = "#4B3D8F"
MAX_SVG_BYTES = 3_200_000        # the script lowers image quality to stay under this

# Where each slot sits (distance from the centre, in pixels) at whole-slot steps
SLOT_X = [0, 312, 489, 609, 725]
VISIBLE = 3.5                    # slots visible on each side of the centre
STEPS_PER_SLOT = 8               # smoothness of the animation keyframes
MIN_SLOTS = 8                    # reel repeats images if there are fewer than this


# ------------------------------------------------------------------ the maths
def smoothstep(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def x_at(a):
    """Horizontal position for slot offset a (0 = centre). Smooth, odd function."""
    s = -1 if a < 0 else 1
    a = abs(a)
    i = min(int(a), len(SLOT_X) - 2)
    t = a - i
    pts = [-SLOT_X[1]] + SLOT_X          # odd extension for a < 0
    p0, p1, p2, p3 = pts[i], pts[i + 1], pts[i + 2], pts[min(i + 3, len(pts) - 1)]
    v = 0.5 * ((2 * p1) + (-p0 + p2) * t
               + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t
               + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3)
    return s * v


def scale_at(a):
    return 0.27 + 0.73 * math.exp(-((abs(a) / 1.1) ** 2))


def opacity_at(a):
    a = abs(a)
    base = 0.45 + 0.55 * math.exp(-((a / 1.0) ** 2))
    edge = smoothstep((VISIBLE - a) / 0.6)
    return base * edge


def frame_at(a):
    return smoothstep(1 - abs(a) / 0.6)


# ------------------------------------------------------------------ images
def natural_key(p):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", p.name)]


def list_images():
    if not SRC_DIR.is_dir():
        return []
    return sorted((p for p in SRC_DIR.iterdir()
                   if p.is_file() and p.suffix.lower() in EXTENSIONS), key=natural_key)


def encode(path, width, quality):
    """Resize to a 4:3 tile (nothing is cropped) and return base64 JPEG text."""
    height = round(width * 3 / 4)
    bg = (22, 18, 46)
    im = ImageOps.exif_transpose(Image.open(path))
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        flat = Image.new("RGB", im.size, bg)
        flat.paste(im, mask=im.split()[-1])
        im = flat
    im = im.convert("RGB")
    im = ImageOps.contain(im, (width, height), Image.LANCZOS)
    tile = Image.new("RGB", (width, height), bg)
    tile.paste(im, ((width - im.width) // 2, (height - im.height) // 2))
    buf = io.BytesIO()
    tile.save(buf, "JPEG", quality=quality, optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def encode_all(paths):
    for width, quality in [(640, 78), (560, 72), (520, 66), (480, 60), (440, 52), (400, 46)]:
        data = [encode(p, width, quality) for p in paths]
        if sum(len(d) for d in data) <= MAX_SVG_BYTES:
            break
    return data


# ------------------------------------------------------------------ the SVG
def build_svg(images_b64):
    n_real = len(images_b64)
    n = max(n_real, MIN_SLOTS)                 # number of slots in the loop
    duration = n * SECONDS_PER_IMAGE

    # sample the motion from a = +VISIBLE (right edge) to a = -VISIBLE (left edge)
    samples = int(round(2 * VISIBLE * STEPS_PER_SLOT))
    a_values = [VISIBLE - k / STEPS_PER_SLOT for k in range(samples + 1)]

    def pct(a):
        return (n - VISIBLE - a) / n * 100

    slide, frame = [], []
    first = a_values[0]
    slide.append("0%%{transform:translate(%.1fpx,0) scale(%.4f);opacity:0}" %
                 (x_at(first), scale_at(first)))
    frame.append("0%{opacity:0}")
    for a in a_values:
        slide.append("%.4f%%{transform:translate(%.1fpx,0) scale(%.4f);opacity:%.3f}" %
                     (pct(a), x_at(a), scale_at(a), opacity_at(a)))
        frame.append("%.4f%%{opacity:%.3f}" % (pct(a), frame_at(a)))

    hw, hh = IMG_W / 2, IMG_H / 2
    f = FRAME_PX
    parts = []
    parts.append(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" '
        'role="img" aria-label="Rotating carousel of photos, certificates and achievements">'
        % (CANVAS_W, CANVAS_H, CANVAS_W, CANVAS_H))
    parts.append(
        '<defs>'
        '<clipPath id="tile"><rect x="%g" y="%g" width="%d" height="%d" rx="6"/></clipPath>'
        '<clipPath id="view"><rect width="%d" height="%d" rx="18"/></clipPath>'
        '</defs>' % (-hw, -hh, IMG_W, IMG_H, CANVAS_W, CANVAS_H))
    parts.append(
        '<style>'
        '.s{animation:slide %.1fs linear infinite}'
        '.f{animation:frame %.1fs linear infinite}'
        '@keyframes slide{%s}'
        '@keyframes frame{%s}'
        '</style>' % (duration, duration, "".join(slide), "".join(frame)))
    parts.append('<g clip-path="url(#view)">')
    if PANEL_COLOR:
        parts.append('<rect x="1" y="1" width="%d" height="%d" rx="18" fill="%s" stroke="%s" '
                     'stroke-width="2"/>' % (CANVAS_W - 2, CANVAS_H - 2, PANEL_COLOR, PANEL_BORDER))
    parts.append('<g transform="translate(%g %g)">' % (CANVAS_W / 2, CANVAS_H / 2))

    for i in range(n):
        # at time 0, slot i sits i slots to the right of the centre
        delay = ((n - VISIBLE - i) % n) * SECONDS_PER_IMAGE
        d = "animation-delay:-%.2fs" % delay
        parts.append(
            '<g class="s" style="opacity:0;%s">'
            '<image href="data:image/jpeg;base64,%s" x="%g" y="%g" width="%d" height="%d" '
            'preserveAspectRatio="xMidYMid slice" clip-path="url(#tile)"/>'
            '<g class="f" style="opacity:0;%s">'
            '<rect x="%g" y="%g" width="%g" height="%g" rx="8" fill="none" stroke="#8B5CF6" '
            'stroke-opacity="0.55" stroke-width="3"/>'
            '<rect x="%g" y="%g" width="%g" height="%g" rx="4" fill="none" stroke="#FFFFFF" '
            'stroke-width="%d"/>'
            '</g></g>' % (
                d, images_b64[i % n_real], -hw, -hh, IMG_W, IMG_H, d,
                -hw - f - 1.5, -hh - f - 1.5, IMG_W + 2 * f + 3, IMG_H + 2 * f + 3,
                -hw - f / 2, -hh - f / 2, IMG_W + f, IMG_H + f, f))
    parts.append('</g></g></svg>')
    return "".join(parts)


def main():
    paths = list_images()
    if not paths:
        print("No images found in gallery/, skipping the carousel.")
        return 0
    print("Found %d images" % len(paths))
    images = encode_all(paths)
    svg = build_svg(images)
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(svg, encoding="utf-8")
    print("Wrote %s (%.2f MB)" % (OUT_FILE.relative_to(ROOT), len(svg) / 1e6))
    return 0


if __name__ == "__main__":
    sys.exit(main())
