#!/usr/bin/env python3
"""Generate the GiongDoc app icon (1024x1024 PNG) programmatically.

Motif: a rounded "squircle" tile with a warm-to-indigo gradient, a white
speech bubble, and an audio waveform inside the bubble.

Only numpy + the standard library (zlib/struct) are needed, so this runs on
any machine (CI, Linux, macOS) without Qt or Pillow.

Usage:
    python packaging/make_icon.py [output.png] [--size 1024]
"""
from __future__ import annotations

import argparse
import struct
import zlib
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
DEFAULT_OUT = HERE / "assets" / "icon_1024.png"


# --------------------------------------------------------------------------- #
# Minimal PNG writer (RGBA, 8-bit)
# --------------------------------------------------------------------------- #
def write_png(path: Path, rgba: np.ndarray) -> None:
    if rgba.dtype != np.uint8 or rgba.ndim != 3 or rgba.shape[2] != 4:
        raise ValueError("expected HxWx4 uint8 array")
    h, w, _ = rgba.shape
    raw = np.empty((h, 1 + w * 4), dtype=np.uint8)
    raw[:, 0] = 0  # filter type: None
    raw[:, 1:] = rgba.reshape(h, w * 4)

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)  # 8-bit RGBA
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw.tobytes(), 9))
        + chunk(b"IEND", b"")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)


# --------------------------------------------------------------------------- #
# Signed distance helpers (negative = inside). Coverage gives anti-aliasing.
# --------------------------------------------------------------------------- #
def sd_round_rect(x, y, cx, cy, hw, hh, r):
    qx = np.abs(x - cx) - (hw - r)
    qy = np.abs(y - cy) - (hh - r)
    outside = np.hypot(np.maximum(qx, 0), np.maximum(qy, 0))
    inside = np.minimum(np.maximum(qx, qy), 0)
    return outside + inside - r


def sd_triangle(x, y, a, b, c):
    """Signed distance to triangle abc (Inigo Quilez formulation)."""
    p = np.stack([x, y], axis=-1)
    a, b, c = (np.asarray(v, dtype=np.float64) for v in (a, b, c))
    e0, e1, e2 = b - a, c - b, a - c
    v0, v1, v2 = p - a, p - b, p - c

    def seg(v, e):
        t = np.clip((v @ e) / (e @ e), 0.0, 1.0)[..., None]
        d = v - e * t
        return (d**2).sum(-1)

    s = np.sign(e0[0] * e2[1] - e0[1] * e2[0])

    def cross(v, e):
        return s * (v[..., 0] * e[1] - v[..., 1] * e[0])

    d = np.minimum(np.minimum(seg(v0, e0), seg(v1, e1)), seg(v2, e2))
    sgn = np.minimum(np.minimum(cross(v0, e0), cross(v1, e1)), cross(v2, e2))
    return -np.sqrt(d) * np.sign(sgn)


def coverage(sd, aa=1.0):
    return np.clip(0.5 - sd / aa, 0.0, 1.0)


def over(dst_rgb, dst_a, src_rgb, src_a):
    """Porter-Duff 'over' with straight (non-premultiplied) colours."""
    out_a = src_a + dst_a * (1 - src_a)
    safe = np.where(out_a > 0, out_a, 1)
    out_rgb = (src_rgb * src_a[..., None] + dst_rgb * (dst_a * (1 - src_a))[..., None]) / safe[..., None]
    return out_rgb, out_a


# --------------------------------------------------------------------------- #
def render(size: int = 1024) -> np.ndarray:
    s = size / 1024.0  # design is authored on a 1024 grid
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float64) + 0.5

    rgb = np.zeros((size, size, 3))
    alpha = np.zeros((size, size))

    # 1. Background tile (macOS Big Sur style: ~824px tile with margins).
    tile_sd = sd_round_rect(xx, yy, 512 * s, 512 * s, 412 * s, 412 * s, 185 * s)
    t = np.clip((xx + yy) / (2 * size), 0, 1)[..., None]  # diagonal gradient
    top = np.array([1.00, 0.55, 0.30])  # warm orange
    bot = np.array([0.36, 0.25, 0.85])  # indigo
    grad = top * (1 - t) + bot * t
    # soft top highlight
    hl = np.clip(1 - (yy - 100 * s) / (500 * s), 0, 1)[..., None] * 0.10
    grad = np.clip(grad + hl, 0, 1)
    rgb, alpha = over(rgb, alpha, grad, coverage(tile_sd))

    # 2. Drop shadow for the bubble.
    bub = dict(cx=512 * s, cy=470 * s, hw=290 * s, hh=215 * s, r=110 * s)
    tail = ((330 * s, 620 * s), (450 * s, 650 * s), (285 * s, 770 * s))
    shadow_sd = np.minimum(
        sd_round_rect(xx, yy - 18 * s, bub["cx"], bub["cy"], bub["hw"], bub["hh"], bub["r"]),
        sd_triangle(xx, yy - 18 * s, *tail),
    )
    shadow_a = coverage(shadow_sd, aa=40 * s) * 0.28 * coverage(tile_sd)
    rgb, alpha = over(rgb, alpha, np.zeros_like(rgb) + 0.10, shadow_a)

    # 3. White speech bubble (rounded rect + tail).
    bubble_sd = np.minimum(
        sd_round_rect(xx, yy, bub["cx"], bub["cy"], bub["hw"], bub["hh"], bub["r"]),
        sd_triangle(xx, yy, *tail),
    )
    white = np.zeros_like(rgb) + np.array([1.0, 0.99, 0.97])
    rgb, alpha = over(rgb, alpha, white, coverage(bubble_sd))

    # 4. Waveform bars inside the bubble (gradient-coloured, symmetric).
    heights = [70, 140, 230, 320, 210, 290, 180, 110, 60]
    bar_w = 34 * s
    gap = 22 * s
    total = len(heights) * bar_w + (len(heights) - 1) * gap
    x0 = bub["cx"] - total / 2 + bar_w / 2
    wave_sd = np.full_like(xx, 1e9)
    for i, h in enumerate(heights):
        cx = x0 + i * (bar_w + gap)
        wave_sd = np.minimum(
            wave_sd, sd_round_rect(xx, yy, cx, bub["cy"], bar_w / 2, h * s / 2, bar_w / 2)
        )
    wt = np.clip((xx - (bub["cx"] - total / 2)) / total, 0, 1)[..., None]
    wave_col = np.array([0.98, 0.45, 0.25]) * (1 - wt) + np.array([0.40, 0.28, 0.88]) * wt
    rgb, alpha = over(rgb, alpha, wave_col, coverage(wave_sd))

    out = np.dstack([rgb, alpha])
    return (np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("output", nargs="?", default=str(DEFAULT_OUT))
    ap.add_argument("--size", type=int, default=1024)
    args = ap.parse_args()
    out = Path(args.output)
    write_png(out, render(args.size))
    print(f"wrote {out} ({args.size}x{args.size})")


if __name__ == "__main__":
    main()
