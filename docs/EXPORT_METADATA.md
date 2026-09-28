# Export metadata and provenance

New renders preserve available recording date/time and camera make/model tags in
`focused.mp4` and `comparison.mp4`. The exporter takes container tags first, then
falls back to the primary video stream. Supported tags include `creation_time`,
`date`, `make`, `model`, `camera_make`, `camera_model`, and the corresponding Apple
QuickTime creation-date/make/model keys.

Source encoder/software identification is retained under `source_encoder`,
`source_software`, or `source_com_apple_quicktime_software`. The normal encoder tag
continues to identify the software that actually encoded the processed video.
Custom tags use MP4 metadata keys; visibility depends on the viewer/editor.

Original orientation, timecode, chapters, GPS and camera telemetry are not copied
as output-video tags/tracks. They may describe the original camera view rather than
the rotated/zoomed view. Audio streams continue to be copied without re-encoding.
Video remains H.264/yuv420p at the configured dimensions and nominal source FPS;
this change does not preserve HDR or variable frame timestamps.

Each focused render also writes these files beside the video:

| File | Contents |
| --- | --- |
| `focused.metadata.json` | Source filename, size/mtime, exposed source container/stream tags, timing information, output dimensions, preserved tags, transform convention and links to related files |
| `source_telemetry.json` | Original data-stream metadata and packet index: stream number, byte offset/size, PTS, DTS, duration and time base |
| `source_telemetry.bin` | Original data-track packet payloads, copied verbatim without interpreting device-specific telemetry |
| `tracks.json` | Per-frame source box, crop center/height, applied rotation, zoom and tracking details |
| `gyro.json` (when available) | Extracted source attitude used by the leveling system |

The telemetry index explicitly identifies its coordinate space as the original
camera/source video. A consumer must not treat those attitude measurements as the
orientation of the leveled output. The packet archive also retains unsupported
camera data and timecode tracks; files with no data streams produce an empty index
and binary archive. Reading the packet archive adds a source-file pass at export.

Keep these files together when moving the processed video. Keep the original video
as the authoritative source: this archive preserves exposed tags and data packets,
not all proprietary container atoms or original image/audio encoding information.
The source file is never modified. These changes apply to subsequent renders;
existing outputs and already-running processes are not automatically migrated.

Validation includes a real MP4 encode/remux with recording/camera tags and a source
timecode track. Tests verify the output tags and exclusion of source timecode, plus
byte-for-byte equality and timestamps for archived data packets.
