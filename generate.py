#!/usr/bin/env python3
"""AI Image Generator - prompt-seeded generative art, fully offline.

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

# I order each palette from its darkest stop to white. color_at walks the
# list in order as t rises, so if I put a light color in the middle, the
# image would flash bright and then go dark again instead of building up.
PALETTES = [
    [(10, 10, 26), (91, 33, 182), (167, 139, 250), (255, 255, 255)],   # violet nebula
    [(4, 20, 32), (0, 119, 182), (72, 202, 228), (255, 255, 255)],    # deep ocean
    [(26, 8, 8), (153, 27, 27), (249, 115, 22), (255, 237, 213)],     # ember
    [(6, 26, 16), (22, 101, 52), (74, 222, 128), (240, 253, 244)],    # matrix green
]


def lerp(a, b, t):
    # I round here, at the blend, so callers always get plain ints that
    # bytes() will accept. If I left floats in, the failure would show up
    # later inside render, far from the line that caused it.
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def color_at(palette, t):
    # I clamp t to 0.9999 instead of 1.0 on purpose. At exactly 1.0 the
    # index i would land on the last stop, and palette[i + 1] would run
    # past the end of the list. This way the top segment still blends
    # toward white but never reaches for a stop that does not exist.
    t = min(max(t, 0.0), 0.9999) * (len(palette) - 1)
    i = int(t)
    return lerp(palette[i], palette[i + 1], t - i)


def plasma(x, y, w, h, rng_seeds):
    v = 0.0
    for sx, sy, freq, phase in rng_seeds:
        v += math.sin((x * sx + y * sy) / (w / freq) + phase)
    # Each sine stays between -1 and 1, so the average does too. I shift
    # and halve that average to land in 0 to 1, which is the range
    # color_at and the style formulas below all expect from me.
    return (v / len(rng_seeds) + 1) / 2


def render(prompt, style, size):
    # The prompt hash is the whole identity of the image. I seed the RNG
    # from digest bytes 0 to 7, and I let byte 8 pick the palette on its
    # own, so the palette choice does not depend on how many numbers the
    # RNG happened to draw first. I keep those two uses separate. If I
    # merged them, I would change every existing prompt's image.
    digest = hashlib.sha256(prompt.encode()).digest()
    rng = random.Random(int.from_bytes(digest[:8], "big"))
    palette = PALETTES[digest[8] % len(PALETTES)]
    # I draw the four field seeds and the orbit center in this fixed order
    # for every style, even though plasma and waves never use the center.
    # If I drew values only when a style needed them, the same prompt
    # would build a different field when I switched styles, and comparing
    # styles for one prompt would stop meaning anything.
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
                # I feed the plasma value back into the sine so the wave
                # fronts bend instead of running straight. The plain sine
                # and cosine sum lands between -2 and 2, so I divide by 4
                # and add 0.5 to bring it back into the 0 to 1 range.
                t = (math.sin(nx * 12 + plasma(x, y, size, size, seeds) * 6)
                     + math.cos(ny * 9)) / 4 + 0.5
            else:  # orbit: radial falloff around a seeded centre
                # I take the absolute value of the sine on purpose. It
                # folds each wave back on itself, so the falloff reads as
                # tight rings around the center instead of soft bands.
                d = math.hypot(nx - cx, ny - cy)
                t = abs(math.sin(d * 22 - plasma(x, y, size, size, seeds) * 4))
            row += bytes(color_at(palette, t))
        # PNG scanlines start with a filter-type byte; 0 means "no filter",
        # which keeps the encoder honest and the decoder trivial. I add
        # that byte here, per row, because png_bytes treats the whole
        # block as already formed scanlines and adds none of its own.
        rows.append(b"\x00" + bytes(row))
    return b"".join(rows)


def png_bytes(prompt, style, size):
    def chunk(kind, data):
        # I compute the CRC over kind plus data, the way the PNG format
        # defines it. If I ran it over data alone, strict decoders would
        # reject the file even though the pixel bytes are fine.
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    # I write the header fields in format order: width, height, bit depth
    # 8, color type 2 for truecolor RGB, then compression, filter, and
    # interlace all at 0, the only values this encoder actually produces.
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
    # I cap the size before any work starts. render walks every pixel in
    # pure Python, so cost grows with the square of the size, and a typo
    # like 20000 would otherwise run for a very long time before failing.
    if not 16 <= args.size <= 2048:
        print("error: size must be between 16 and 2048", file=sys.stderr)
        return 1
    # I name the default file from the prompt hash, not from the prompt
    # text. Prompt text can hold spaces and characters a file name cannot,
    # and the hash name means the same prompt overwrites its own old file
    # instead of piling up near duplicates.
    output = args.output or (
        "image-" + hashlib.sha256(args.prompt.encode()).hexdigest()[:10] + ".png")
    with open(output, "wb") as fh:
        fh.write(png_bytes(args.prompt, args.style, args.size))
    print(f"Wrote {output} ({args.size}x{args.size}, style={args.style})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
