"""Make the small test assets of each new kind, and their thumbnails, so an app can check its loaders:

    image/equirect_test_grid.png     a 360 x 180 degree panorama grid, labelled FRONT / RIGHT / BACK / LEFT / UP / DOWN
    video/test_pattern_720p.mp4      8 s, 1280x720, H.264 + AAC, faststart
    video/equirect_test_360.mp4      6 s, 2048x1024 equirectangular, H.264 + AAC, faststart
    virus/crambin_icosahedral_demo.json   60 copies of crambin on an icosahedral shell (an instance-list example)
    thumbs/...                       one JPG for each, and for the molecules

    python3 tools/make_test_assets.py
Needs numpy, Pillow and ffmpeg (with libx264).
"""

from __future__ import annotations

import itertools
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).parent))
from molecule_to_glb import COLORS, RADII, read_atoms  # noqa: E402

THUMB = (480, 360)


def font(size: int):
    for name in ("Arial Bold.ttf", "DejaVuSans-Bold.ttf", "Helvetica.ttc"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def equirect_grid(path: Path, width: int = 4096) -> None:
    """Lines every 15 degrees, heavier every 90; the image centre is straight ahead (FRONT)."""
    height = width // 2
    im = Image.new("RGB", (width, height), (24, 32, 48))
    d = ImageDraw.Draw(im)
    for lon in range(0, 361, 15):
        x = round(lon / 360 * (width - 1))
        d.line([(x, 0), (x, height)], fill=(200, 200, 220) if lon % 90 == 0 else (90, 100, 130), width=6 if lon % 90 == 0 else 2)
    for lat in range(-90, 91, 15):
        y = round((90 - lat) / 180 * (height - 1))
        d.line([(0, y), (width, y)], fill=(200, 200, 220) if lat == 0 else (90, 100, 130), width=6 if lat == 0 else 2)
    big = font(width // 24)
    for label, u, colour in (("BACK", 0.0, (255, 120, 120)), ("LEFT", 0.25, (120, 255, 120)), ("FRONT", 0.5, (255, 255, 255)),
                             ("RIGHT", 0.75, (120, 180, 255)), ("BACK", 1.0, (255, 120, 120))):
        x = u * width
        w = d.textlength(label, font=big)
        d.text((min(max(x - w / 2, 10), width - w - 10), height / 2 - width / 24 - 20), label, fill=colour, font=big)
    for label, y in (("UP", height * 0.06), ("DOWN", height * 0.86)):
        for u in (0.125, 0.375, 0.625, 0.875):
            w = d.textlength(label, font=big)
            d.text((u * width - w / 2, y), label, fill=(255, 220, 120), font=big)
    im.save(path, optimize=True)
    print(f"{path.relative_to(ROOT)}: {width}x{height}")


def thumb_from_image(src: Path, dst: Path) -> None:
    with Image.open(src) as im:
        im = im.convert("RGB")
        im.thumbnail(THUMB)
        canvas = Image.new("RGB", THUMB, (16, 16, 16))
        canvas.paste(im, ((THUMB[0] - im.width) // 2, (THUMB[1] - im.height) // 2))
        canvas.save(dst, quality=85)
    print(f"{dst.relative_to(ROOT)}")


def ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def videos() -> None:
    flat = ROOT / "video/test_pattern_720p.mp4"
    ffmpeg("-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=8",
           "-f", "lavfi", "-i", "sine=frequency=440:beep_factor=4:duration=8",
           "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p", "-crf", "23",
           "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(flat))
    print(f"{flat.relative_to(ROOT)}")
    grid = ROOT / "image/equirect_test_grid.png"
    vr = ROOT / "video/equirect_test_360.mp4"
    ffmpeg("-loop", "1", "-i", str(grid), "-f", "lavfi", "-i", "testsrc2=size=480x270:rate=30",
           "-f", "lavfi", "-i", "sine=frequency=660:beep_factor=2:duration=6",
           "-filter_complex", "[0]scale=2048:1024[bg];[bg][1]overlay=(W-w)/2:(H-h)/2+200:shortest=1",
           "-t", "6", "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p", "-crf", "24",
           "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(vr))
    print(f"{vr.relative_to(ROOT)}")
    for src, dst in ((flat, "thumbs/test_pattern_720p.jpg"), (vr, "thumbs/equirect_test_360.jpg")):
        ffmpeg("-ss", "2", "-i", str(src), "-frames:v", "1", "-vf", f"scale={THUMB[0]}:-2", str(ROOT / dst))
        print(dst)


def icosahedral_rotations() -> np.ndarray:
    """The 60 rotations of the icosahedral group, as unit quaternions (x, y, z, w)."""
    phi = (1 + 5 ** 0.5) / 2
    quats = set()
    for i in range(4):
        for s in (1, -1):
            q = [0.0] * 4
            q[i] = s
            quats.add(tuple(q))
    for signs in itertools.product((0.5, -0.5), repeat=4):
        quats.add(signs)
    base = (0.0, 0.5, 0.5 / phi, phi / 2)
    even = [p for p in itertools.permutations(range(4)) if sum(1 for a, b in itertools.combinations(p, 2) if a > b) % 2 == 0]
    for perm in even:
        for signs in itertools.product((1, -1), repeat=3):
            v = [base[k] for k in perm]
            nonzero = [k for k in range(4) if v[k] != 0]
            for k, s in zip(nonzero, signs):
                v[k] *= s
            quats.add(tuple(round(c, 12) for c in v))
    unique = []
    for q in quats:
        q = np.array(q)
        if not any(np.allclose(q, u) or np.allclose(q, -u) for u in unique):
            unique.append(q)
    assert len(unique) == 60, len(unique)
    return np.array(unique)


def rotate(q: np.ndarray, v: np.ndarray) -> np.ndarray:
    x, y, z, w = q
    u = np.array([x, y, z])
    return v + 2 * np.cross(u, np.cross(u, v) + w * v)


def virus_demo() -> None:
    path = ROOT / "virus/crambin_icosahedral_demo.json"
    radius = 60.0  # Angstroms from the centre to each copy
    anchor = np.array([0.0, 0.0, radius])
    instances = []
    for q in icosahedral_rotations():
        p = rotate(q, anchor + np.array([8.0, 5.0, 0.0]))  # off the symmetry axis, so copies don't overlap
        instances.append({"protein": "crambin_1crn_spacefill", "position": [round(c, 3) for c in p],
                          "rotation": [round(c, 6) for c in q]})
    data = {"schema": "thetunnel-instances/1", "units": "angstroms", "meters_per_unit": 1e-10,
            "note": "Demo only: 60 crambins placed with icosahedral symmetry, to show the instance-list format.",
            "instances": instances}
    path.write_text(json.dumps(data, indent=1) + "\n")
    print(f"{path.relative_to(ROOT)}: {len(instances)} instances")


def render_atoms(centres: list[np.ndarray], elements: list[str], dst: Path) -> None:
    """A quick orthographic picture of atoms as shaded discs, nearest last."""
    pts = np.array(centres)
    lo, hi = pts.min(0) - 2, pts.max(0) + 2
    scale = min(THUMB[0] / (hi[0] - lo[0]), THUMB[1] / (hi[1] - lo[1])) * 0.92
    im = Image.new("RGB", THUMB, (16, 16, 16))
    d = ImageDraw.Draw(im)
    order = np.argsort(pts[:, 2])
    zmin, zmax = pts[:, 2].min(), pts[:, 2].max()
    for i in order:
        x, y, z = pts[i]
        r = RADII.get(elements[i], 1.7) * scale
        cx = THUMB[0] / 2 + (x - (lo[0] + hi[0]) / 2) * scale
        cy = THUMB[1] / 2 - (y - (lo[1] + hi[1]) / 2) * scale
        depth = 0.55 + 0.45 * (z - zmin) / max(zmax - zmin, 1e-6)
        colour = tuple(int(255 * c * depth) for c in COLORS.get(elements[i], (0.8, 0.5, 0.8)))
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=colour, outline=tuple(int(c * 0.6) for c in colour))
    im.save(dst, quality=85)
    print(f"{dst.relative_to(ROOT)}")


def molecule_thumbs() -> None:
    atoms = read_atoms(ROOT / "molecule/1crn.cif")
    centres = [np.array(a[:3]) for a in atoms]
    mean = np.mean(centres, 0)
    centres = [c - mean for c in centres]
    elements = [a[3] for a in atoms]
    render_atoms(centres, elements, ROOT / "thumbs/1crn.jpg")
    demo = json.loads((ROOT / "virus/crambin_icosahedral_demo.json").read_text())
    all_c, all_e = [], []
    for inst in demo["instances"]:
        q, p = np.array(inst["rotation"]), np.array(inst["position"])
        for c, e in zip(centres, elements):
            if e != "H":
                all_c.append(rotate(q, c) + p)
                all_e.append(e)
    render_atoms(all_c, all_e, ROOT / "thumbs/crambin_icosahedral_demo.jpg")


def main() -> None:
    for folder in ("image", "video", "virus", "thumbs"):
        (ROOT / folder).mkdir(exist_ok=True)
    equirect_grid(ROOT / "image/equirect_test_grid.png")
    thumb_from_image(ROOT / "image/equirect_test_grid.png", ROOT / "thumbs/equirect_test_grid.jpg")
    videos()
    virus_demo()
    molecule_thumbs()


if __name__ == "__main__":
    main()
