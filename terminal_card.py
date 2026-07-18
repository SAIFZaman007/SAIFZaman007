#!/usr/bin/env python3
"""
generate_terminal_card.py
==========================
"""

from __future__ import annotations

import argparse
import html
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

from PIL import Image, ImageOps, ImageFilter

# ---------------------------------------------------------------------------
# ASCII ramp -- sparse -> dense, 10 luminance levels.
# ---------------------------------------------------------------------------

RAMP: str = " .:-=+*#%@"

@dataclass(frozen=True)
class Theme:
    key: str
    bg: str
    panel: str
    border: str
    text: str
    dim: str
    prompt: str
    accent: str


DARK = Theme("dark", bg="#0d1117", panel="#161b22", border="#30363d",
             text="#c9d1d9", dim="#6e7681", prompt="#3fb950", accent="#00f7ff")
LIGHT = Theme("light", bg="#ffffff", panel="#f6f8fa", border="#d0d7de",
              text="#24292f", dim="#57606a", prompt="#1a7f37", accent="#0969da")


# ---------------------------------------------------------------------------
# Image -> ASCII
# ---------------------------------------------------------------------------
def load_portrait(path: Path, top: float, bottom: float, crop_ratio: float) -> Image.Image:
    """Crop to a head-and-shoulders frame.

    `top`/`bottom` are fractions (0-1) of the source image's height that
    bound the crop vertically -- e.g. top=0.02, bottom=0.53 keeps
    roughly the top half, which is what a headshot needs (a full-body
    photo has too much background/torso for a small ASCII grid to
    render as anything but noise). The result is then centred
    horizontally to `crop_ratio` (width / height).
    """
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    w, h = img.size

    y0, y1 = int(h * top), int(h * bottom)
    kept_h = y1 - y0
    target_w = int(kept_h * crop_ratio)
    if target_w > w:
        target_w = w
        kept_h = int(w / crop_ratio)
        y1 = y0 + kept_h

    x0 = (w - target_w) // 2
    return img.crop((x0, y0, x0 + target_w, y1))


def image_to_levels(img: Image.Image, columns: int, char_aspect: float) -> List[List[int]]:

    gray = ImageOps.autocontrast(img.convert("L"), cutoff=2)
    gray = gray.filter(ImageFilter.UnsharpMask(radius=2, percent=100, threshold=2))
    w, h = gray.size
    rows = max(1, round(h * (columns / w) * char_aspect))
    gray = gray.resize((columns, rows), Image.LANCZOS)

    levels = len(RAMP)
    pixels = gray.tobytes()  # mode "L" -> exactly one byte per pixel
    grid: List[List[int]] = []
    for r in range(rows):
        row_px = pixels[r * columns:(r + 1) * columns]
        grid.append([min(levels - 1, p * levels // 256) for p in row_px])
    return grid


def rows_for_theme(grid: List[List[int]], theme: Theme) -> List[str]:

    ramp = RAMP if theme.key == "dark" else RAMP[::-1]
    return ["".join(ramp[v] for v in row) for row in grid]


# ---------------------------------------------------------------------------
# SVG assembly
# ---------------------------------------------------------------------------
def esc(s: str) -> str:
    return html.escape(s, quote=False)


# Right-column row heights, in SVG units, keyed by row type.
ROW_H = {"cmd": 26, "output": 30, "divider": 22, "kv": 23, "prompt": 26}


def _layout_right_rows(rows: List[Tuple], start_y: float) -> List[Tuple[str, Tuple, float]]:
    """Assign a baseline y to every right-column row; return (kind, data, y)."""
    laid_out = []
    y = start_y
    for row in rows:
        kind = row[0]
        if kind == "space":
            y += row[1]
            continue
        y += ROW_H[kind]
        laid_out.append((kind, row[1:], y))
    return laid_out


def _right_rows_height(rows: List[Tuple]) -> float:
    h = 0.0
    for row in rows:
        h += row[1] if row[0] == "space" else ROW_H[row[0]]
    return h


def build_svg(
    dark_rows: List[str],
    light_rows: List[str],
    *,
    host: str,
    command: str,
    identity: str,
    kv_pairs: List[Tuple[str, str]],
    char_w: float = 7.4,
    char_h: float = 14.6,
    font_size: float = 12.0,
) -> str:
    columns = len(dark_rows[0])
    rows = len(dark_rows)

    pad = 30
    titlebar_h = 40
    frame_pad = 12
    gap = 40
    right_w = 470.0

    art_w = columns * char_w
    art_h = rows * char_h
    frame_w = art_w + frame_pad * 2
    frame_h = art_h + frame_pad * 2

    content_top = titlebar_h + pad
    left_x = pad
    frame_y = content_top
    art_x = left_x + frame_pad
    art_y = frame_y + frame_pad

    right_x = left_x + frame_w + gap

    right_rows: List[Tuple] = [
        ("cmd",),
        ("space", 6),
        ("output",),
        ("space", 14),
        ("divider",),
        ("space", 10),
    ]
    for label, value in kv_pairs:
        right_rows.append(("kv", label, value))
    right_rows += [("space", 16), ("prompt",)]

    laid_out = _layout_right_rows(right_rows, content_top - ROW_H["cmd"] * 0.28)
    right_h = _right_rows_height(right_rows)

    content_h = max(frame_h, right_h)
    width = right_x + right_w + pad
    height = content_top + content_h + pad

    # ---- ascii art block ----
    def ascii_block(rows_text: List[str], cls: str) -> str:
        parts = []
        for i, row in enumerate(rows_text):
            y = art_y + i * char_h + char_h * 0.82
            parts.append(
                f'<text x="{art_x:.1f}" y="{y:.1f}" textLength="{art_w:.1f}" '
                f'lengthAdjust="spacingAndGlyphs" class="{cls}">{esc(row)}</text>'
            )
        return "\n      ".join(parts)

    dark_block = ascii_block(dark_rows, "ascii ascii-dark")
    light_block = ascii_block(light_rows, "ascii ascii-light")

    # ---- right column ----
    cmd_full = f"{host} {command}"
    cmd_len = max(len(cmd_full), 1)
    char_adv = font_size * 0.6

    right_svg_parts = []
    for kind, data, y in laid_out:
        if kind == "cmd":
            right_svg_parts.append(f'''
  <g class="line-cmd">
    <text class="host" x="{right_x:.1f}" y="{y:.1f}">{esc(host)}</text>
    <text class="cmd" x="{right_x + len(host) * char_adv:.1f}" y="{y:.1f}"> {esc(command)}</text>
  </g>''')
        elif kind == "output":
            right_svg_parts.append(
                f'<g class="line-out"><text class="out" x="{right_x:.1f}" y="{y:.1f}">&gt; {esc(identity)}</text></g>'
            )
        elif kind == "divider":
            right_svg_parts.append(
                f'<line class="divider info-block" x1="{right_x:.1f}" y1="{y - 7:.1f}" '
                f'x2="{right_x + right_w:.1f}" y2="{y - 7:.1f}"/>'
            )
        elif kind == "kv":
            label, value = data
            right_svg_parts.append(f'''
  <text class="kv-label info-block" x="{right_x:.1f}" y="{y:.1f}">{esc(label)}</text>
  <text class="kv-value info-block" x="{right_x + 92:.1f}" y="{y:.1f}">{esc(value)}</text>''')
        elif kind == "prompt":
            right_svg_parts.append(f'''
  <g class="line-close">
    <text class="host" x="{right_x:.1f}" y="{y:.1f}">{esc(host)}</text>
    <rect class="cursor" x="{right_x + len(host) * char_adv + 8:.1f}" y="{y - 11:.1f}" width="8" height="14"/>
  </g>''')

    right_svg = "\n  ".join(right_svg_parts)

    svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg viewBox="0 0 {width:.0f} {height:.0f}" xmlns="http://www.w3.org/2000/svg"
     role="img" aria-label="Animated terminal card: {esc(command)} returns {esc(identity)}">
  <title>{esc(host)} {esc(command)}</title>
  <style>
    <![CDATA[
      svg {{
        --bg: {DARK.bg}; --panel: {DARK.panel}; --border: {DARK.border};
        --text: {DARK.text}; --dim: {DARK.dim}; --prompt: {DARK.prompt}; --accent: {DARK.accent};
      }}
      @media (prefers-color-scheme: light) {{
        svg {{
          --bg: {LIGHT.bg}; --panel: {LIGHT.panel}; --border: {LIGHT.border};
          --text: {LIGHT.text}; --dim: {LIGHT.dim}; --prompt: {LIGHT.prompt}; --accent: {LIGHT.accent};
        }}
      }}

      .card-bg  {{ fill: var(--bg); stroke: var(--border); }}
      .chrome   {{ fill: var(--panel); }}
      .hairline {{ stroke: var(--border); stroke-width: 1; }}
      .tab      {{ fill: var(--dim); font: 12px ui-monospace, 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace; }}
      .frame    {{ fill: none; stroke: var(--border); stroke-width: 1; }}
      .divider  {{ stroke: var(--border); stroke-width: 1; }}

      text {{
        font-family: ui-monospace, 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, 'Courier New', monospace;
        white-space: pre;
      }}

      .ascii       {{ font-size: {font_size:.0f}px; fill: var(--text); }}
      .ascii-dark  {{ display: block; }}
      .ascii-light {{ display: none; }}
      @media (prefers-color-scheme: light) {{
        .ascii-dark  {{ display: none; }}
        .ascii-light {{ display: block; }}
      }}

      .host     {{ fill: var(--dim); font-size: 14px; }}
      .cmd      {{ fill: var(--accent); font-size: 14px; }}
      .out      {{ fill: var(--prompt); font-size: 18px; font-weight: 600; }}
      .kv-label {{ fill: var(--dim); font-size: 13px; }}
      .kv-value {{ fill: var(--text); font-size: 13px; }}
      .cursor   {{ fill: var(--accent); }}

      /* ---- animation: a single reveal pass on load, nothing loops
             except the cursor -- see frontend-design note on restraint ---- */
      .line-cmd {{
        clip-path: inset(0 100% 0 0);
        animation: reveal-cmd 1.0s steps({cmd_len}, end) 0.3s 1 forwards;
      }}
      .art-group  {{ opacity: 0; animation: fade-in 1.0s ease-out 0.15s 1 forwards; }}
      .line-out   {{ opacity: 0; animation: fade-in 0.4s ease-out 1.5s 1 forwards; }}
      .info-block {{ opacity: 0; animation: fade-in 0.6s ease-out 2.0s 1 forwards; }}
      .line-close {{ opacity: 0; animation: fade-in 0.4s ease-out 2.7s 1 forwards; }}
      .cursor     {{ animation: blink 1s steps(1, end) 2.9s infinite; }}

      @keyframes reveal-cmd {{ to {{ clip-path: inset(0 0 0 0); }} }}
      @keyframes fade-in    {{ to {{ opacity: 1; }} }}
      @keyframes blink      {{ 0%, 49% {{ opacity: 1; }} 50%, 100% {{ opacity: 0; }} }}

      @media (prefers-reduced-motion: reduce) {{
        .line-cmd, .art-group, .line-out, .info-block, .line-close {{
          animation: none !important; opacity: 1 !important; clip-path: inset(0 0 0 0) !important;
        }}
        .cursor {{ animation: none !important; opacity: 1 !important; }}
      }}
    ]]>
  </style>

  <rect class="card-bg" x="0.5" y="0.5" width="{width - 1:.0f}" height="{height - 1:.0f}" rx="10"/>
  <path class="chrome" d="M0.5,10.5 a9.5,9.5 0 0 1 9.5,-10 h{width - 20:.0f} a9.5,9.5 0 0 1 9.5,10 v{titlebar_h - 10:.0f} h-{width - 1:.0f} z"/>
  <line class="hairline" x1="0" y1="{titlebar_h:.0f}" x2="{width:.0f}" y2="{titlebar_h:.0f}"/>
  <circle cx="22" cy="{titlebar_h / 2:.0f}" r="6" fill="#ff5f56"/>
  <circle cx="42" cy="{titlebar_h / 2:.0f}" r="6" fill="#ffbd2e"/>
  <circle cx="62" cy="{titlebar_h / 2:.0f}" r="6" fill="#27c93f"/>
  <text class="tab" x="{width / 2:.0f}" y="{titlebar_h / 2 + 4:.0f}" text-anchor="middle">{esc(host)}</text>

  <rect class="frame" x="{left_x:.1f}" y="{frame_y:.1f}" width="{frame_w:.1f}" height="{frame_h:.1f}" rx="6"/>
  <g class="art-group">
      {dark_block}
      {light_block}
  </g>

  {right_svg}
</svg>'''
    return svg


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--columns", type=int, default=46, help="ASCII grid width in characters")
    p.add_argument("--crop-top", type=float, default=0.02, help="top edge of crop, as a fraction of photo height")
    p.add_argument("--crop-bottom", type=float, default=0.53, help="bottom edge of crop, as a fraction of photo height")
    p.add_argument("--crop-ratio", type=float, default=0.92, help="crop width/height ratio")
    p.add_argument("--char-aspect", type=float, default=0.52)
    p.add_argument("--host", default="saif@maktech:~$")
    p.add_argument("--command", default="whoami")
    p.add_argument("--identity", default="Saif")
    args = p.parse_args()

    kv_pairs = [
        ("role", "AI-SaaS Team Lead @ Maktech"),
        ("focus", "Security \u00b7 ML \u00b7 Full-Stack"),
        ("based", "Dhaka, Bangladesh"),
        ("uptime", "shipping since 2025"),
        ("reach", "open to freelance & collab"),
    ]

    img = load_portrait(args.input, args.crop_top, args.crop_bottom, args.crop_ratio)
    grid = image_to_levels(img, args.columns, args.char_aspect)
    dark_rows = rows_for_theme(grid, DARK)
    light_rows = rows_for_theme(grid, LIGHT)

    svg = build_svg(
        dark_rows, light_rows,
        host=args.host, command=args.command, identity=args.identity,
        kv_pairs=kv_pairs,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(svg, encoding="utf-8")
    print(f"wrote {args.output}  ({args.columns}x{len(dark_rows)} grid, {len(svg):,} bytes)")

if __name__ == "__main__":
    main()