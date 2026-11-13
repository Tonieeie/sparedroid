"""Render the README images from demo.html.

    pip install playwright pillow && playwright install chromium
    python docs/media-src/render.py                 # everything
    python docs/media-src/render.py --preview ai 5000   # one PNG frame, for tweaking

Outputs into docs/media/: hero.png, demo-ai.gif, demo-order.gif, demo-any.gif.
Frames are rendered by calling render(ms) in the page, so timing is exact and
repeatable. Identical consecutive frames are merged (longer duration) to keep GIFs small.
"""

from __future__ import annotations

import argparse
import io
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "media"
URL = (HERE / "demo.html").as_uri()


def frames(page, scene: str, fps: int, end_hold_ms: int):
    page.goto(f"{URL}?scene={scene}")
    page.wait_for_function("typeof render === 'function'")
    dur = page.evaluate(f"SCENES[{scene!r}].dur")
    step = 1000 / fps
    t = 0.0
    while t <= dur:
        page.evaluate(f"render({t})")
        yield page.screenshot(type="png"), step
        t += step
    yield page.screenshot(type="png"), end_hold_ms


def make_gif(page, scene: str, *, fps: int = 15, scale: float = 0.75, end_hold_ms: int = 1500) -> Path:
    from PIL import Image

    imgs: list[Image.Image] = []
    durs: list[float] = []
    last = None
    for png, ms in frames(page, scene, fps, end_hold_ms):
        if png == last:
            durs[-1] += ms
            continue
        last = png
        im = Image.open(io.BytesIO(png)).convert("RGB")
        if scale != 1:
            im = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
        imgs.append(im)
        durs.append(ms)
    # One shared palette (no colour flicker between frames), built from ~16 frames spread
    # over the whole scene so every bubble, avatar and emoji gets palette entries.
    picks = imgs[:: max(1, len(imgs) // 16)]
    w, h = imgs[0].width // 2, imgs[0].height // 2
    sample = Image.new("RGB", (w * 4, h * ((len(picks) + 3) // 4)))
    for i, im in enumerate(picks):
        sample.paste(im.resize((w, h)), ((i % 4) * w, (i // 4) * h))
    palette = sample.quantize(colors=256, method=Image.Quantize.FASTOCTREE)
    pal = [im.quantize(palette=palette, dither=Image.Dither.NONE) for im in imgs]
    out = OUT / f"demo-{scene}.gif"
    pal[0].save(out, save_all=True, append_images=pal[1:], duration=[round(d) for d in durs],
                loop=0, optimize=True, disposal=1)
    print(f"{out.name}: {len(pal)} frames, {out.stat().st_size / 1024:.0f} KB")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", nargs=2, metavar=("SCENE", "MS"))
    a = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    with sync_playwright() as p:
        # PLAYWRIGHT_CHROMIUM=<path to chrome.exe> to reuse a browser you already have
        exe = os.environ.get("PLAYWRIGHT_CHROMIUM")
        browser = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 720}, device_scale_factor=1)
        if a.preview:
            scene, ms = a.preview
            page.goto(f"{URL}?scene={scene}")
            page.wait_for_function("typeof render === 'function'")
            page.evaluate(f"render({int(ms)})")
            out = OUT / f"preview-{scene}-{ms}.png"
            page.screenshot(path=str(out))
            print(out)
            return 0
        hero = browser.new_page(viewport={"width": 1280, "height": 640}, device_scale_factor=2)
        hero.goto(f"{URL}?scene=hero")
        hero.wait_for_function("typeof render === 'function'")
        hero.screenshot(path=str(OUT / "hero.png"))
        print("hero.png")
        for scene in ("ai", "order", "any"):
            make_gif(page, scene)
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
