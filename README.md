# Action Reframe

The [architecture and next steps](docs/ARCHITECTURE_ROADMAP.md) define the agreed four core components, video-level scheduling, folder-level workflow, and separate feature-building and optimization tracks.

See [current approach](docs/CURRENT_APPROACH.md) for the implemented tracking/review behavior, agreed tradeoffs, and the boundary between current functionality and planned work.

Offline subject tracking, camera leveling, smooth reframing, and review for action footage.

The current prototype supports frame analysis, backward recovery, rendering, synchronized comparison, and corrections. The proposed three-part workflow—design plans, validate offline trials, then process approved videos—is described in [the design](docs/PROJECT_DESIGN.md) and [implementation plan](docs/PROJECT_PLAN.md).

Open `/lookout` for daily UX and operational improvement suggestions. See the [Lookout operating guide](docs/LOOKOUT.md) for collection controls, service setup and measurement limits.

The [Lookout project plan](docs/LOOKOUT_PLAN.md) describes lightweight UX and operational telemetry, with daily suggestions focused on reducing human attention: up to three UX improvements and three operational improvements, without scores.

See [performance, reliability and operations improvements](docs/PERFORMANCE_RELIABILITY_OPERATIONS.md) for the current baseline, GPU acceleration plan, service deployment gaps, and verifiable delivery steps.

## Folder batches

Open `/library` on the review server to prepare video projects, review/approve
identity descriptions, queue ready videos, and start serial overnight processing.
Jobs persist independently of the UI; each run has isolated outputs, progress,
retry controls and review links. See [batch workflow](docs/BATCH_WORKFLOW.md) for
the exact pause/restart semantics and current limits.

## Layout

```text
docs/             Design, implementation plan, decisions, prototype guide
src/              Python processing and review server
src/web/          Review/comparison pages and diagnostics
tests/            Unit and synthetic-video integration tests
configs/          Generic defaults and optional sailboat examples
scripts/          Bash launchers and test runner
data/             Default local workspace; contents excluded from Git
requirements.in   Dependency constraints
requirements.txt  Locked dependencies
```

## Setup

Use Python 3.12 and a dedicated virtual environment. No Conda environment, GPU, private video, model server, system FFmpeg, or machine-specific directory is required to run the tests and review interface. Qwen analysis requires a separately configured compatible vision endpoint; it may run on another machine.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
./scripts/test.sh
./scripts/run_review.sh --workspace ./data --port 8765
```

Open <http://127.0.0.1:8765/>. An empty workspace displays setup guidance. Add a video to the workspace, reload, select a frame and subject rectangle, and create a project. No example project is required. Existing workspace projects are discovered automatically; `?config=project_name.json` selects one explicitly.

The scripts use the repository's `.venv/bin/python`. Set `ACTION_REFRAME_PYTHON` to another prepared Python executable if needed. They preserve the caller's working directory, so relative arguments are relative to where you invoke the script.

On Windows, use the Python entry points directly with `.venv\Scripts\python.exe`. For example, `python src/review_server.py --workspace data`. The Bash launchers are optional. Python dependencies and codecs must be available for the chosen OS/architecture; Windows and macOS have not yet been validated.

## Configuration

| Setting | Default | Override |
|---|---|---|
| Review workspace | Repository `data/` | `--workspace PATH`, then `LONGVIDEO_WORKSPACE` environment variable |
| Review port | 8765, loopback only | `--port NUMBER` |
| Qwen endpoint | `http://127.0.0.1:8000/v1` | `QWEN_API_URL`, or project `api_url` |
| Analysis cadence | 10 FPS | UI, project `analysis_fps`, or CLI `--analysis-fps` |
| Processing defaults | `configs/defaults.json` | Individual project fields |

Environment variables are inherited by analysis workers. `QWEN_API_URL` takes precedence over the project's endpoint. The current client expects the model-list, chat-completions, and vLLM-compatible `/tokenize` endpoints, accepts image inputs, and has no API-key authentication integration yet. Arbitrary hosted providers are not interchangeable without an adapter.

The UI creates configuration files at the workspace root with paths relative to that workspace. CLI video/output paths are relative to the configuration file, regardless of the current working directory. The CLI can use absolute paths as well. Generated run records may contain resolved local paths; caches are runtime data and are not promised to be relocatable. Share source configs and references, then regenerate runtime artifacts after relocating them.

```bash
./scripts/run_reframe.sh /path/to/workspace/project_name.json --stage all
./scripts/run_reframe.sh /path/to/workspace/project_name.json --analysis-fps 5 --output-dir ./data/experiment_fps5
```

The sailboat configs are optional illustrative selections, not supplied test data. They expect user-provided `data/videos/example.mp4`; adjust the reference time, box, and description for your footage. The review interface instead lists videos directly inside its configured workspace. See [data setup](data/README.md) and [prototype behavior](docs/PROTOTYPE.md).

## Development and portability

```bash
./scripts/test.sh
```

Tests generate tiny synthetic media in temporary directories and do not call Qwen. GitHub Actions runs them with Python 3.12 on Ubuntu. Static HTML/JavaScript is shipped in `src/web/`, independently of the video workspace. FFmpeg comes from `imageio-ffmpeg`; PyAV reads metadata.

Keep media, outputs, environments, and credentials out of Git. No workspace symlink is needed or automatically selected. An existing local symlink can be used explicitly through `--workspace data/workspace`. Avoid simultaneous jobs writing to the same output directory; durable multi-worker coordination is future work.

Follow acceptance checks in `docs/PROJECT_PLAN.md`. Verify changed UI behavior as well as tests. The repository does not yet declare an open-source license; choose one before offering it for public reuse.

## Gyro-final leveling with independent Qwen comparison

For inspected DJI Osmo Action 6 (`dvtm_ac206.proto`) telemetry, set these fields in your project:

```json
{
  "leveling_source": "gyro",
  "level_divergence_degrees": 5,
  "level_workers": 2
}
```

`--stage all` performs tracking, independent visual leveling, and rendering. To reuse completed tracking in an existing output directory:

```bash
./scripts/run_reframe.sh /path/to/project.json --stage level-render
```

Use `--stage level --single 30` for one visual check, or `--stage level` for the configured sample grid. Analysis rate comes from that run's saved `meta.json`; change FPS by creating a new analysis run. `--stage render` uses saved visual observations and extracts telemetry again.

The independent leveling request sees only the current original image and its measured line candidates. It receives no previous leveling answers and no telemetry angles. Qwen chooses visual evidence; the application computes the line angle, checks contradictory direction claims, and lowers absolute-orientation confidence for shorelines. This addresses repeated historical estimates without claiming every visual measurement is correct.

In gyro mode, the final applied rotation is the per-frame DJI fused-attitude roll. Qwen estimates cannot override it. Manual roll corrections are disabled for that project. Missing, invalid, unsupported, or misaligned telemetry stops gyro rendering rather than silently substituting Qwen. The current axis mapping has visual corroboration but is still explicitly marked provisional; other cameras require their own validated adapters. Gyro-free projects retain `leveling_source: "visual"` by default.

The comparison UI shows final gyro roll, independent Qwen roll, their signed difference, confidence, sample-frame offset, and evidence. Differences greater than the configured threshold get a red badge and separate jump-to-interval buttons. Comparison at intervening frames uses the nearest visual sample, explicitly labeled. A missing visual estimate is marked unavailable, not agreement. `level_summary.json` warns if the new visual pass repeats one angle throughout.

Artifacts include `gyro.json`, `level_observations.json`, `level_comparison.json`, `level_summary.json`, `level_progress.json`, and content-keyed `level_cache/`. All remain in the ignored output workspace. Tracking and independent leveling observations are stored separately; the UI labels legacy tracking-pass level fields to avoid confusing them with the final rotation.
