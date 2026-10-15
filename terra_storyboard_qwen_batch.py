#!/usr/bin/env python3
"""TERRA SINE HOMINIBUS - local storyboard still generator for ComfyUI/Qwen-Image.

This script is deliberately workflow-agnostic: you export your existing ComfyUI
Qwen-Image workflow in API format, then give this script a tiny node-map JSON.
That avoids hard-coding node IDs from somebody else's workflow.

Main commands:
  inspect   Inspect an API workflow and write a best-effort node map.
  generate  Batch-generate storyboard stills from terra_storyboard_manifest.jsonl.
  h3-manifest  Turn approved storyboard stills into an H3-ready JSONL manifest.

Dependencies:
  pip install requests pillow

Typical use:
  python terra_storyboard_qwen_batch.py inspect \
      --workflow workflows/qwen_image_api.json \
      --write-map qwen_nodes.json

  python terra_storyboard_qwen_batch.py generate \
      --workflow workflows/qwen_image_api.json \
      --node-map qwen_nodes.json \
      --manifest terra_storyboard_manifest.jsonl \
      --variants 4 --include-endframes

  # Put chosen keyframes in approved/ as S01.png, S02.png ...
  # Optional end frames: approved/S60_end.png, approved/S62_end.png ...
  python terra_storyboard_qwen_batch.py h3-manifest \
      --manifest terra_storyboard_manifest.jsonl \
      --approved-dir approved \
      --output terra_h3_from_approved.jsonl
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

try:
    import requests
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Missing dependency: requests. Install with: pip install requests") from exc

try:
    from PIL import Image
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Missing dependency: Pillow. Install with: pip install pillow") from exc


# -----------------------------------------------------------------------------
# Project-wide visual language
# -----------------------------------------------------------------------------
# The user reference was a modern, realistic Japanese action-animation look.
# We encode the *visual attributes* rather than depending on a studio/franchise
# name, which is more repeatable across Qwen-Image -> H3.
STYLE_PROMPT = (
    "high-end contemporary Japanese cinematic animation, semi-realistic 2D anime, "
    "mature realistic proportions, precise hand-drawn linework, crisp controlled contours, "
    "restrained two-to-three-tone cel shading, realistic architecture and industrial design, "
    "3D-informed perspective but unmistakably hand-drawn 2D compositing, subtle filmic texture, "
    "cinematic lens language, strong but believable perspective, detailed background art, "
    "graphite grey and cool cyan palette with sparse sodium-amber practical lights, "
    "natural overcast daylight or motivated practical lighting, atmospheric depth and haze, "
    "serious modern urban tone, grounded materials, restrained contrast, no decorative fantasy styling"
)

NEGATIVE_PROMPT = (
    "photoreal live-action photo, glossy CGI, game render, plastic 3D anime, chibi, super-deformed, "
    "cute moe aesthetic, idol anime, watercolor illustration, oil painting, sketch page, manga panel, "
    "thick cartoon outline, oversaturated neon cyberpunk, vaporwave, fantasy armor, ornamental mecha, "
    "giant hologram UI, floating text, subtitles, logo, watermark, signature, readable text, "
    "bad perspective, warped architecture, duplicated objects, malformed machinery, extra limbs, "
    "extra fingers, deformed hands, melted faces, low detail, blurry foreground, jpeg artifacts"
)

PACK_PROMPTS = {
    "city": (
        "near-future 2026 urban environment, contemporary offices, transit and streets, "
        "clean lived-in human traces but no disaster damage, understated Japanese-animation background art"
    ),
    "machine": (
        "data centers, logistics automation and network infrastructure, believable engineering, "
        "dense cables, vents, racks, status lights, practical robotics, quiet machine rhythm"
    ),
    "lab": (
        "advanced robotics laboratory, clean white-grey industrial surfaces, calibration rigs, "
        "tooling, robot test zones, practical research equipment, believable engineering scale"
    ),
    "resource": (
        "large-scale energy, mining, port, agriculture and industrial infrastructure, "
        "weathered but maintained machinery, physically plausible scale, documentary industrial detail"
    ),
    "sim": (
        "scientific visualization and reality-anomaly imagery, initially subtle and physically grounded, "
        "later revealing procedural repetition, render seams and simulation structure without flashy cyberpunk"
    ),
}

ROBOT_BIBLE = (
    "recurring utility humanoid robot design: faceless off-white ceramic-metal shell, exposed graphite joints, "
    "single narrow black rectangular sensor bar instead of a face, no eyes, no mouth, slim practical proportions, "
    "tool-like hands, no decorative armor, no heroic silhouette"
)

HUMAN_BIBLE = (
    "ordinary contemporary commuters and office workers, mature anime facial proportions, understated clothing, "
    "natural gestures, no fashion-editorial posing"
)

NO_HUMANS = "no living humans visible, no corpses, no human silhouettes, only human-made traces remain"

# First-frame overrides for transition shots. These make the still pair describe
# two clean states instead of asking the image model to depict motion in one frame.
KEY_FRAME_OVERRIDES: dict[str, str] = {
    "S32": "close-up of the robot hand attempting to grasp a small metal bolt; the bolt is just slipping from the fingertips, before the successful grip",
    "S36": "the utility humanoid robot is losing balance on the stair test rig, torso tilted and one hand reaching toward the support surface, before recovery",
    "S55": "microscopic view of an apparently natural irregular soil sample, believable mineral and organic particles, before any procedural pattern is revealed",
    "S58": "the utility humanoid robot fingertip is a few centimeters from an apparently empty point in space, with no ripple visible yet",
    "S59": "fully realistic Earth from orbit, natural clouds and atmosphere, no wireframe, no glitch, no visible render layers yet",
    "S60": "fully realistic Earth filling the frame from orbit, normal deep space around it, no external laboratory visible yet",
    "S61": "over-shoulder view of a real-world researcher's hand hovering near an abstract console control before switching it; no readable interface text",
    "S62": "locked wide view of the same subway platform completely empty of people, lights and train infrastructure normal, before the population returns",
    "S63": "wide robotics lab while the machines are still active and dispersed, before they return to charging positions and fold back into standby",
}

# End-frame overrides only for shots where FLF/I2V benefits from a deliberate terminal state.
END_FRAME_OVERRIDES: dict[str, str] = {
    "S32": "close-up of the same robot hand now firmly and correctly holding the metal bolt after the learning attempt",
    "S36": "the same utility humanoid robot has recovered and stands balanced upright on the stair test rig, one hand just leaving the support rail",
    "S55": "microscopic soil sample with the hidden regular procedural particle lattice clearly exposed beneath the natural surface texture",
    "S58": "the same robot fingertip is touching empty space and a transparent membrane-like circular ripple is visibly spreading through reality",
    "S59": "the same Earth from orbit with its realistic surface peeled into restrained low-poly wireframe and render-layer structure, still recognizably Earth",
    "S60": "wide external laboratory reveal: the entire simulated Earth hangs inside a vast research apparatus, with a real researcher's blurred hand and console in the foreground",
    "S61": "over-shoulder view of the researcher's hand having just switched the control back on; screen content remains abstract and unreadable for later compositing",
    "S62": "the exact same subway platform composition now suddenly full of ordinary commuters continuing their motions naturally, as if nothing happened",
    "S63": "the same robotics lab after the recall: all robots have returned to charging positions, mechanical arms folded, room calm and ordinary again",
}

# Shots after the API is restored can show people. S61 is the external researcher.
HUMAN_VISIBLE_SHOTS = {"S61", "S62", "S64"}
ROBOT_SHOTS = set([f"S{i:02d}" for i in range(25, 39)] + ["S58", "S63"])

SHOT_RE = re.compile(r"^S(\d{2})$")
RANGE_RE = re.compile(r"^S?(\d{1,2})-S?(\d{1,2})$", re.I)


@dataclass
class NodeTarget:
    node: str
    input: str


# -----------------------------------------------------------------------------
# Manifest + prompts
# -----------------------------------------------------------------------------
def read_jsonl(path: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{lineno}: {exc}") from exc
    return items


def write_jsonl(path: Path, items: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def shot_sort_key(shot_id: str) -> int:
    m = SHOT_RE.match(shot_id)
    return int(m.group(1)) if m else 9999


def parse_shot_filter(spec: str | None) -> set[str] | None:
    if not spec:
        return None
    out: set[str] = set()
    for token in [x.strip() for x in spec.split(",") if x.strip()]:
        m = RANGE_RE.match(token)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if a > b:
                a, b = b, a
            out.update(f"S{i:02d}" for i in range(a, b + 1))
            continue
        if token.isdigit():
            out.add(f"S{int(token):02d}")
            continue
        token = token.upper()
        if SHOT_RE.match(token):
            out.add(token)
            continue
        raise ValueError(f"Bad --shots token: {token}")
    return out


def build_image_prompt(shot: dict[str, Any], role: str = "key") -> str:
    sid = shot["shot_id"]
    pack = shot.get("reference_pack", "city")
    description = shot.get("description_en") or shot.get("description_zh", "")
    camera = shot.get("camera", "")

    if role == "key" and sid in KEY_FRAME_OVERRIDES:
        description = KEY_FRAME_OVERRIDES[sid]
    if role == "end" and sid in END_FRAME_OVERRIDES:
        description = END_FRAME_OVERRIDES[sid]

    clauses = [
        STYLE_PROMPT,
        PACK_PROMPTS.get(pack, ""),
        "cinematic storyboard keyframe, single coherent moment, 21:9 center-safe composition inside a 16:9 source frame",
        f"shot content: {description}",
        f"camera and composition: {camera}",
    ]
    human_state = (sid == "S60" and role == "end") or sid == "S61" or (sid == "S62" and role == "end") or sid == "S64"
    if not human_state:
        clauses.append(NO_HUMANS)
    elif sid == "S60":
        clauses.append("only a partial blurred real-world researcher's hand may enter the foreground; no other human figure is visible")
    elif sid == "S61":
        clauses.append("a real-world researcher is visible only as an understated shoulder, forearm and hand at the console; no dramatic portrait pose")
    else:
        clauses.append(HUMAN_BIBLE)
    if sid in ROBOT_SHOTS:
        clauses.append(ROBOT_BIBLE)
    if sid in {"S12", "S23", "S51", "S56", "S61"}:
        clauses.append("all interface text must be blank, abstract or illegible because readable UI will be composited in post")
    if sid == "S62":
        clauses.append("match the geometry and camera position of the empty-platform first frame exactly; only the presence of commuters changes")
    if sid == "S60":
        clauses.append("the reveal must feel like one reality layer outside another, not a fantasy portal and not a computer-game HUD")
    return ". ".join(x.strip().rstrip(".") for x in clauses if x).strip() + "."


def build_negative_prompt(shot: dict[str, Any], role: str = "key") -> str:
    extra = []
    sid = shot["shot_id"]
    human_state = (sid == "S60" and role == "end") or sid == "S61" or (sid == "S62" and role == "end") or sid == "S64"
    if not human_state:
        extra += ["person", "people", "crowd", "human face", "human body"]
    if sid in ROBOT_SHOTS:
        extra += ["robot face", "glowing eyes", "android skin", "sexy robot", "military robot", "weapon"]
    if shot.get("reference_pack") == "sim":
        extra += ["matrix green code", "cyberpunk hologram", "magic portal", "fantasy cosmic nebula"]
    return NEGATIVE_PROMPT + (", " + ", ".join(extra) if extra else "")


def deterministic_seed(base_seed: int, shot_id: str, variant: int, role: str) -> int:
    raw = f"{base_seed}|{shot_id}|{variant}|{role}".encode("utf-8")
    return int.from_bytes(hashlib.blake2b(raw, digest_size=8).digest(), "big") & 0x7FFFFFFFFFFFFFFF


# -----------------------------------------------------------------------------
# ComfyUI workflow inspection and patching
# -----------------------------------------------------------------------------
def load_workflow(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if "nodes" in data and isinstance(data.get("nodes"), list):
        raise ValueError(
            "This looks like a normal ComfyUI UI workflow, not API format. "
            "Enable Developer Mode and export/save the workflow in API format."
        )
    if not isinstance(data, dict) or not data:
        raise ValueError("Workflow must be a non-empty ComfyUI API JSON object")
    return data


def node_title(node: dict[str, Any]) -> str:
    meta = node.get("_meta") or {}
    return str(meta.get("title") or "")


def find_nodes_with_input(workflow: dict[str, Any], keys: set[str]) -> list[tuple[str, dict[str, Any], set[str]]]:
    out = []
    for nid, node in workflow.items():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs") or {}
        hit = keys.intersection(inputs.keys())
        if hit:
            out.append((str(nid), node, hit))
    return out


def inspect_workflow(workflow: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for nid, node in workflow.items():
        inputs = node.get("inputs") or {}
        rows.append(
            {
                "node": str(nid),
                "class_type": node.get("class_type"),
                "title": node_title(node),
                "inputs": sorted(inputs.keys()),
            }
        )
    rows.sort(key=lambda x: int(x["node"]) if x["node"].isdigit() else 999999)
    return {"nodes": rows}


def auto_detect_node_map(workflow: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}

    # Text prompt nodes.
    text_nodes = []
    for nid, node, _ in find_nodes_with_input(workflow, {"text", "prompt"}):
        inputs = node.get("inputs") or {}
        key = "text" if "text" in inputs else "prompt"
        if isinstance(inputs.get(key), str):
            title = node_title(node).lower()
            cls = str(node.get("class_type", "")).lower()
            text_nodes.append((nid, key, title, cls, str(inputs.get(key, ""))))

    neg_candidates = [x for x in text_nodes if "negative" in x[2] or "negative" in x[4].lower()]
    pos_candidates = [x for x in text_nodes if "positive" in x[2] or "prompt" in x[2]]
    if pos_candidates:
        nid, key, *_ = pos_candidates[0]
        result["positive_prompt"] = {"node": nid, "input": key}
    elif text_nodes:
        nid, key, *_ = text_nodes[0]
        result["positive_prompt"] = {"node": nid, "input": key}
    if neg_candidates:
        nid, key, *_ = neg_candidates[0]
        result["negative_prompt"] = {"node": nid, "input": key}
    elif len(text_nodes) >= 2:
        nid, key, *_ = text_nodes[1]
        result["negative_prompt"] = {"node": nid, "input": key}

    # Seed/noise seed.
    seed_nodes = find_nodes_with_input(workflow, {"seed", "noise_seed"})
    if seed_nodes:
        nid, node, hit = seed_nodes[0]
        key = "noise_seed" if "noise_seed" in hit else "seed"
        result["seed"] = {"node": nid, "input": key}

    # Width/height should ideally live on one latent node.
    size_nodes = []
    for nid, node, _ in find_nodes_with_input(workflow, {"width", "height"}):
        inputs = node.get("inputs") or {}
        if "width" in inputs and "height" in inputs:
            size_nodes.append((nid, node))
    if size_nodes:
        nid, _ = size_nodes[0]
        result["width"] = {"node": nid, "input": "width"}
        result["height"] = {"node": nid, "input": "height"}

    # SaveImage filename prefix.
    save_candidates = []
    for nid, node, hit in find_nodes_with_input(workflow, {"filename_prefix"}):
        cls = str(node.get("class_type", ""))
        if "SaveImage" in cls or "Save" in cls:
            save_candidates.append((nid, node))
    if save_candidates:
        nid, _ = save_candidates[-1]
        result["filename_prefix"] = {"node": nid, "input": "filename_prefix"}

    return result


def load_node_map(path: Path | None, workflow: dict[str, Any]) -> dict[str, NodeTarget]:
    raw = json.loads(path.read_text(encoding="utf-8")) if path else auto_detect_node_map(workflow)
    out: dict[str, NodeTarget] = {}
    for name, target in raw.items():
        if not isinstance(target, dict) or "node" not in target or "input" not in target:
            continue
        out[name] = NodeTarget(str(target["node"]), str(target["input"]))
    required = {"positive_prompt", "seed", "width", "height", "filename_prefix"}
    missing = sorted(required.difference(out))
    if missing:
        raise ValueError(
            "Node map is missing required logical fields: " + ", ".join(missing) +
            ". Run the inspect command and edit the generated map if auto-detection is ambiguous."
        )
    return out


def patch(workflow: dict[str, Any], node_map: dict[str, NodeTarget], values: dict[str, Any]) -> dict[str, Any]:
    wf = copy.deepcopy(workflow)
    for logical, value in values.items():
        target = node_map.get(logical)
        if target is None:
            continue
        if target.node not in wf:
            raise KeyError(f"Node {target.node} for '{logical}' is not present in workflow")
        inputs = wf[target.node].setdefault("inputs", {})
        if target.input not in inputs:
            raise KeyError(f"Input '{target.input}' missing on node {target.node} for '{logical}'")
        inputs[target.input] = value
    return wf


# -----------------------------------------------------------------------------
# ComfyUI HTTP client
# -----------------------------------------------------------------------------
class ComfyClient:
    def __init__(self, server: str, timeout: float = 120.0):
        self.server = server.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

    def system_stats(self) -> dict[str, Any]:
        r = self.session.get(f"{self.server}/system_stats", timeout=10)
        r.raise_for_status()
        return r.json()

    def queue_prompt(self, workflow: dict[str, Any], client_id: str) -> str:
        r = self.session.post(
            f"{self.server}/prompt",
            json={"prompt": workflow, "client_id": client_id},
            timeout=self.timeout,
        )
        r.raise_for_status()
        data = r.json()
        if "prompt_id" not in data:
            raise RuntimeError(f"ComfyUI did not return prompt_id: {data}")
        return str(data["prompt_id"])

    def history(self, prompt_id: str) -> dict[str, Any]:
        r = self.session.get(f"{self.server}/history/{prompt_id}", timeout=30)
        r.raise_for_status()
        return r.json()

    def wait_history(self, prompt_id: str, poll: float = 1.0, max_wait: float = 3600.0) -> dict[str, Any]:
        started = time.time()
        while True:
            data = self.history(prompt_id)
            if prompt_id in data:
                return data[prompt_id]
            if time.time() - started > max_wait:
                raise TimeoutError(f"Timed out waiting for ComfyUI prompt {prompt_id}")
            time.sleep(poll)

    def download_image(self, image_info: dict[str, Any], dst: Path) -> None:
        params = {
            "filename": image_info["filename"],
            "subfolder": image_info.get("subfolder", ""),
            "type": image_info.get("type", "output"),
        }
        r = self.session.get(f"{self.server}/view", params=params, timeout=self.timeout)
        r.raise_for_status()
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(r.content)


def extract_output_images(history_record: dict[str, Any], preferred_node: str | None = None) -> list[dict[str, Any]]:
    outputs = history_record.get("outputs") or {}
    images: list[dict[str, Any]] = []
    if preferred_node is not None:
        node_output = outputs.get(str(preferred_node)) or {}
        for im in node_output.get("images") or []:
            if all(k in im for k in ("filename", "type")):
                images.append(im)
        if images:
            return images
    for node_output in outputs.values():
        for im in node_output.get("images") or []:
            if all(k in im for k in ("filename", "type")):
                images.append(im)
    return images


# -----------------------------------------------------------------------------
# Image post-processing
# -----------------------------------------------------------------------------
def crop_resize_21x9(src: Path, dst: Path, width: int = 1344, height: int = 576) -> None:
    """Center-crop to 21:9 then resize. This is post-process only; Qwen can render at its native 16:9 sweet spot."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as im:
        im = im.convert("RGB")
        sw, sh = im.size
        target_ratio = width / height
        source_ratio = sw / sh
        if source_ratio > target_ratio:
            crop_w = round(sh * target_ratio)
            left = max(0, (sw - crop_w) // 2)
            box = (left, 0, left + crop_w, sh)
        else:
            crop_h = round(sw / target_ratio)
            top = max(0, (sh - crop_h) // 2)
            box = (0, top, sw, top + crop_h)
        im = im.crop(box).resize((width, height), Image.Resampling.LANCZOS)
        im.save(dst, format="PNG", optimize=True)


# -----------------------------------------------------------------------------
# Commands
# -----------------------------------------------------------------------------
def cmd_inspect(args: argparse.Namespace) -> int:
    wf = load_workflow(args.workflow)
    report = inspect_workflow(wf)
    detected = auto_detect_node_map(wf)

    print("ComfyUI API workflow nodes:\n")
    for row in report["nodes"]:
        print(f"{row['node']:>6}  {row['class_type']:<36}  {row['title']!r}  inputs={','.join(row['inputs'])}")
    print("\nBest-effort logical node map:")
    print(json.dumps(detected, ensure_ascii=False, indent=2))
    if args.write_map:
        args.write_map.parent.mkdir(parents=True, exist_ok=True)
        args.write_map.write_text(json.dumps(detected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"\nWrote: {args.write_map}")
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    wf = load_workflow(args.workflow)
    node_map = load_node_map(args.node_map, wf)
    manifest = read_jsonl(args.manifest)
    selected = parse_shot_filter(args.shots)
    if selected is not None:
        manifest = [s for s in manifest if s.get("shot_id") in selected]
    manifest.sort(key=lambda s: shot_sort_key(s.get("shot_id", "")))

    if not manifest:
        raise SystemExit("No shots selected")

    client = ComfyClient(args.server)
    try:
        stats = client.system_stats()
        print(f"Connected to ComfyUI: {args.server}")
        devices = stats.get("devices") or []
        for dev in devices:
            name = dev.get("name") or dev.get("type") or "device"
            print(f"  device: {name}")
    except Exception as exc:
        raise SystemExit(f"Cannot reach ComfyUI at {args.server}: {exc}") from exc

    args.out_dir.mkdir(parents=True, exist_ok=True)
    args.h3_frame_dir.mkdir(parents=True, exist_ok=True)
    state_path = args.out_dir / "_generation_state.jsonl"
    total_jobs = 0
    for shot in manifest:
        total_jobs += args.variants
        if args.include_endframes and shot["shot_id"] in END_FRAME_OVERRIDES:
            total_jobs += args.variants

    print(f"Shots: {len(manifest)} | variants: {args.variants} | planned images: {total_jobs}")
    print(f"Qwen render size: {args.width}x{args.height} | H3 frame export: {args.h3_width}x{args.h3_height}")

    client_id = f"terra-storyboard-{int(time.time())}"
    finished = 0
    for shot in manifest:
        sid = shot["shot_id"]
        roles = ["key"]
        if args.include_endframes and sid in END_FRAME_OVERRIDES:
            roles.append("end")

        for role in roles:
            for variant in range(1, args.variants + 1):
                role_suffix = "" if role == "key" else "_end"
                stem = f"{sid}{role_suffix}_v{variant:02d}"
                raw_dst = args.out_dir / sid / f"{stem}.png"
                h3_dst = args.h3_frame_dir / sid / f"{stem}.png"

                if args.resume and raw_dst.exists() and h3_dst.exists():
                    finished += 1
                    print(f"[{finished:03d}/{total_jobs:03d}] SKIP {stem}")
                    continue

                seed = deterministic_seed(args.base_seed, sid, variant, role)
                positive = build_image_prompt(shot, role=role)
                negative = build_negative_prompt(shot, role=role)
                prefix = f"terra_storyboard/{sid}/{stem}"
                values = {
                    "positive_prompt": positive,
                    "negative_prompt": negative,
                    "seed": seed,
                    "width": args.width,
                    "height": args.height,
                    "filename_prefix": prefix,
                }
                job_wf = patch(wf, node_map, values)

                print(f"[{finished + 1:03d}/{total_jobs:03d}] RUN  {stem} seed={seed}")
                prompt_id = client.queue_prompt(job_wf, client_id=client_id)
                history = client.wait_history(prompt_id, poll=args.poll, max_wait=args.max_wait)
                images = extract_output_images(history, preferred_node=node_map["filename_prefix"].node)
                if not images:
                    status = history.get("status")
                    raise RuntimeError(f"No image output for {stem}; prompt_id={prompt_id}; status={status}")

                # Use the last image output: this is normally the final SaveImage node.
                client.download_image(images[-1], raw_dst)
                crop_resize_21x9(raw_dst, h3_dst, args.h3_width, args.h3_height)

                record = {
                    "shot_id": sid,
                    "role": role,
                    "variant": variant,
                    "seed": seed,
                    "prompt_id": prompt_id,
                    "raw_image": str(raw_dst),
                    "h3_frame": str(h3_dst),
                    "positive_prompt": positive,
                    "negative_prompt": negative,
                }
                with state_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
                finished += 1

    print("\nDone.")
    print(f"Raw Qwen stills : {args.out_dir}")
    print(f"H3-ready 21:9   : {args.h3_frame_dir}")
    print(f"Generation log  : {state_path}")
    return 0


def find_approved_frame(approved_dir: Path, shot_id: str, end: bool = False) -> Path | None:
    suffix = "_end" if end else ""
    direct = approved_dir / f"{shot_id}{suffix}.png"
    if direct.exists():
        return direct.resolve()
    # Also accept jpg/jpeg/webp.
    for ext in ("jpg", "jpeg", "webp"):
        p = approved_dir / f"{shot_id}{suffix}.{ext}"
        if p.exists():
            return p.resolve()
    return None


def build_h3_prompt(shot: dict[str, Any]) -> str:
    sid = shot["shot_id"]
    desc = shot.get("description_en") or shot.get("description_zh", "")
    camera = shot.get("camera", "")
    parts = [
        "Maintain the exact design, composition, lighting, color palette and anime rendering style of the provided first frame",
        "single coherent cinematic shot with physically plausible motion, no cuts, no style drift, no new text",
        f"camera movement: {camera}",
        f"scene action: {desc}",
    ]
    if sid in ROBOT_SHOTS:
        parts.append("keep the utility robot geometry and sensor design identical throughout the shot")
    if sid not in {"S60", "S61", "S62", "S64"}:
        parts.append("do not introduce humans or human silhouettes")
    if sid == "S62":
        parts.append("the change from empty station to commuters must feel instantaneous and clean, with camera and architecture perfectly locked")
    if sid == "S60":
        parts.append("continuous impossible pull-back revealing the larger external laboratory layer; preserve spatial continuity")
    return ". ".join(parts) + "."


def cmd_prompts(args: argparse.Namespace) -> int:
    shots = read_jsonl(args.manifest)
    selected = parse_shot_filter(args.shots)
    if selected is not None:
        shots = [s for s in shots if s.get("shot_id") in selected]
    shots.sort(key=lambda s: shot_sort_key(s["shot_id"]))
    rows = []
    for shot in shots:
        sid = shot["shot_id"]
        rows.append({
            **shot,
            "frame_role": "key",
            "positive_prompt": build_image_prompt(shot, "key"),
            "negative_prompt": build_negative_prompt(shot, role="key"),
            "h3_motion_prompt": build_h3_prompt(shot),
        })
        if args.include_endframes and sid in END_FRAME_OVERRIDES:
            rows.append({
                **shot,
                "frame_role": "end",
                "positive_prompt": build_image_prompt(shot, "end"),
                "negative_prompt": build_negative_prompt(shot, role="end"),
                "h3_motion_prompt": build_h3_prompt(shot),
            })
    write_jsonl(args.output, rows)
    print(f"Wrote expanded prompt manifest: {args.output} ({len(rows)} rows)")
    return 0


def cmd_h3_manifest(args: argparse.Namespace) -> int:
    shots = read_jsonl(args.manifest)
    selected = parse_shot_filter(args.shots)
    if selected is not None:
        shots = [s for s in shots if s.get("shot_id") in selected]
    shots.sort(key=lambda s: shot_sort_key(s["shot_id"]))

    jobs = []
    missing = []
    for shot in shots:
        sid = shot["shot_id"]
        first = find_approved_frame(args.approved_dir, sid, end=False)
        if first is None:
            missing.append(sid)
            if args.require_all:
                continue
            else:
                continue
        end = find_approved_frame(args.approved_dir, sid, end=True)
        needs_end = sid in END_FRAME_OVERRIDES
        mode = "first_last_frame" if end is not None else "first_frame"
        jobs.append(
            {
                "job_id": sid,
                "shot_id": sid,
                "timeline": {
                    "in": shot.get("time_in"),
                    "out": shot.get("time_out"),
                    "target_sec": shot.get("target_sec"),
                    "beats": shot.get("beats"),
                },
                "h3": {
                    "mode": mode,
                    "first_frame": str(first),
                    "last_frame": str(end) if end else None,
                    "last_frame_recommended": needs_end,
                    "source_duration_sec": shot.get("source_duration_sec", 5),
                    "fps": 24,
                    "width": args.width,
                    "height": args.height,
                    "seed": deterministic_seed(args.base_seed, sid, 1, "h3"),
                    "prompt": build_h3_prompt(shot),
                },
                "creative": {
                    "description_zh": shot.get("description_zh"),
                    "camera": shot.get("camera"),
                    "reference_pack": shot.get("reference_pack"),
                },
            }
        )

    if args.require_all and missing:
        raise SystemExit("Missing approved first frames: " + ", ".join(missing))
    write_jsonl(args.output, jobs)
    print(f"Wrote H3 manifest: {args.output} ({len(jobs)} jobs)")
    if missing:
        print("Missing approved first frames (not exported): " + ", ".join(missing))
    print("Expected approved naming: S01.png ... S64.png; optional FLF end frames: S60_end.png, S62_end.png, etc.")
    return 0


def make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="TERRA storyboard generator for local Qwen-Image + H3 handoff")
    sub = p.add_subparsers(dest="command", required=True)

    pi = sub.add_parser("inspect", help="Inspect ComfyUI API workflow and auto-detect node mapping")
    pi.add_argument("--workflow", type=Path, required=True)
    pi.add_argument("--write-map", type=Path, default=None)
    pi.set_defaults(func=cmd_inspect)

    pg = sub.add_parser("generate", help="Generate storyboard stills through a local ComfyUI Qwen-Image workflow")
    pg.add_argument("--workflow", type=Path, required=True, help="ComfyUI workflow exported in API format")
    pg.add_argument("--node-map", type=Path, default=None, help="Logical node map JSON; auto-detect if omitted")
    pg.add_argument("--manifest", type=Path, default=Path("terra_storyboard_manifest.jsonl"))
    pg.add_argument("--server", default="http://127.0.0.1:8188")
    pg.add_argument("--out-dir", type=Path, default=Path("generated_storyboards_qwen"))
    pg.add_argument("--h3-frame-dir", type=Path, default=Path("generated_storyboards_h3_frames"))
    pg.add_argument("--variants", type=int, default=4)
    pg.add_argument("--shots", default=None, help="e.g. S01-S10,S59,S60 or 1-10,59,60")
    pg.add_argument("--include-endframes", action="store_true", help="Also generate terminal stills for FLF-critical shots")
    pg.add_argument("--width", type=int, default=1664, help="Qwen source width; 1664x928 is a strong native 16:9 size")
    pg.add_argument("--height", type=int, default=928)
    pg.add_argument("--h3-width", type=int, default=1344)
    pg.add_argument("--h3-height", type=int, default=576)
    pg.add_argument("--base-seed", type=int, default=260930)
    pg.add_argument("--poll", type=float, default=1.0)
    pg.add_argument("--max-wait", type=float, default=3600.0)
    pg.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    pg.set_defaults(func=cmd_generate)

    pp = sub.add_parser("prompts", help="Export fully expanded Qwen image prompts + H3 motion prompts for review/editing")
    pp.add_argument("--manifest", type=Path, default=Path("terra_storyboard_manifest.jsonl"))
    pp.add_argument("--output", type=Path, default=Path("terra_storyboard_prompts.jsonl"))
    pp.add_argument("--shots", default=None)
    pp.add_argument("--include-endframes", action="store_true")
    pp.set_defaults(func=cmd_prompts)

    ph = sub.add_parser("h3-manifest", help="Build one-click-H3 handoff manifest from approved storyboard frames")
    ph.add_argument("--manifest", type=Path, default=Path("terra_storyboard_manifest.jsonl"))
    ph.add_argument("--approved-dir", type=Path, default=Path("approved"))
    ph.add_argument("--output", type=Path, default=Path("terra_h3_from_approved.jsonl"))
    ph.add_argument("--shots", default=None)
    ph.add_argument("--width", type=int, default=1344)
    ph.add_argument("--height", type=int, default=576)
    ph.add_argument("--base-seed", type=int, default=260930)
    ph.add_argument("--require-all", action="store_true")
    ph.set_defaults(func=cmd_h3_manifest)

    return p


def main() -> int:
    parser = make_parser()
    args = parser.parse_args()
    if hasattr(args, "variants") and args.variants < 1:
        parser.error("--variants must be >= 1")
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())