# Anchor-driven tracking

Select **Anchor expansion + discovery** under Output, save settings, then Analyze
and render. Existing single/dual modes remain available. Use a separate project
output directory when comparing algorithms; saved manual boxes live in that
output directory's corrections.json.

## Workflow

1. Seed authoritative anchors from manual boxes and the initial user reference.
   Manual absence is preserved and blocks a propagation branch at that frame.
2. Expand in both directions. Optical flow follows image features through every
   intervening source frame. At analysis sample positions, validate a relaxed crop
   or run fresh localization inside that region.
3. Promote only freshly localized, verified, complete boxes meeting the anchor
   threshold. Identity scores on propagated/relaxed crops do not make new anchors.
4. When the propagation queue empties, independently scan unresolved positions at
   the discovery FPS. A failed local search does not count as a full-frame scan.
   New high-confidence discoveries restart expansion immediately.
5. Stop when no productive branches or eligible discovery positions remain. Save
   unresolved positions for review; render the resolved observations normally.

## Settings

`tracking_mode: "anchor"` enables this mode. Output exposes the tracking mode,
**High-confidence anchor threshold (%)** (85% by default), discovery FPS (2),
analysis FPS, and the separate acceptance threshold. The anchor threshold must be
at least the acceptance threshold. These are reliability scores, not probabilities.

Additional `anchor_tracking` JSON settings:

| Field | Default | Meaning |
|---|---:|---|
| `padding_fraction` | 0.15 | Per-side fraction of predicted box dimensions |
| `min_padding_px` | 8 | Minimum per-side padding in source pixels |
| `max_dimension_ratio` | 1.5 | Relocalize if search dimension exceeds last localized dimension by this factor |
| `max_area_ratio` | 2 | Relocalize if search area exceeds last localized area by this factor |
| `max_propagation_attempts` | 4 | Maximum proposals at each sample position |
| `start_time`, `end_time` | Full video | Optional analysis interval, in source seconds, for experiments |

Relaxation includes accumulated optical-flow uncertainty. When flow fails, the
search region expands further and requires localization, rather than accepting a
stationary box. Validation alone does not reset uncertainty or the last localized
box size. There is no fixed age trigger. Analysis and discovery schedules are
combined with manual-frame positions. Coverage counts refer to these sample
positions, not claims that Qwen examined every source frame.

## Modules and evidence

- `visual_tracking.py`: CPU Lucas–Kanade flow, forward/backward point checks,
  RANSAC partial-affine motion, feature survival and uncertainty. Carries corners
  through transforms to avoid repeated bounding-rectangle inflation.
- `tracking_search.py`: raw/leveled crop validation and local/full-frame detection.
  Crop-local detections inverse-map through crop translation and leveling rotation.
- `tracking_evidence.py`: preserve manual labels, prefer localized evidence when
  proposals agree; conflicts remain uncertain pending independent discovery.
  Agreement does not increase scores.
- `analysis_scheduler.py`: bounded work queue, coverage and anchor lineage.
- `anchor_tracking.py`: configuration validation, initial reference seeding,
  checkpoint fingerprints, existing renderer/UI output formats.

`anchor_checkpoint.json` preserves pending work, proposals, coverage, and events.
Its fingerprint includes source metadata, model, configuration, manual labels and
algorithm versions. A matching restart resumes pending tasks; changed inputs
start a new scheduler state while request caches remain separately keyed.
Each proposal records origin anchor, parent frame, direction, motion quality,
uncertainty, relaxed region, localization status and candidate evidence.
`anchor_summary.json` and `analysis_progress.json` expose progress in the UI.

Malformed model rectangles are rejected evidence; they do not stop discovery.
Service/verification errors halt at a resumable checkpoint. Completed failed
full-frame searches are not repeated without changed inputs. Manual labels always
win. Repeated descendants of the same anchor are not independent confirmations.

## Limits and verification

Optical flow may follow background features in a loose box or fail on textureless,
very small objects. Motion scores do not prove identity. Independent crop
verification and localization remain necessary. The implementation does not yet
use a learned appearance tracker or GPU optical flow. A valid relaxed crop proves
identity somewhere inside it, not precise boundaries; propagated boxes are marked
as estimates and cannot seed independent anchors.

Tests cover synthetic translation in both directions, featureless failure,
relaxation bounds, local-to-source coordinates, conflicting proposals, authoritative
absence, discovery after stalled expansion, bounded/resumable work, initial
reference anchors and configurable thresholds. Use short isolated video intervals
before full-video experiments.

## Comparison overlays and score labels

The comparison video's original panel draws the saved rendered track as a green
dashed rectangle, alongside cyan/raw and orange/leveled candidates. Green uses
source-pixel coordinates from tracks.json and disappears when the frame has no
rendered box; unsaved or pending corrections do not alter that overlay. Dashes
keep overlapping candidate outlines visible. Interpolated/held playback boxes are
explicitly labeled rather than presented as new optical-flow detections.

Each Raw/Leveled analysis section names its box method (optical flow with crop
validation, crop-local Qwen localization, full-frame Qwen detection, or human
label) and shows text-comparison identity confidence separately from optical
motion quality and detector self-confidence. Older anchor outputs can infer the
method from the paired selection record. New localizations store the method on
each candidate. Missing scores remain unavailable, not fabricated from detector
confidence.

### Exact-frame analysis display

The confidence badge names the displayed frame's evidence source: human label,
independent raw/leveled analysis, or tracking with raw/leveled crop validation.
Interpolated/held playback tracks are labeled separately and do not inherit a
neighboring sample's confidence. Their per-frame identity score is unavailable.
The text field includes independent detection, crop verification, direction
comparisons and visual-level evidence only when recorded at this exact frame.
Unsampled frames retain their own saved render box, interpolation provenance,
render parameters and telemetry. Historical outputs do not persist every internal
optical-flow update; the UI does not invent those measurements or describe
interpolation as optical flow. No reanalysis is required for this display change.

### Human polygons and candidate approval

The focus page displays the raw source frame and a leveled/zoomed preview side by
side. The preview is generated from the exact source frame using the saved render
transform; before a render is available it uses the full leveled frame. Drag a
rectangle on either image, then choose **Save target box**. A processed rectangle
maps back to a polygon in original-video pixel coordinates. Source bounds clip
selections; a selection entirely outside source content is rejected. The blurred
extension does not supply additional source pixels.

Both views share **Approve Cyan (raw path)** and **Approve Orange (leveled path)**
inside Frame Analysis. Approval is enabled whenever that path has a displayed box, including zero-confidence,
interpolated, and held estimates. The exact displayed outline is saved for the
currently displayed frame; approval provenance records the estimate type. Approval saves the displayed
outline: cyan's source polygon, or orange's enclosing source rectangle. It does
not replace that outline with an unseen detector-space box.

Drawing and approval both update the existing project's `corrections.json`.
Records preserve the canonical `source_polygon_px`, its enclosing `bbox` for
existing framing code, `processed_polygon_px`, and the preview transform.
`approved_path` records which candidate the user approved. Original model results
remain available. A human label has 100% confidence, overrides automatic results,
skips detection at that frame, and serves as a bidirectional anchor and reference
under the existing context limits. Neighboring frames still need their own
verification. Polygon masks exclude unselected corners from human reference crops
and optical-flow feature initialization.

Saving does not launch processing. Reanalyze to propagate the new anchor, or render
with saved corrections to apply labels without Qwen analysis. Labels can be
replaced by another selection/approval or cleared by marking the target absent.
Editing is disabled while a managed processing job is running.
