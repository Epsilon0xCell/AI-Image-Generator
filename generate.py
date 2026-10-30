#!/usr/bin/env python3
"""Best AI Image Generator - prompt-seeded generative art, fully offline.

Turns any text prompt into a unique PNG image using procedural art
(plasma fields, wave interference and orbit traps) seeded by the prompt.
No API key, no network, no third-party libraries - just the Python
standard library and a hand-rolled PNG encoder.

Usage:
    python3 generate.py "a violet nebula over a dark ocean"
    python3 generate.py "geometric sunrise" --style waves --size 800
    python3 generate.py "circuit dreams" --style orbit -o dreams.png
"""
import argparse
import hashlib
import math
import random
import struct
import sys
import zlib

PALETTES = [
    [(10, 10, 26), (91, 33, 182), (167, 139, 250), (255, 255, 255)],   # violet nebula
    [(4, 20, 32), (0, 119, 182), (72, 202, 228), (255, 255, 255)],    # deep ocean
    [(26, 8, 8), (153, 27, 27), (249, 115, 22), (255, 237, 213)],     # ember
    [(6, 26, 16), (22, 101, 52), (74, 222, 128), (240, 253, 244)],    # matrix green
]


def lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def color_at(palette, t):
    t = min(max(t, 0.0), 0.9999) * (len(palette) - 1)
    i = int(t)
    return lerp(palette[i], palette[i + 1], t - i)


def plasma(x, y, w, h, rng_seeds):
    v = 0.0
    for sx, sy, freq, phase in rng_seeds:
        v += math.sin((x * sx + y * sy) / (w / freq) + phase)
    return (v / len(rng_seeds) + 1) / 2


def render(prompt, style, size):
    digest = hashlib.sha256(prompt.encode()).digest()
    rng = random.Random(int.from_bytes(digest[:8], "big"))
    palette = PALETTES[digest[8] % len(PALETTES)]
    seeds = [(rng.uniform(-1, 1), rng.uniform(-1, 1),
              rng.uniform(2, 9), rng.uniform(0, 6.28)) for _ in range(4)]
    cx, cy = rng.uniform(0.3, 0.7), rng.uniform(0.3, 0.7)
    rows = []
    for y in range(size):
        row = bytearray()
        for x in range(size):
            nx, ny = x / size, y / size
            if style == "plasma":
                t = plasma(x, y, size, size, seeds)
            elif style == "waves":
                t = (math.sin(nx * 12 + plasma(x, y, size, size, seeds) * 6)
                     + math.cos(ny * 9)) / 4 + 0.5
            else:  # orbit: radial falloff around a seeded centre
                d = math.hypot(nx - cx, ny - cy)
                t = abs(math.sin(d * 22 - plasma(x, y, size, size, seeds) * 4))
            row += bytes(color_at(palette, t))
        rows.append(b"\x00" + bytes(row))
    return b"".join(rows)


def png_bytes(prompt, style, size):
    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(render(prompt, style, size)))
            + chunk(b"IEND", b""))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate prompt-seeded art as a PNG (offline).")
    parser.add_argument("prompt", help="text prompt - the same prompt always makes the same image")
    parser.add_argument("--style", choices=["plasma", "waves", "orbit"], default="plasma")
    parser.add_argument("--size", type=int, default=512, help="image size in pixels (default 512)")
    parser.add_argument("-o", "--output", help="output file (default: derived from the prompt)")
    args = parser.parse_args(argv)
    if not 16 <= args.size <= 2048:
        print("error: size must be between 16 and 2048", file=sys.stderr)
        return 1
    output = args.output or (
        "image-" + hashlib.sha256(args.prompt.encode()).hexdigest()[:10] + ".png")
    with open(output, "wb") as fh:
        fh.write(png_bytes(args.prompt, args.style, args.size))
    print(f"Wrote {output} ({args.size}x{args.size}, style={args.style})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
