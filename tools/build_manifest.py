"""Regenerate assets.json from the asset files and their metadata sidecars.

Every asset is a file in one of the kind folders plus a sidecar next to it named after it:

    mesh/foo.glb
    mesh/foo.glb.meta.json     {"id": "foo", "subject": "...", "title": "...", "tags": [...], ...}

The kind comes from the folder (mesh, splat, image, video, molecule, virus). Format, mime type, size, sha256 and stats
(vertices and faces, image size, video duration and codec, atom and chain counts...) are read from the file itself.
A file too large for GitHub can live elsewhere (a GitHub Release asset, object storage): give its "url" in the sidecar
and either keep the file locally, untracked, for its stats and checksum, or give "bytes" and "sha256" in the sidecar.

    python3 tools/build_manifest.py            # write assets.json
    python3 tools/build_manifest.py --check    # fail if anything is wrong or assets.json is out of date
    python3 tools/build_manifest.py --repo someone/TheTunnelAsset --branch main

The repository and branch the URLs point at come from `git remote get-url origin` and the current branch, unless given.
Needs Python 3.9+. Optional: Pillow (image sizes; a small built-in reader is used otherwise), ffprobe (video stats).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import struct
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "thetunnel-assets/2"
SIDECAR = ".meta.json"

# Folders, in the order assets are listed, and the kind of asset each holds.
KIND_FOLDERS = {"mesh": "mesh", "splat": "splat", "image": "image", "video": "video", "molecule": "molecule", "virus": "virus"}

MAX_BYTES = 95_000_000   # GitHub refuses files over 100 MB
CDN_MAX_BYTES = 20_000_000  # jsDelivr serves files under 20 MB

FORMATS = {
    ".glb": ("gltf-binary", "model/gltf-binary"),
    ".usdz": ("usdz", "model/vnd.usdz+zip"),
    ".ply": ("gaussian-splat-ply", "application/octet-stream"),
    ".jpg": ("jpeg", "image/jpeg"),
    ".jpeg": ("jpeg", "image/jpeg"),
    ".png": ("png", "image/png"),
    ".mp4": ("mp4", "video/mp4"),
    ".pdb": ("pdb", "chemical/x-pdb"),
    ".cif": ("mmcif", "chemical/x-mmcif"),
    ".json": ("instance-list-json", "application/json"),
}

# Named coordinate conventions a sidecar can use ("coordinates": "gltf"), or it can give the object itself.
COORDINATES = {
    "gltf": {"convention": "gltf", "x": "right", "y": "up", "z": "toward viewer", "units": "meters (approx.)",
             "meters_per_unit": 1.0},
    "gltf-meters": {"convention": "gltf", "x": "right", "y": "up", "z": "toward viewer", "units": "meters",
                    "meters_per_unit": 1.0},
    "angstrom": {"convention": "gltf", "x": "right", "y": "up", "z": "toward viewer", "units": "angstroms",
                 "meters_per_unit": 1e-10},
    "opencv": {"convention": "opencv", "x": "right", "y": "down", "z": "forward", "units": "meters (approx.)",
               "meters_per_unit": 1.0, "to_y_up": "rotate 180 deg about X"},
}
DEFAULT_COORDINATES = {"mesh": "gltf", "splat": "opencv", "molecule": "angstrom", "virus": "angstrom"}

# Fields the generator works out itself; a sidecar can't set them (except url, bytes and sha256 for external files).
GENERATED = {"kind", "format", "mime", "path", "url", "cdn_url", "bytes", "sha256"}
CHECK_ONLY = False  # set by --check: write nothing, not even sidecars


class Problem(Exception):
    pass


# ----------------------------------------------------------------------------------------------------------------------
# Where the URLs point


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def repo_from_git() -> str:
    url = git("remote", "get-url", "origin")
    m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?/?$", url)
    if not m:
        raise Problem(f"origin ({url}) isn't a GitHub repository: pass --repo owner/name")
    return m.group(1)


def branch_from_git() -> str:
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    if branch == "HEAD":  # detached, as in GitHub Actions on a tag
        raise Problem("no current branch: pass --branch")
    return branch


# ----------------------------------------------------------------------------------------------------------------------
# Stats, read from the files themselves


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def glb_stats(path: Path) -> dict:
    """Vertices and triangles as drawn (every placed copy of a mesh), and where the colour is, from the glb's JSON."""
    with path.open("rb") as f:
        magic, _, _ = struct.unpack("<4sII", f.read(12))
        length, kind = struct.unpack("<I4s", f.read(8))
        if magic != b"glTF" or kind != b"JSON":
            raise Problem(f"{path}: not a glTF binary")
        gltf = json.loads(f.read(length))
    accessors = gltf.get("accessors", [])
    # Count each mesh as often as nodes place it (molecular exports place one capsid protein 60 or 180 times).
    uses = [0] * len(gltf.get("meshes", []))
    for node in gltf.get("nodes", []):
        if "mesh" in node:
            uses[node["mesh"]] += 1
    vertices = faces = 0
    vertex_colors = textured = False
    for mesh, used in zip(gltf.get("meshes", []), uses):
        for primitive in mesh.get("primitives", []):
            attributes = primitive.get("attributes", {})
            count = accessors[attributes["POSITION"]]["count"] if "POSITION" in attributes else 0
            vertices += count * used
            if primitive.get("mode", 4) == 4:
                faces += (accessors[primitive["indices"]]["count"] if "indices" in primitive else count) // 3 * used
            vertex_colors |= "COLOR_0" in attributes
    for material in gltf.get("materials", []):
        textured |= "baseColorTexture" in material.get("pbrMetallicRoughness", {})
    color = "vertex" if vertex_colors else "texture" if textured else "material"
    return {"vertices": vertices, "faces": faces, "color": color}


def ply_stats(path: Path) -> dict:
    """The number of Gaussians (the vertex element) from a 3DGS .ply's header."""
    with path.open("rb") as f:
        header = b""
        while not header.endswith(b"end_header\n"):
            line = f.readline()
            if not line:
                raise Problem(f"{path}: no PLY header")
            header += line
    gaussians = None
    for line in header.decode("ascii", "replace").splitlines():
        parts = line.split()
        if parts[:2] == ["element", "vertex"]:
            gaussians = int(parts[2])
    return {"gaussians": gaussians} if gaussians is not None else {}


def image_size(path: Path) -> tuple[int, int]:
    try:
        from PIL import Image

        with Image.open(path) as im:
            return im.size
    except ImportError:
        pass
    data = path.read_bytes()
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", data[16:24])
    i = 2  # JPEG: find a start-of-frame marker
    while i < len(data) - 9:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        length = struct.unpack(">H", data[i + 2:i + 4])[0]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return w, h
        i += 2 + length
    raise Problem(f"{path}: can't read the image size")


def image_stats(path: Path) -> dict:
    w, h = image_size(path)
    return {"width": w, "height": h}


def mp4_faststart(path: Path) -> bool:
    """True if the moov atom comes before mdat, so the video can start playing while it streams."""
    with path.open("rb") as f:
        while True:
            head = f.read(8)
            if len(head) < 8:
                return False
            size, kind = struct.unpack(">I4s", head)
            if kind == b"moov":
                return True
            if kind == b"mdat":
                return False
            if size == 1:
                size = struct.unpack(">Q", f.read(8))[0] - 8
            elif size == 0:
                return False
            f.seek(size - 8, 1)


def video_stats(path: Path) -> dict:
    out = {"faststart": mp4_faststart(path)}
    if not shutil.which("ffprobe"):
        print(f"  (no ffprobe: {path.name} has no duration, resolution or codec)", file=sys.stderr)
        return out
    probe = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, check=True).stdout)
    video = next((s for s in probe.get("streams", []) if s.get("codec_type") == "video"), None)
    audio = next((s for s in probe.get("streams", []) if s.get("codec_type") == "audio"), None)
    if video:
        num, _, den = video.get("avg_frame_rate", "0/1").partition("/")
        out.update(width=video.get("width"), height=video.get("height"), codec=video.get("codec_name"),
                   fps=round(float(num) / float(den), 3) if float(den or 0) else None)
    if audio:
        out["audio_codec"] = audio.get("codec_name")
    if "duration" in probe.get("format", {}):
        out["duration"] = round(float(probe["format"]["duration"]), 3)
    return out


def pdb_stats(path: Path) -> dict:
    atoms, chains = 0, set()
    with path.open(errors="replace") as f:
        for line in f:
            if line.startswith(("ATOM  ", "HETATM")):
                atoms += 1
                chains.add(line[21:22])
            elif line.startswith("ENDMDL"):
                break  # the first model only
    return {"atoms": atoms, "chains": len(chains)}


def cif_stats(path: Path) -> dict:
    """Atoms and chains from the _atom_site loop of an mmCIF file (the first model only)."""
    columns: list[str] = []
    atoms, chains = 0, set()
    in_loop = reading = False
    with path.open(errors="replace") as f:
        for line in f:
            s = line.strip()
            if s == "loop_":
                in_loop, columns, reading = True, [], False
                continue
            if in_loop and s.startswith("_atom_site."):
                columns.append(s.split()[0][len("_atom_site."):])
                continue
            if in_loop and columns and not s.startswith("_"):
                reading, in_loop = True, False
            if reading:
                if not s or s.startswith(("#", "loop_", "_")):
                    break
                values = s.split()
                if "pdbx_PDB_model_num" in columns and values[columns.index("pdbx_PDB_model_num")] != "1":
                    continue
                atoms += 1
                for key in ("auth_asym_id", "label_asym_id"):
                    if key in columns:
                        chains.add(values[columns.index(key)])
                        break
    return {"atoms": atoms, "chains": len(chains)}


def instance_stats(path: Path) -> dict:
    data = json.loads(path.read_text())
    instances = data.get("instances", [])
    return {"instances": len(instances), "proteins": sorted({i.get("protein") for i in instances if i.get("protein")})}


def file_stats(path: Path) -> dict:
    suffix = path.suffix.lower()
    if suffix == ".glb":
        return glb_stats(path)
    if suffix == ".ply":
        return ply_stats(path)
    if suffix in (".jpg", ".jpeg", ".png"):
        return image_stats(path)
    if suffix == ".mp4":
        return video_stats(path)
    if suffix == ".pdb":
        return pdb_stats(path)
    if suffix == ".cif":
        return cif_stats(path)
    if suffix == ".json":
        return instance_stats(path)
    return {}


# ----------------------------------------------------------------------------------------------------------------------
# The manifest


def find_sidecars() -> list[Path]:
    found: list[Path] = []
    for folder in KIND_FOLDERS:
        found += sorted((ROOT / folder).glob("**/*" + SIDECAR))
    return found


def is_ignored(rel: str) -> bool:
    return subprocess.run(["git", "check-ignore", "-q", rel], cwd=ROOT).returncode == 0


def build(raw: str, cdn: str, problems: list[str]) -> list[dict]:
    items, seen = [], {}
    for sidecar in find_sidecars():
        rel_sidecar = sidecar.relative_to(ROOT).as_posix()
        try:
            meta = json.loads(sidecar.read_text())
        except json.JSONDecodeError as e:
            problems.append(f"{rel_sidecar}: not valid JSON ({e})")
            continue
        file = sidecar.with_name(sidecar.name[: -len(SIDECAR)])
        rel = file.relative_to(ROOT).as_posix()
        kind = meta.get("kind") or KIND_FOLDERS[rel.split("/")[0]]
        asset_id = meta.get("id")
        if not asset_id or not re.fullmatch(r"[a-z0-9][a-z0-9_\-]*", asset_id):
            problems.append(f"{rel_sidecar}: 'id' must be lower-case letters, digits, '_' or '-'")
            continue
        if asset_id in seen:
            problems.append(f"duplicate id {asset_id}: {seen[asset_id]} and {rel}")
            continue
        seen[asset_id] = rel
        if file.suffix.lower() not in FORMATS:
            problems.append(f"{rel}: unknown file type {file.suffix}")
            continue
        fmt, mime = FORMATS[file.suffix.lower()]

        external = meta.get("url")  # a file kept outside the repository (a Release asset, object storage)
        if file.exists():
            with file.open("rb") as f:
                if f.read(40).startswith(b"version https://git-lfs"):
                    problems.append(f"{rel}: a Git LFS pointer; raw.githubusercontent.com would serve the pointer, "
                                    "not the file (keep it in git, or host it elsewhere and give its url)")
                    continue
            size = file.stat().st_size
            digest = sha256(file)
            if meta.get("sha256") and meta["sha256"] != digest and not external:
                problems.append(f"{rel}: sha256 {digest} doesn't match the sidecar's {meta['sha256']}")
            if not external and size > MAX_BYTES:
                problems.append(f"{rel}: {size / 1e6:.1f} MB, over the {MAX_BYTES / 1e6:.0f} MB limit "
                                "(GitHub refuses 100 MB): host it elsewhere and give its url in the sidecar")
            if external and not is_ignored(rel):
                problems.append(f"{rel}: has an external url but is also in git; add it to .gitignore")
            try:
                stats = file_stats(file)
            except Exception as e:  # an unreadable file is a problem to report, not a crash
                problems.append(f"{rel}: can't read it ({e})")
                continue
            if external and (meta.get("bytes") != size or meta.get("sha256") != digest
                             or any(meta.get(k) != v for k, v in stats.items())):
                # Where the file isn't (GitHub Actions, other clones), the sidecar's size, checksum and stats stand in.
                if CHECK_ONLY:
                    problems.append(f"{rel_sidecar}: bytes and sha256 out of date; run python3 tools/build_manifest.py")
                else:
                    meta.update(bytes=size, sha256=digest, **stats)
                    sidecar.write_text(json.dumps(meta, indent=2) + "\n")
                    print(f"  (wrote bytes and sha256 into {rel_sidecar})")
        elif external and meta.get("bytes") and meta.get("sha256"):
            size, digest, stats = int(meta["bytes"]), meta["sha256"], {}
        else:
            problems.append(f"{rel_sidecar}: no {rel} (an external file needs url, bytes and sha256 in its sidecar)")
            continue

        thumbnail = meta.get("thumbnail") or f"thumbs/{file.name.split('.')[0]}.jpg"
        if not (ROOT / thumbnail).exists():
            problems.append(f"{rel}: no thumbnail {thumbnail}")
        if kind == "video" and stats.get("faststart") is False:
            problems.append(f"{rel}: moov atom after the data, so it won't stream; fix with "
                            "ffmpeg -i in.mp4 -c copy -movflags +faststart out.mp4")
        if kind == "video" and stats.get("codec") not in (None, "h264", "hevc"):
            problems.append(f"{rel}: video codec {stats.get('codec')}; the Quest plays H.264 (or H.265)")

        item = {
            "id": asset_id,
            "kind": kind,
            "subject": meta.get("subject", ""),
            "title": meta.get("title", asset_id),
            "tags": meta.get("tags", []),
            "format": fmt,
            "mime": mime,
            "path": rel,
            "url": external or raw + rel,
            "cdn_url": cdn + rel if not external and size < CDN_MAX_BYTES else None,
            "bytes": size,
            "sha256": digest,
            "thumbnail": raw + thumbnail,
        }
        coordinates = meta.get("coordinates", DEFAULT_COORDINATES.get(kind))
        if isinstance(coordinates, str):
            if coordinates not in COORDINATES:
                problems.append(f"{rel_sidecar}: unknown coordinates '{coordinates}' ({', '.join(COORDINATES)})")
            coordinates = COORDINATES.get(coordinates)
        if coordinates:
            item["coordinates"] = coordinates
        item.update(stats)
        for key, value in meta.items():  # everything else in the sidecar is passed on as it is
            if key not in item and key not in GENERATED and key not in ("id", "thumbnail", "coordinates"):
                item[key] = value
        items.append(item)
        print(f"  {asset_id:36s} {kind:9s} {size / 1e6:7.1f} MB")

    # A molecule's surface, and the proteins in an instance list, must be assets too.
    ids = {i["id"] for i in items}
    for item in items:
        for ref in [item.get("surface")] + list(item.get("proteins", [])):
            if ref and ref not in ids:
                problems.append(f"{item['id']}: refers to {ref}, which isn't an asset")
    return items


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo", help="owner/name the URLs point at (default: git remote origin)")
    parser.add_argument("--branch", help="branch the URLs point at (default: the current branch)")
    parser.add_argument("--check", action="store_true", help="don't write; fail if anything is wrong or out of date")
    args = parser.parse_args()
    global CHECK_ONLY
    CHECK_ONLY = args.check

    try:
        repo = args.repo or repo_from_git()
        branch = args.branch or branch_from_git()
    except (Problem, subprocess.CalledProcessError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    raw = f"https://raw.githubusercontent.com/{repo}/{branch}/"
    cdn = f"https://cdn.jsdelivr.net/gh/{repo}@{branch}/"
    print(f"assets for {repo}@{branch}")

    problems: list[str] = []
    items = build(raw, cdn, problems)
    path = ROOT / "assets.json"
    previous = json.loads(path.read_text()) if path.exists() else {}
    manifest = {
        "schema": SCHEMA,
        "repo": f"https://github.com/{repo}",
        "branch": branch,
        "base_url": raw,
        "updated": previous.get("updated", ""),
        "count": len(items),
        "kinds": sorted({i["kind"] for i in items}),
        "subjects": sorted({i["subject"] for i in items if i["subject"]}),
        "assets": items,
    }
    unchanged = {k: v for k, v in manifest.items() if k != "updated"} == {k: v for k, v in previous.items() if k != "updated"}
    if not unchanged or not manifest["updated"]:
        manifest["updated"] = date.today().isoformat()

    if args.check and not unchanged:
        old = previous.get("assets", [])
        stale = [i["id"] for i in items if i not in old]
        problems.append("assets.json is out of date" + (f" ({', '.join(stale)})" if stale else "")
                        + ": run python3 tools/build_manifest.py and commit it")
    for p in problems:
        print(f"PROBLEM: {p}", file=sys.stderr)
    if problems:
        return 1
    if args.check:
        print(f"assets.json is up to date ({len(items)} assets)")
    elif unchanged:
        print(f"assets.json unchanged ({len(items)} assets)")
    else:
        path.write_text(json.dumps(manifest, indent=2) + "\n")
        print(f"wrote assets.json ({len(items)} assets)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
