# TheTunnelAsset

Assets for The Tunnel, a shared mixed reality space for molecular biology on Meta Quest:
- 3D portraits of David Goodsell, Art and the Scripps building in the 1920s (Gaussian splats and meshes);
- images, videos, molecules and viruses, each kind in its own folder.

The app reads `assets.json` when it starts, so an asset pushed here appears in the headset without a new build.
This repository is a fork of [autinlab/TheTunnelAsset](https://github.com/autinlab/TheTunnelAsset). Every id and path
from the original is unchanged.

## Layout

```
mesh/       .glb meshes (also .usdz for iOS / visionOS)       glTF y-up
splat/      .ply 3D Gaussian splats                             OpenCV (y down)
image/      .jpg / .png: posters, textures, 360 panoramas (tag "equirect")
video/      .mp4, H.264 + AAC, up to 4K, faststart; 360 video tagged "equirect" (+ "stereo-tb" for top-bottom 3D)
molecule/   .pdb / .cif atomic models, and .glb surfaces made from them   glTF y-up, Angstroms
virus/      .glb whole-virus or capsid meshes, and .json instance lists   glTF y-up, Angstroms
thumbs/     one .jpg per asset (about 480 x 360)
tools/      build_manifest.py writes assets.json; the scripts that made the assets
assets.json the index of every asset, for apps (generated: don't edit it by hand)
```

Next to every asset file is a small metadata sidecar named after it, for example `mesh/foo.glb.meta.json`.

## Adding an asset, end to end

1. **Drop in the file.** Put it in its kind's folder, and a JPG thumbnail in `thumbs/`.
2. **Write its sidecar** next to it as `<file>.meta.json`. Only `id` is required; `title`, `subject`, `tags` and
   `thumbnail` are what the app's menu shows:
   ```json
   {
     "id": "my_poster",
     "title": "Poster of the week",
     "subject": "art",
     "tags": ["poster"],
     "thumbnail": "thumbs/my_poster.jpg"
   }
   ```
   Any other fields (`source`, `method`, `license`, `notes`...) are copied into `assets.json` as they are.
3. **Run the generator and push:**
   ```bash
   python3 tools/build_manifest.py          # writes assets.json, and stops on any problem
   git add -A && git commit -m "Add my poster" && git push
   ```
   The GitHub Action also regenerates `assets.json` on every push to main, so step 3 works without running the
   script yourself. Running it first shows any problem before you push.
4. **In the headset:** the asset is in the splat-box menu the next time The Tunnel starts. raw.githubusercontent.com
   can take up to 5 minutes to show a new `assets.json`.

### By kind

| kind | files | sidecar extras | the generator reads |
|---|---|---|---|
| `mesh` | `.glb` (y-up, meters), `.usdz` | `coordinates` if not `"gltf"` | `vertices`, `faces`, `color` (`vertex`, `texture` or `material`) |
| `splat` | `.ply` (3DGS) | `source_image_size` | `gaussians` |
| `image` | `.jpg`, `.png` | `"projection": "equirect"` and the `equirect` tag for 360 panoramas | `width`, `height` |
| `video` | `.mp4`: H.264 + AAC, 1080p to 4K, faststart | `projection`, `"stereo": "mono"` or `"top-bottom"` (tag `stereo-tb`) | `width`, `height`, `duration`, `fps`, `codec`, `audio_codec`, `faststart` |
| `molecule` | `.pdb`, `.cif`, and `.glb` surfaces | `"surface": "<id of its glb>"` on the .pdb/.cif | `atoms`, `chains`; `vertices`, `faces` for .glb |
| `virus` | `.glb` meshes, `.json` instance lists | | `vertices`, `faces`; `instances`, `proteins` |

- **Images.** The centre of a 360 panorama is straight ahead (see `image/equirect_test_grid.png`).
- **Videos must stream on a Quest.** Make them like this:
  ```bash
  ffmpeg -i in.mov -c:v libx264 -profile:v high -pix_fmt yuv420p -crf 20 -vf "scale='min(3840,iw)':-2" \
         -c:a aac -b:a 160k -movflags +faststart video/my_clip.mp4
  ```
  The generator refuses a video whose `moov` atom is at the end, because it couldn't start playing until fully
  downloaded.
- **Molecules.** Give a `.pdb` / `.cif` the `surface` of a ready-made glb, and the app shows that glb.
  `tools/molecule_to_glb.py` makes a spacefill glb from any PDB or mmCIF file, with colours by element or by chain and
  shading baked in:
  ```bash
  curl -o molecule/1abc.cif https://files.rcsb.org/download/1ABC.cif
  python3 tools/molecule_to_glb.py molecule/1abc.cif molecule/1abc_spacefill.glb --color chain
  ```
  Then write two sidecars: the glb's, and the cif's with `"surface": "<the glb's id>"`.
- **Viruses.** An instance list builds a large assembly from protein meshes in the app. Each `protein` is the id of a
  glb asset. Positions and quaternion rotations `[x, y, z, w]` are in the glTF frame (y-up, right-handed), in the list's
  units:
  ```json
  {
    "schema": "thetunnel-instances/1",
    "units": "angstroms",
    "meters_per_unit": 1e-10,
    "instances": [
      {"protein": "crambin_1crn_spacefill", "position": [8.0, 5.0, 60.0], "rotation": [0, 0, 0, 1]}
    ]
  }
  ```
  `virus/crambin_icosahedral_demo.json` is an example: 60 copies of crambin with icosahedral symmetry.

### Large files

- GitHub refuses files over 100 MB, so the generator stops at 95 MB.
- Don't use Git LFS: raw.githubusercontent.com serves an LFS file's pointer, not its data. The generator refuses LFS
  pointers.
- Put a larger file (a long 4K video, say) in a GitHub Release or object storage instead:
  1. Keep the file locally in an `external/` folder inside its kind's folder, for example
     `video/external/tour.mp4`. Git ignores it.
  2. Commit its sidecar, `video/external/tour.mp4.meta.json`, with `"url"` set to where it's hosted.
  3. The generator reads the stats and checksum from the local copy. Without one, give `"bytes"` and `"sha256"` in the
     sidecar.
  4. To host it as a Release asset:
     ```bash
     gh release create media-1 video/external/tour.mp4
     ```
     Its url is `https://github.com/<owner>/TheTunnelAsset/releases/download/media-1/tour.mp4`.

## The generator: tools/build_manifest.py

```bash
python3 tools/build_manifest.py                          # write assets.json
python3 tools/build_manifest.py --check                  # write nothing; fail on any problem or a stale assets.json
python3 tools/build_manifest.py --repo owner/name --branch dev   # URLs for another repository or branch
```

- **Where the URLs point.** The repository and branch come from `git remote get-url origin` and the current branch,
  so a fork's `assets.json` points at the fork.
- **What it stops on:**
  - a file over 95 MB that isn't hosted elsewhere;
  - a duplicate id;
  - a missing thumbnail;
  - a sha256 that doesn't match the one in the sidecar;
  - a Git LFS pointer;
  - a video that isn't faststart or isn't H.264/H.265;
  - a molecule `surface` or virus `protein` that isn't an asset.
- **Needs** Python 3.9+ and nothing else. Pillow is used for image sizes if it's installed, ffprobe for video stats.

## Schema: `thetunnel-assets/2`

```
{
  "schema": "thetunnel-assets/2",
  "repo": "https://github.com/<owner>/TheTunnelAsset",
  "branch": "main",
  "base_url": "https://raw.githubusercontent.com/<owner>/TheTunnelAsset/main/",
  "updated": "YYYY-MM-DD",
  "count": N,
  "kinds": [...],
  "subjects": [...],
  "assets": [ ... ]
}
```

**Every asset has:**

| field | |
|---|---|
| `id` | stable; apps refer to assets by it |
| `kind` | `mesh`, `splat`, `image`, `video`, `molecule` or `virus` |
| `subject`, `title`, `tags` | |
| `format`, `mime` | `gltf-binary` `model/gltf-binary`, `usdz`, `gaussian-splat-ply`, `jpeg`, `png`, `mp4` `video/mp4`, `pdb` `chemical/x-pdb`, `mmcif` `chemical/x-mmcif`, `instance-list-json` `application/json` |
| `path` | |
| `url` | the file: raw.githubusercontent.com, or where an external file is hosted |
| `cdn_url` | jsDelivr; `null` at 20 MB or more, and for external files |
| `bytes`, `sha256` | for caching and checking downloads |
| `thumbnail` | a JPG url |

**Some assets also have:**
- `coordinates`, for meshes, splats, molecules and viruses: `convention`, `x`, `y`, `z`, `units`, and
  `meters_per_unit`. `meters_per_unit` is 1 for meters and 1e-10 for Angstroms, so an app can show things at their
  real size.
- `license`: `name`, `url`, `author`, `attribution`. Show the `attribution` with the asset.
- The stats for its kind (see "By kind").
- Anything else its sidecar gives.

**Changes from `thetunnel-assets/1`:**
- New kinds `image`, `video`, `molecule` and `virus`.
- New top-level `branch` and `kinds`.
- `coordinates.meters_per_unit`.
- Per-kind stats.
- `color` is now read from the glb itself: the vertex-coloured meshes that v1 called `texture` are now `vertex`.
- Assets come from sidecars instead of a list in the Python file.

Every v1 field is still there, with the same meaning. Apps should ignore kinds and fields they don't know.

## How they were made

- **Splats**: [SHARP](https://github.com/apple/ml-sharp) (Apple), one photo in, one 3DGS `.ply` out
  (about 1.18M Gaussians, 2 layers of 768x768). SHARP reconstructs only what the camera saw, so
  the back of every scene is empty. Look at them from roughly the front.
- **Scripps 1924**: SHARP on a 1920s photograph of the Scripps building. Cleaned versions
  remove the sky and floaters, or push the sky out to a distant backdrop. `scripps_1924_supersplat`
  is the version edited and published on SuperSplat.
- **Splat-look meshes** (`*_splatlook*`): one small textured quad per Gaussian, so a plain mesh
  renderer (Quest, three.js, Unity without a splat plugin) gets a splat-like look.
- **2.5D meshes** (`goodsell_portrait_mesh*`, `art_photo_mesh`): the front layer of a SHARP splat
  triangulated as a grid, with triangles across depth jumps removed. A relief, not a closed object.
- **Full-body mesh** (`art_video_fullbody_*`): Apple Object Capture (RealityKit
  `PhotogrammetrySession`, medium detail) on 134 sharp frames from a 17 s orbit video.
  It is a full 360 degree model, but the subject moved during the capture, so there is a faint ghost second head
  and an extra sheet of surface on one side. Its scale is arbitrary (about 1.35 m tall), so rescale it to his real
  height before use. It is a candidate for auto-rigging (Mixamo / AccuRIG, then Unity Humanoid).

## Credits and licenses

- `splat/scripps_1924_supersplat.ply`: "Scripps 1924" by LMGL
  ([superspl.at/scene/2e27822f](https://superspl.at/scene/2e27822f)), licensed
  [CC BY 4.0](http://creativecommons.org/licenses/by/4.0/). You must credit the author when you reuse it.
  Assets with a license have a `license` field in `assets.json`.
- `molecule/1crn.cif`: PDB entry 1CRN (crambin, M.M. Teeter) from the [RCSB PDB](https://www.rcsb.org/structure/1CRN),
  CC0. The spacefill glb is made from it with `tools/molecule_to_glb.py`.
- Splats were made with [SHARP](https://github.com/apple/ml-sharp). See its license for model terms.

## Making new assets (the exact scripts used for the assets above)

Use these scripts as they are. They hold the settings that produced the current assets.
These Python scripts need `numpy plyfile trimesh` (+ `scipy pillow` for frames); the
[ml-sharp](https://github.com/apple/ml-sharp) conda env has most of them.

**Photo -> splat -> mesh**

```bash
# 1. splat (Apple SHARP, runs on mps / cuda / cpu; checkpoint downloads on first run)
sharp predict -i photos/ -o out/ --device mps            # -> out/<name>.ply (OpenCV coords)
# 2. 2.5D relief mesh from the front layer, vertex colors, y-up   -> out/<id>_mesh.ply + .glb
python tools/splat_to_mesh.py out/<name>.ply out/<id>_mesh
# 3. splat-look mesh: one quad per Gaussian (optionally decimated for Quest)
python tools/splat2glb.py out/<name>.ply mesh/<id>_splatlook.glb 1.6
python tools/splat2glb.py out/<name>.ply mesh/<id>_splatlook_quest.glb 1.6 100000 "credit"
```

| script | what it does |
|---|---|
| `splat_to_mesh.py` | triangulates layer 0 of the 2x768x768 SHARP grid; drops triangles across depth jumps (z ratio >= 1.04) or with opacity <= 0.1; flips to y-up |
| `splat2glb.py` | args: `in.ply out.glb [sigma] [target_splats] [copyright]`; quads span +-sigma along the 2 largest Gaussian axes; drops opacity < 0.2; unlit linear vertex colors |
| `clean_splat_sky.py` | **example only**: the sky/floater cleanup used for Scripps 1924 (needs a sky mask; thresholds tuned for that photo) |

**Orbit video -> full 360 degree model** (macOS on Apple silicon, Apple Object Capture)

```bash
python tools/select_frames.py in.mov work/frames 10 0.2      # 10 fps, drop blurriest 20%
swift tools/object_capture.swift work/frames work/model.usdz medium   # preview|reduced|medium|full|raw
swift tools/usdz_to_obj.swift work/model.usdz work/obj/model.obj      # ModelIO, with textures
python tools/obj_to_glb.py work/obj/model.obj mesh/<id>_fullbody.glb 1.80   # real height in m, feet at y=0
cp work/model.usdz mesh/<id>_fullbody.usdz
```

`object_capture.swift` uses sequential sample ordering (video frames), high feature sensitivity
and object masking (keeps the subject, drops the room). On Windows or Linux, run the same frames
through RealityScan, Meshroom or COLMAP instead.

Capture tips. Most bad results come from the subject moving.
- The subject stands perfectly still in an A-pose (arms 30-45 degrees out).
- Film two slow loops of 20-40 s: one at chest height, one higher, looking down.
- Use even light with no backlight. Keep the whole body in frame the whole time.
- Shiny, black and very thin parts (glasses, loose hair) reconstruct poorly.
- For rigging: clean up in Blender, decimate to about 50k tris, auto-rig in Mixamo or AccuRIG,
  then use Unity Humanoid.

## Adding an asset

1. Put the file in `splat/` or `mesh/` and a JPG thumbnail in `thumbs/`.
2. Add an entry to `ASSETS` in `tools/build_manifest.py`.
3. Run `python tools/build_manifest.py` (needs `numpy plyfile trimesh`), then commit `assets.json`
   with the files.
