"""Authoritative human boxes, stored in source pixels and used in traversal history."""
import json
from pathlib import Path


def manual_observations(config, meta):
    path = Path(config['output_dir']) / 'corrections.json'
    corrections = json.loads(path.read_text()) if path.exists() else {}
    rows = {}
    for key, correction in corrections.items():
        index = int(key)
        if 'bbox' not in correction or not 0 <= index < meta.get('frames', float('inf')):
            continue
        box = correction['bbox']
        normalized = None if box is None else [v / (meta['height'] if j % 2 else meta['width']) * 1000 for j, v in enumerate(box)]
        rows[index] = dict(frame=index, time=index / meta['fps'], bbox=normalized,
                           confidence=1 if box is not None else 0,
                           confidence_source='human', manual=True, analysis_source='manual',
                           visibility='visible' if box is not None else 'absent',
                           direction='manual', note='Human-confirmed target box' if box is not None else 'Human-confirmed absence',
                           shoreline=None, level_confidence=0)
    return rows
