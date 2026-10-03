"""Project integration for standalone visual-leveling annotations."""

import hashlib
import json
import math
from pathlib import Path
from functools import lru_cache

import av
import numpy as np


SCHEMA = "video-leveling-annotations/v1"


def source_identity(path):
    path = Path(path)
    stat = path.stat()
    return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


@lru_cache(maxsize=128)
def _gyro_available(path, size, mtime_ns):
    try:
        with av.open(path) as container:
            stream=container.streams.video[0]
            fps=float(stream.average_rate)
            duration=float(stream.duration*stream.time_base) if stream.duration else container.duration/1e6
            frames=stream.frames or round(duration*fps)
        from leveling import extract_gyro
        extract_gyro(path,dict(frames=frames,fps=fps))
        return True
    except (av.error.FFmpegError, OSError, ValueError, KeyError, StopIteration):
        return False


def gyro_available(video):
    """True only when supported attitude covers and aligns with every video frame."""
    video=Path(video).resolve();stat=video.stat()
    return _gyro_available(str(video),stat.st_size,stat.st_mtime_ns)


def manifest_path(root, config):
    value = config.get("leveling_annotation")
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = Path(root) / path
    path = path.resolve()
    root = Path(root).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Leveling annotation must be inside the workspace")
    if path.is_dir():
        path = path / "leveling.json"
    return path


def validate_manifest(root, config, require_complete=False):
    path = manifest_path(root, config)
    if path is None or not path.is_file():
        raise ValueError("Leveling annotation is not available")
    manifest = json.loads(path.read_text())
    if manifest.get("schema") != SCHEMA:
        raise ValueError("Unsupported leveling annotation schema")
    video = Path(config["video"])
    if not video.is_absolute():
        video = Path(root) / video
    identity = source_identity(video)
    recorded = manifest.get("source", {})
    if any(recorded.get(key) != value for key, value in identity.items()):
        raise ValueError("Leveling annotation belongs to a different version of the source video")
    if require_complete and not manifest.get("shards"):
        raise ValueError("Leveling annotation has no exported shards")
    return path, manifest


def annotation_status(root, config):
    video = Path(config["video"])
    if not video.is_absolute():
        video = Path(root) / video
    has_gyro = gyro_available(video)
    try:
        path, manifest = validate_manifest(root, config, require_complete=True)
        counts = manifest.get("counts", {})
        total = int(manifest.get("metadata", {}).get("frames", 0))
        estimated = int(counts.get("estimated", 0))
        return {
            "required": not has_gyro,
            "gyro_available": has_gyro,
            "status": "Done",
            "result_status": manifest.get("status", "complete"),
            "annotation": str(path.relative_to(Path(root).resolve())),
            "estimated": estimated,
            "unknown": int(counts.get("unknown", max(0, total - estimated))),
            "needs_review": int(counts.get("needs_review", 0)),
            "frames": total,
            "coverage": estimated / total if total else 0,
            "scene_hint": config.get("leveling_scene_hint", ""),
        }
    except (ValueError, OSError, json.JSONDecodeError):
        return {
            "required": not has_gyro,
            "gyro_available": has_gyro,
            "status": "Not required" if has_gyro else "Not queued",
            "annotation": None,
            "estimated": 0,
            "unknown": 0,
            "needs_review": 0,
            "frames": 0,
            "coverage": 0,
            "scene_hint": config.get("leveling_scene_hint", ""),
        }


def _verified_shard(folder, shard):
    path = (folder / shard["path"]).resolve()
    if not path.is_relative_to(folder.resolve()):
        raise ValueError("Invalid leveling shard path")
    if hashlib.sha256(path.read_bytes()).hexdigest() != shard["sha256"]:
        raise ValueError(f"Leveling shard checksum mismatch: {path.name}")
    return path


def load_rows(root, config):
    manifest_path_, manifest = validate_manifest(root, config, require_complete=True)
    folder = manifest_path_.parent
    rows = []
    for shard in manifest["shards"]:
        path = _verified_shard(folder, shard)
        with path.open() as handle:
            rows.extend(json.loads(line) for line in handle if line.strip())
    frames = int(manifest["metadata"]["frames"])
    if len(rows) != frames or any(row.get("frame") != index for index, row in enumerate(rows)):
        raise ValueError("Leveling shards do not form one complete source-frame timeline")
    return manifest, rows


def row_at(root, config, frame):
    path, manifest = validate_manifest(root, config, require_complete=True)
    if not 0 <= frame < int(manifest["metadata"]["frames"]):
        raise ValueError("Frame is outside leveling annotation")
    for shard in manifest["shards"]:
        if int(shard["start_frame"]) <= frame < int(shard["end_frame_exclusive"]):
            with _verified_shard(path.parent, shard).open() as handle:
                for line in handle:
                    row = json.loads(line)
                    if row["frame"] == frame:
                        return row
            break
    raise ValueError("Frame is missing from leveling annotation")


def rows_at(root, config, frames):
    """Read selected annotation rows while opening each required shard once."""
    path, manifest = validate_manifest(root, config, require_complete=True)
    requested = sorted(set(int(frame) for frame in frames))
    total = int(manifest["metadata"]["frames"])
    if requested and (requested[0] < 0 or requested[-1] >= total):
        raise ValueError("Frame is outside leveling annotation")
    found = {}
    for shard in manifest["shards"]:
        start, end = int(shard["start_frame"]), int(shard["end_frame_exclusive"])
        wanted = {frame for frame in requested if start <= frame < end}
        if not wanted:continue
        with _verified_shard(path.parent, shard).open() as handle:
            for line in handle:
                row = json.loads(line)
                if row["frame"] in wanted:found[row["frame"]] = row
        if len(found) == len(requested):break
    if len(found) != len(requested):raise ValueError("Frame is missing from leveling annotation")
    return [found[int(frame)] for frame in frames]


def correction_series(root, config, frames=None):
    manifest, rows = load_rows(root, config)
    total = int(manifest["metadata"]["frames"])
    if frames is not None and total != frames:
        raise ValueError("Leveling annotation frame count does not match analysis video")
    raw = np.array([
        np.nan if row.get("correction_degrees_ccw") is None else float(row["correction_degrees_ccw"])
        for row in rows
    ])
    known = np.isfinite(raw)
    if not known.any():
        raise ValueError("Leveling annotation contains no supported angles")
    indices = np.arange(total)
    filled = np.interp(indices, indices[known], raw[known])
    quality = np.array([float(row.get("evidence_quality", 0)) for row in rows])
    return filled, known, quality, rows


def as_tracking_attitude(root, config, frames=None):
    angles, known, quality, rows = correction_series(root, config, frames)
    return {
        "source": "standalone visual leveling annotation",
        "schema": SCHEMA,
        "frames": [
            {
                "frame": index,
                "time": rows[index]["time_seconds"],
                "roll": float(angles[index]),
                "level_supported": bool(known[index]),
                "evidence_quality": float(quality[index]),
                "flags": rows[index].get("flags", []),
            }
            for index in range(len(rows))
        ],
    }


def tracking_attitude(config, meta):
    """Return the configured correction timeline in the gyro-compatible shape."""
    source = config.get("leveling_source", "gyro")
    if source == "gyro":
        from leveling import extract_gyro
        return extract_gyro(config["video"], meta)
    if source == "annotation":
        root = Path(config.get("_workspace_root") or Path(config["video"]).resolve().parent)
        return as_tracking_attitude(root, config, meta.get("frames"))
    raise ValueError("Tracking requires gyro or a completed standalone leveling annotation")
