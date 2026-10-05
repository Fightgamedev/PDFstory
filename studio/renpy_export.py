from __future__ import annotations

import hashlib
import json
import re
import struct
import zlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


def _quote(value: object) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def _placeholder_png(path: Path, seed: str, width: int = 1280, height: int = 720) -> None:
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    first = (30 + digest[0] % 55, 12 + digest[1] % 34, 35 + digest[2] % 70)
    second = (20 + digest[3] % 35, 30 + digest[4] % 55, 75 + digest[5] % 95)

    raw = bytearray()
    for y in range(height):
        row = bytearray([0])
        vertical = y / max(1, height - 1)
        for x in range(width):
            horizontal = x / max(1, width - 1)
            t = min(1.0, max(0.0, vertical * 0.68 + horizontal * 0.32))
            for a, b in zip(first, second):
                row.append(round(a * (1.0 - t) + b * t))
        raw.extend(row)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(bytes(raw), level=6))
        + _png_chunk(b"IEND", b"")
    )


def _illustrated_scene(path: Path, seed: str, description: str, width: int = 1280, height: int = 720) -> None:
    """Paint an original atmospheric scene locally from its setting cues."""
    digest = hashlib.sha256((seed + description).encode("utf-8")).digest()
    palettes = [((17, 17, 58), (173, 42, 119), (34, 210, 219)), ((25, 22, 56), (204, 81, 86), (255, 185, 113)), ((11, 41, 66), (49, 143, 154), (247, 90, 158)), ((43, 17, 55), (147, 59, 143), (255, 173, 106))]
    top, horizon, glow = palettes[digest[0] % len(palettes)]
    image = Image.new("RGB", (width, height))
    base_draw = ImageDraw.Draw(image)
    for y in range(height):
        t = y / (height - 1)
        col = tuple(round(a * (1 - t) + b * t) for a, b in zip(top, horizon))
        base_draw.line((0, y, width, y), fill=col)
    # Soft light source and broad atmospheric glow.
    light = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ld = ImageDraw.Draw(light)
    cx, cy = int(width * (.22 + digest[1] / 255 * .56)), int(height * (.18 + digest[2] / 255 * .2))
    radius = 185 + digest[3] % 100
    ld.ellipse((cx-radius, cy-radius, cx+radius, cy+radius), fill=(*glow, 105))
    light = light.filter(ImageFilter.GaussianBlur(70))
    image = Image.alpha_composite(image.convert("RGBA"), light)
    d = ImageDraw.Draw(image, "RGBA")
    # Star / window lights.
    for i in range(45):
        x = digest[(i + 4) % 32] * 5
        y = digest[(i + 12) % 32] * 2
        r = 1 + (digest[(i + 20) % 32] % 3)
        d.ellipse((x-r, y-r, x+r, y+r), fill=(255, 231, 240, 150))
    setting = description.lower()
    if any(k in setting for k in ("garden", "forest", "tree", "hill", "shore", "sea", "river", "road", "hillside")):
        # Layered hills and a reflective path / water band.
        d.polygon([(0, 430), (190, 330), (390, 450), (610, 315), (880, 440), (1070, 340), (1280, 420), (1280, 720), (0, 720)], fill=(22, 28, 58, 235))
        d.polygon([(0, 510), (250, 425), (470, 535), (740, 415), (950, 515), (1130, 430), (1280, 490), (1280, 720), (0, 720)], fill=(13, 20, 43, 250))
        d.polygon([(570, 720), (700, 720), (655, 495), (625, 495)], fill=(*glow, 70))
        # Framing tree branches.
        for x, direction in ((45, 1), (1235, -1)):
            d.line((x, 720, x + 35*direction, 390), fill=(11, 15, 34, 255), width=36)
            for j in range(5):
                yy = 390 + j*32
                d.line((x+25*direction, yy, x+145*direction, yy-90), fill=(12, 17, 38, 245), width=12)
    else:
        # Architectural silhouette adapts to house / city / interior cues.
        d.rectangle((0, 470, width, height), fill=(12, 14, 35, 250))
        for i in range(11):
            bw = 70 + digest[(i+5)%32] % 100
            x = i * 126 - 20
            bh = 130 + digest[(i+11)%32] % 230
            d.rectangle((x, 480-bh, x+bw, 540), fill=(19, 21, 48, 235))
            for wy in range(500-bh, 520, 37):
                for wx in range(x+14, x+bw-8, 28):
                    if digest[(i+wx+wy) % 32] % 3:
                        d.rectangle((wx, wy, wx+7, wy+13), fill=(*glow, 180))
        d.polygon([(0, 720), (0, 565), (340, 530), (530, 590), (820, 520), (1280, 575), (1280, 720)], fill=(9, 12, 28, 245))
    # A small original traveler silhouette gives the composition scale.
    px = 800 + digest[7] % 200
    d.ellipse((px-24, 418, px+24, 466), fill=(18, 12, 31, 255), outline=(*glow, 170), width=2)
    d.polygon([(px-24, 461), (px+24, 461), (px+48, 590), (px+37, 610), (px+20, 535), (px+12, 720), (px-10, 720), (px-13, 540), (px-35, 617), (px-49, 600)], fill=(17, 12, 29, 255))
    d.line((px-25, 480, px-53, 555), fill=(17, 12, 29, 255), width=13)
    d.line((px+25, 480, px+54, 550), fill=(17, 12, 29, 255), width=13)
    # Soft vignette and subtle colored frame glows.
    vignette = Image.new("L", (width, height), 0)
    vd = ImageDraw.Draw(vignette)
    vd.ellipse((-width*.2, -height*.3, width*1.2, height*1.2), fill=210)
    vignette = vignette.filter(ImageFilter.GaussianBlur(100))
    shade = Image.new("RGBA", (width, height), (5, 4, 19, 125))
    shade.putalpha(Image.eval(vignette, lambda a: 125 - int(a * .48)))
    image = Image.alpha_composite(image, shade)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(path, "PNG", optimize=True)


def _safe_name(text: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9_]+", "_", text.strip().lower()).strip("_")
    return name or "story"


def export_game(story: dict, destination: Path) -> Path:
    game_dir = destination / "game"
    image_dir = game_dir / "images"
    image_dir.mkdir(parents=True, exist_ok=True)

    title = str(story.get("title") or "Untitled Story").strip() or "Untitled Story"
    scenes = story.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        raise ValueError("The screenplay needs at least one scene before it can be exported.")

    speakers: dict[str, str] = {}
    for scene in scenes:
        for line in scene.get("dialogue", []):
            speaker = str(line.get("speaker", "Narrator")).strip() or "Narrator"
            if speaker.casefold() != "narrator":
                speakers.setdefault(speaker, f"speaker_{len(speakers) + 1}")

    script: list[str] = [
        "# Generated by PDF Story Studio. Edit this file to customize your game.",
        "define config.name = " + _quote(title),
        "define config.version = \"0.1\"",
        "define config.screen_width = 1280",
        "define config.screen_height = 720",
        "define config.save_directory = " + _quote("pdf_story_" + _safe_name(title)),
        "",
        "transform gentle_drift:",
        "    subpixel True",
        "    zoom 1.0",
        "    xalign 0.5",
        "    yalign 0.5",
        "    linear 12.0 zoom 1.045 xalign 0.53",
        "    linear 12.0 zoom 1.0 xalign 0.47",
        "    repeat",
        "",
    ]

    for name, variable in speakers.items():
        script.append(f"define {variable} = Character({_quote(name)})")
    if speakers:
        script.append("")

    labels: list[str] = []
    for index, scene in enumerate(scenes, start=1):
        label = f"scene_{index}"
        labels.append(label)
        script.append(f"image bg {label} = \"images/{label}.png\"")
        description = str(scene.get("visual_description") or scene.get("location") or "")
        _illustrated_scene(image_dir / f"{label}.png", f"{title}:{scene.get('title', label)}", description)
    script.extend(["", "label start:"])

    first_scene_name = str(scenes[0].get("title") or "Opening")
    script.extend(
        [
            f"    scene bg {labels[0]} at gentle_drift",
            "    with fade",
            f"    {_quote(title)}",
            f"    jump {labels[0]}",
            "",
        ]
    )

    for index, scene in enumerate(scenes):
        label = labels[index]
        scene_title = str(scene.get("title") or f"Scene {index + 1}")
        pages = scene.get("source_pages", [])
        if isinstance(pages, list) and len(pages) >= 2:
            script.append(f"# Adapted from source pages {pages[0]}-{pages[1]}.")
        script.extend(
            [
                f"label {label}:",
                f"    scene bg {label} at gentle_drift",
                "    with dissolve",
                f"    centered {_quote(scene_title)}",
            ]
        )

        dialogue = scene.get("dialogue", [])
        if not isinstance(dialogue, list) or not dialogue:
            dialogue = [{"speaker": "Narrator", "text": scene.get("visual_description") or scene_title}]
        for line in dialogue:
            speaker = str(line.get("speaker", "Narrator")).strip() or "Narrator"
            text = str(line.get("text", "")).strip()
            if not text:
                continue
            if speaker.casefold() == "narrator":
                script.append(f"    narrator {_quote(text)}")
            else:
                variable = speakers[speaker]
                script.append(f"    {variable} {_quote(text)}")

        if index + 1 < len(scenes):
            script.append(f"    jump {labels[index + 1]}")
        else:
            script.append("    return")
        script.append("")

    (game_dir / "script.rpy").write_text("\n".join(script), encoding="utf-8")
    (game_dir / "options.rpy").write_text(
        "# Project settings for the generated Ren'Py game.\n"
        f"define config.window_title = {_quote(title)}\n"
        "define config.rollback_enabled = True\n",
        encoding="utf-8",
    )
    (destination / "story.json").write_text(json.dumps(story, ensure_ascii=False, indent=2), encoding="utf-8")
    (destination / "README.txt").write_text(
        f"{title}\n\n"
        "This is an editable Ren'Py project generated by PDF Story Studio.\n"
        "Scene images are locally composed original illustrations. Replace the\n"
        "PNGs under game/images with your own artwork, keeping their names.\n\n"
        "To preview, set RENPY_SDK to a Ren'Py SDK folder and run ./play.sh.\n",
        encoding="utf-8",
    )
    launcher = destination / "play.sh"
    launcher.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        "HERE=$(CDPATH= cd -- \"$(dirname -- \"$0\")\" && pwd)\n"
        "SDK=${RENPY_SDK:-}\n"
        "if [ -z \"$SDK\" ] || [ ! -x \"$SDK/renpy.sh\" ]; then\n"
        "    printf '%s\\n' 'Set RENPY_SDK to your Ren\x27Py SDK folder first.' >&2\n"
        "    exit 1\n"
        "fi\n"
        "exec \"$SDK/renpy.sh\" \"$HERE\" run\n",
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    return destination
