#!/usr/bin/env python3
"""Generate desktop assets, preferring a locally staged user-provided PNG."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


def icon(size: int = 1024) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((24, 24, size - 24, size - 24), radius=218, fill=255)
    for y in range(size):
        for x in range(size):
            if mask.getpixel((x, y)):
                glow = max(0, 1 - (((x - 745) ** 2 + (y - 210) ** 2) ** 0.5) / 930)
                image.putpixel(
                    (x, y), (int(8 + 6 * glow), int(16 + 25 * glow), int(32 + 51 * glow), 255)
                )
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (27, 27, size - 27, size - 27), radius=216, outline=(48, 78, 123), width=3
    )
    for coordinate in (294, 438, 582, 726):
        draw.line([(coordinate, 240), (coordinate, 784)], fill=(24, 43, 69), width=3)
        draw.line([(240, coordinate), (784, coordinate)], fill=(24, 43, 69), width=3)
    # Two directional paths form an abstract G/H with opposing positions.
    draw.line(
        [(242, 672), (401, 513), (521, 632), (758, 393)], fill=(7, 29, 63), width=85, joint="curve"
    )
    draw.line(
        [(242, 672), (401, 513), (521, 632), (758, 393)],
        fill=(62, 139, 253),
        width=52,
        joint="curve",
    )
    draw.polygon([(688, 350), (802, 350), (802, 464)], fill=(91, 173, 255))
    draw.line([(260, 365), (429, 365), (595, 530)], fill=(156, 215, 255), width=42, joint="curve")
    draw.polygon([(224, 322), (224, 406), (301, 365)], fill=(156, 215, 255))
    draw.ellipse((375, 487, 427, 539), fill=(189, 229, 255))
    return image


def source_icon(root: Path) -> Image.Image:
    supplied = root / "desktop" / "assets" / "bot-icon-source.png"
    if not supplied.is_file():
        return icon()
    with Image.open(supplied) as opened:
        opened.load()
        if min(opened.size) < 512:
            raise ValueError(f"User icon is too small: {opened.size[0]}x{opened.size[1]}")
        return ImageOps.fit(
            opened.convert("RGBA"),
            (1024, 1024),
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        )


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    # Pillow bundles this font, so DMG text is independent of installed OS fonts.
    return ImageFont.load_default(size=size)


def generate(root: Path) -> None:
    icons = root / "desktop" / "icons"
    assets = root / "desktop" / "assets"
    icons.mkdir(parents=True, exist_ok=True)
    assets.mkdir(parents=True, exist_ok=True)
    source = source_icon(root)
    source.save(icons / "icon.png")
    source.save(icons / "icon.icns", format="ICNS")
    source.save(icons / "icon.ico", format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (256, 256)])
    for size, name in ((32, "32x32.png"), (128, "128x128.png"), (256, "128x128@2x.png")):
        source.resize((size, size), Image.Resampling.LANCZOS).save(icons / name)
    background = Image.new("RGB", (660, 420), (10, 16, 29))
    draw = ImageDraw.Draw(background)
    draw.text((330, 59), "GRID HEDGE BOT", font=font(29), fill=(235, 244, 255), anchor="mm")
    draw.text(
        (330, 100),
        "Trascina l'app in Applicazioni",
        font=font(16),
        fill=(154, 177, 206),
        anchor="mm",
    )
    draw.line([(300, 205), (354, 205)], fill=(83, 152, 250), width=5)
    draw.polygon([(350, 192), (368, 205), (350, 218)], fill=(83, 152, 250))
    draw.text(
        (330, 351),
        "DEMO / LIVE  ·  Stato protetto  ·  Credenziali Keychain",
        font=font(13),
        fill=(109, 134, 166),
        anchor="mm",
    )
    background.save(assets / "dmg-background.png")
    (icons / "icon.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024">'
        '<defs><linearGradient id="b" x2="1" y2="1"><stop stop-color="#183553"/>'
        '<stop offset="1" stop-color="#080f20"/></linearGradient></defs>'
        '<rect x="24" y="24" width="976" height="976" rx="218" fill="url(#b)" stroke="#304e7b" stroke-width="3"/>'
        '<path d="M242 672 401 513 521 632 758 393" fill="none" stroke="#3e8bfd" stroke-width="52"/>'
        '<path d="M688 350H802V464Z" fill="#5badff"/>'
        '<path d="M260 365H429L595 530" fill="none" stroke="#9cd7ff" stroke-width="42"/>'
        '<path d="M224 322V406L301 365Z" fill="#9cd7ff"/>'
        '<circle cx="401" cy="513" r="26" fill="#bde5ff"/></svg>\n',
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    arguments = parser.parse_args()
    generate(arguments.root)
    print("Desktop assets generated: source PNG, ICNS, ICO, sizes and DMG background")


if __name__ == "__main__":
    main()
