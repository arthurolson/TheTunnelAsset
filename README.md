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
  assemblies/  ligands/  proteins/      The Tunnel's molecule categories (add more: chemicals/, nucleic-acids/)
virus/      .glb whole-virus or capsid meshes, and .json instance lists   glTF y-up, Angstroms
  capsids/                              The Tunnel's viral capsids (capsids/external/: hosted as Release assets)
thumbs/     one .jpg per asset (about 480 x 360)
tools/      build_manifest.py writes assets.json; the scripts that made the assets
assets.json the index of every asset, for apps (generated: don't edit it by hand)
```

Next to every asset file is a small metadata sidecar named after it, for example `mesh/foo.glb.meta.json`.
- Kind folders can have subfolders; an asset's kind comes from its top folder.
- The molecules and capsids are the ones The Tunnel ships (Mol* glTF exports). Their `category` field names the TS Menu
  category they're in.

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

**Thumbnails** for meshes, molecules and viruses can be drawn from the glb itself:
```bash
python3 tools/glb_thumbnail.py molecule/proteins/foo.glb thumbs/foo.jpg
```
To turn an OBJ with MTL colours (as some molecular-surface tools write) into a glb:
```bash
python3 tools/obj_mtl_to_glb.py surface.obj virus/capsids/foo.glb
```

### Large files

- GitHub refuses files over 100 MB, so the generator stops at 95 MB.
- Don't use Git LFS: raw.githubusercontent.com serves an LFS file's pointer, not its data. The generator refuses LFS
  pointers.
- Put a larger file (a long 4K video, say) in a GitHub Release or object storage instead:
  1. Keep the file locally in an `external/` folder inside its kind's folder, for example
     `video/external/tour.mp4`. Git ignores it.
  2. Commit its sidecar, `video/external/tour.mp4.meta.json`, with `"url"` set to where it's hosted.
  3. Run the generator with the local copy there. It reads the file's stats and checksum, and writes `bytes`,
     `sha256` and the stats into the sidecar, so a clone without the file (or the GitHub Action) gets the same
     `assets.json`.
  4. To host it as a Release asset:
     ```bash
     gh release create media-1 video/external/tour.mp4
     ```
     Its url is `https://github.com/<owner>/TheTunnelAsset/releases/download/media-1/tour.mp4`.
     `virus/capsids/external/sars_cov_2_virion.glb` (324 MB) is hosted this way, in release `molecules-1`.

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

## Pipelines: one command, one asset

Each pipeline takes one input file and writes the asset files, a thumbnail and a sidecar for each, then regenerates
`assets.json`. Check the thumbnails, then `git add -A && git commit && git push`, and the asset is in the headset.

**Setting up (once).** Both pipelines run with the Python of a conda environment that has SHARP and the libraries
they use:

```bash
git clone https://github.com/apple/ml-sharp && cd ml-sharp
conda create -n sharp python=3.13 && conda activate sharp
pip install -r requirements.txt
pip install plyfile trimesh scipy pillow opencv-python-headless
```

### A. One photo -> splat -> mesh: `tools/photo_to_asset.py`

```bash
~/miniforge3/envs/sharp/bin/python tools/photo_to_asset.py photos/lab.jpg \
    --id art_lab --subject art --title "Art in the lab" --tags person,lab --splatlook --background 92
# about 2 minutes on the CPU; the first run also downloads SHARP's 2.8 GB checkpoint
```

It writes:

| file | id | what it is |
|---|---|---|
| `splat/<id>.ply` | `<id>_splat` | the SHARP splat: 1,179,648 Gaussians (2 layers of 768 x 768), OpenCV coordinates |
| `mesh/<id>_mesh.glb` | `<id>_mesh` | its front layer as a vertex-coloured relief (glTF y-up, about 1M triangles) |
| `mesh/<id>_mesh_quest.glb` | `<id>_mesh_quest` | the relief merged on a grid to about 300k triangles; headsets load it instead |
| `mesh/<id>_splatlook.glb` | `<id>_splatlook` | with `--splatlook`: one quad per Gaussian (left out if over 95 MB) |
| `mesh/<id>_splatlook_quest.glb` | `<id>_splatlook_quest` | the same, voxel-decimated to about 300k triangles for Quest |
| `thumbs/<id>.jpg`, `thumbs/<id>_mesh.jpg` | | the photo, and a drawing of the mesh |

- **The relief mesh.** SHARP's front layer is triangulated, two triangles per cell, leaving out triangles:
  - across a depth jump (max z / min z ≥ 1.04);
  - on near-transparent points (opacity ≤ 0.1).
- **Options:**
  - `--background P` drops anything further than the P-th percentile of depth (a sky or a far wall) from the mesh
    and the splat-look.
  - `--background-depth D` drops anything further than D meters from the camera instead, for a backdrop just
    behind the subject. In a studio portrait, look for the empty gap in depth between the person and the backdrop.
  - `--main-piece` keeps only the mesh's main piece, dropping loose bits such as a table edge beside a photographed
    print.
  - `--trim F` leaves out a margin of F (e.g. 0.05) at each edge of the photo, for a photo of a print with its border
    or a ragged edge.
  - `--soft` makes the splat-look quads fade out from their centre and by their opacity (alpha-blended). The Tunnel
    draws them opaque.
  - `--device`: SHARP runs on the CPU by default, which takes about 2 minutes and 9 GB of memory on a Mac. `mps`
    (the Apple GPU) is faster, but its first run on a 24 GB Mac, with Unity open, seems to have taken the whole Mac
    down. `cuda` is for an NVIDIA GPU.
  - `--splat file.ply` starts from a splat you already have.
- **Its limits:**
  - SHARP reconstructs only what the camera saw. The back of everything is empty, and the mesh is a relief, not a
    closed object.
  - Look at the results from roughly the front.

### B. Orbit or turntable video -> full 3D model and splat: `tools/video_to_asset.sh`

```bash
tools/video_to_asset.sh orbit.mov --id art_standing --subject art --title "Art, standing" --height 1.80
```

It writes `mesh/<id>_fullbody.glb` and `.usdz` (real size, feet at y = 0), `splat/<id>_fullbody.ply` and a four-view
thumbnail. It needs a Mac with Apple silicon (Apple Object Capture) and takes about 12 minutes for 270 frames.
- **Several videos** of the same subject go in together (`a.mov b.mov`): filmed from different heights, they fill in
  the top of the head and under the arms.
- **Turntable** (the subject turns, the camera and room stay still, as on a swivel chair): add `--turntable`. Each
  frame is cut out onto grey with Apple Vision first, so Object Capture follows the subject and not the room. It can
  still fill the space under a chair seat with that grey: `--grey-below 0.5` removes grey triangles lower than 0.5 m
  (the GLB is cleaned, so no USDZ is written). A seated person was made with
  `--turntable --grey-below 0.5 --height 1.30`.
- **The splat** is sampled over the textured mesh (`tools/mesh_to_splat.py`, 600,000 flat Gaussians lying in the
  surface; `--splat-count` changes that). It's all round, unlike SHARP's, but only as detailed as the mesh: a trained
  3D Gaussian Splatting model (needs an NVIDIA GPU; Postshot, nerfstudio, gsplat) gives finer hair and edges.
- **Settings:** `--detail full` for a hero asset (`reduced` if the file comes out over 95 MB).
- **Frames:** `--fps` and `--drop` choose them (10 per second, blurriest 20% left out).
- **On Windows or Linux:** run the frames through RealityScan, Meshroom or COLMAP + OpenMVS, then
  `tools/obj_to_glb.py`.

The capture tips under "Making new assets step by step" below matter more than any setting.

### Too large for GitHub

A splat or model over 95 MB stops either pipeline. Then:
- crop it with `--background`;
- or compress a splat to `.spz` / `.sog`;
- or host the file elsewhere with its `url` in the sidecar (see "Large files" above).

## Making new assets step by step (what the pipelines run)

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
