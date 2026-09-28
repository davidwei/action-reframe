"""Source provenance kept separate from the orientation of rendered pixels."""
import json
from pathlib import Path

import av


IDENTITY_TAGS = {
    'creation_time', 'date', 'make', 'model', 'camera_make', 'camera_model',
    'com.apple.quicktime.creationdate', 'com.apple.quicktime.make',
    'com.apple.quicktime.model',
}


def inspect_source(video):
    with av.open(str(video)) as container:
        streams = []
        for stream in container.streams:
            streams.append({'index': stream.index, 'type': stream.type,
                            'tags': dict(stream.metadata),
                            'time_base': str(stream.time_base),
                            'start_time': stream.start_time,
                            'duration': stream.duration,
                            'codec': stream.codec_context.name if stream.codec_context else None})
        return {'tags': dict(container.metadata), 'streams': streams}


def export_tags(source):
    # Container tags take precedence over the primary video stream.
    primary = next((s['tags'] for s in source['streams'] if s['type'] == 'video'), {})
    tags = dict(primary, **source['tags'])
    result = {k: v for k, v in tags.items() if k.lower() in IDENTITY_TAGS}
    # Keep source camera/software identification without mislabelling the new encoder.
    for key in ('encoder', 'software', 'com.apple.quicktime.software'):
        if tags.get(key):
            result['source_' + key.replace('.', '_')] = tags[key]
    return result


def ffmpeg_metadata_args(video):
    args = ['-map_metadata', '-1', '-map_chapters', '-1']
    for key, value in export_tags(inspect_source(video)).items():
        args.extend(['-metadata', f'{key}={value}'])
    return args


def write_json(path, value):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, indent=2, allow_nan=False))
    temp.replace(path)


def write_sidecar(config, filename='focused.mp4'):
    """Archive original data packets verbatim; do not attach them to transformed video."""
    source_path = Path(config['video'])
    out = Path(config['output_dir'])
    source = inspect_source(source_path)
    # Binary payload avoids base64 expansion for long recordings. JSON records
    # packet boundaries/timestamps and original stream metadata, not interpreted IMU.
    binary = out/'source_telemetry.bin'
    temp = binary.with_suffix('.bin.tmp')
    packets = []
    with av.open(str(source_path)) as container, temp.open('wb') as archive:
        streams = [s for s in container.streams if s.type == 'data']
        if streams:
            for packet in container.demux(streams):
                if not packet.size:
                    continue
                data = bytes(packet)
                packets.append({'stream_index': packet.stream.index,
                                'offset': archive.tell(), 'size': len(data),
                                'pts': packet.pts, 'dts': packet.dts,
                                'duration': packet.duration, 'time_base': str(packet.time_base)})
                archive.write(data)
    temp.replace(binary)
    write_json(out/'source_telemetry.json', {
        'coordinate_space': 'original camera/source video, NOT leveled output',
        'payload_file': binary.name, 'packets': packets,
        'streams': [s for s in source['streams'] if s['type'] == 'data']})
    stat = source_path.stat()
    write_json(out/filename.replace('.mp4', '.metadata.json'), {
        'schema_version': 1, 'output_file': filename,
        'source': {'filename': source_path.name, 'size_bytes': stat.st_size,
                   'mtime_ns': stat.st_mtime_ns, **source},
        'preserved_output_tags': export_tags(source),
        'original_telemetry': 'source_telemetry.json',
        'extracted_source_attitude': 'gyro.json' if (out/'gyro.json').exists() else None,
        'frame_transforms': 'tracks.json',
        'transform_convention': 'tracks frame i corresponds to decoded source frame i; '
            'time=i/source_fps. Rotate about center by roll degrees using OpenCV, '
            'scale=output_height/crop_height, then translate center to output center. '
            'Feathered background is synthesized; source attitude is not output attitude.',
        'output_dimensions': [config['output_width'], config['output_height']],
        'timing': 'Constant source nominal FPS; original variable frame timestamps are not preserved.',
        'limitations': 'Data packet payloads/timestamps and exposed tags are archived; '
            'this is not a byte-for-byte archive of all MP4 atoms. Retain the original video.'})
