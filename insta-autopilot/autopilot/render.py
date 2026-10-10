from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .media import run_ffmpeg

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\segoeuib.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/google-fonts/Poppins-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def find_font(font_path: str = "", size: int = 88) -> ImageFont.FreeTypeFont:
    for p in ([font_path] if font_path else []) + FONT_CANDIDATES:
        if p and Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size)


def render_caption_png(text: str, out: Path, font: ImageFont.FreeTypeFont,
                       max_width: int = 940, stroke: int = 7) -> None:
    """Transparent PNG with bold white caption text and a dark outline."""
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if font.getlength(trial) <= max_width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)

    line_h = int(font.size * 1.18)
    width = int(max(font.getlength(l) for l in lines)) + stroke * 4
    height = line_h * len(lines) + stroke * 4
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        x = (width - font.getlength(line)) / 2
        draw.text((x, stroke * 2 + i * line_h), line, font=font, fill="white",
                  stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
    img.save(out)


def render_scene(footage: Path | None, audio: Path, duration: float,
                 captions: list[tuple[str, float, float]], workdir: Path, idx: int,
                 cfg: dict) -> Path:
    """One scene: cropped stock clip (or plain colour), caption overlays, voice."""
    v = cfg["video"]
    W, H, fps = v["width"], v["height"], v["fps"]
    font = find_font(v.get("font_path", ""))

    png_paths = []
    for j, (text, _s, _e) in enumerate(captions):
        p = workdir / f"cap_{idx:02d}_{j:02d}.png"
        render_caption_png(text, p, font)
        png_paths.append(p)

    args: list[str] = []
    if footage:
        args += ["-stream_loop", "-1", "-i", str(footage)]
    else:
        args += ["-f", "lavfi", "-i",
                 f"color=c={v['background_color']}:s={W}x{H}:r={fps}"]
    args += ["-i", str(audio)]
    for p in png_paths:
        args += ["-i", str(p)]

    chain = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
             f"crop={W}:{H},setsar=1,fps={fps},eq=brightness=-0.10:saturation=1.05[v0]")
    y = int(H * 0.60)
    last = "v0"
    parts = [chain]
    for j, (_t, s, e) in enumerate(captions):
        nxt = f"v{j + 1}"
        parts.append(
            f"[{last}][{2 + j}:v]overlay=x=(W-w)/2:y={y}-h/2:"
            f"enable='between(t,{s:.3f},{e:.3f})'[{nxt}]")
        last = nxt

    out = workdir / f"scene_{idx:02d}.mp4"
    args += [
        "-filter_complex", ";".join(parts),
        "-map", f"[{last}]", "-map", "1:a",
        "-af", "apad", "-t", f"{duration:.3f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-r", str(fps), "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2",
        "-movflags", "+faststart", str(out),
    ]
    run_ffmpeg(args)
    return out


def concat_scenes(scene_files: list[Path], out: Path) -> Path:
    listing = out.parent / "concat.txt"
    with open(listing, "w", encoding="utf-8") as f:
        for p in scene_files:
            f.write("file '{}'\n".format(str(p.resolve()).replace("\\", "/").replace("'", r"'\''")))
    run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(listing),
                "-c", "copy", "-movflags", "+faststart", str(out)])
    return out
