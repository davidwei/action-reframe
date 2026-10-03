# Action Reframe

Offline subject tracking, camera leveling, smooth reframing, and review for action footage.

Start with the [documentation guide](docs/README.md), [current approach](docs/CURRENT_APPROACH.md), and [video processing paths](docs/TWO_PATH_TRACKING.md). The [architecture roadmap](docs/ARCHITECTURE_ROADMAP.md) separates built features from future work. The library supports approved inputs and offline analysis/rerender queues; the broader planner/trial/production experience remains planned.

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
| Crop Verification FPS | 10 FPS | UI, project `analysis_fps`, or CLI `--analysis-fps` |
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

In gyro mode, the final applied rotation is the per-frame DJI fused-attitude roll. Qwen estimates cannot override it. Manual roll corrections are disabled for that project. Missing, invalid, unsupported, or misaligned telemetry stops gyro rendering rather than silently substituting Qwen. The current axis mapping has visual corroboration but is still explicitly marked provisional; other cameras require their own validated adapters. New projects default to gyro leveling and independent raw/leveled optical tracking (`tracking_mode: "anchor"`). This mode requires supported gyro telemetry. Legacy single-path visual processing must be explicitly selected for gyro-free projects.

The comparison UI shows final gyro roll, independent Qwen roll, their signed difference, confidence, sample-frame offset, and evidence. Differences greater than the configured threshold get a red badge and separate jump-to-interval buttons. Comparison at intervening frames uses the nearest visual sample, explicitly labeled. A missing visual estimate is marked unavailable, not agreement. `level_summary.json` warns if the new visual pass repeats one angle throughout.

Artifacts include `gyro.json`, `level_observations.json`, `level_comparison.json`, `level_summary.json`, `level_progress.json`, and content-keyed `level_cache/`. All remain in the ignored output workspace. Tracking and independent leveling observations are stored separately; the UI labels legacy tracking-pass level fields to avoid confusing them with the final rotation.

New UI projects and minimal configuration files share `configs/defaults.json`: 10 FPS crop verification, at most 2 FPS independent recovery per path, 50% acceptance and 85% priority-anchor thresholds, gyro rotation, and no analysis zoom. Example configs inherit those defaults rather than embedding older context/tracking settings. Existing projects and queued snapshots keep their saved overrides.

## Review and model startup after reboot (Linux)

If a local model already has a systemd user service, install the review service
with that dependency. Substitute your workspace, port and model unit:

```bash
.venv/bin/python scripts/install_review_service.py \
  --workspace /path/to/videos --port 8766 \
  --model-service vllm-vl.service \
  --expected-model /path/to/models/Qwen3-VL-32B-FP8 --install
```

Without `--install`, this prints the generated unit for review. It does not install
vLLM or choose/download model weights. The existing model unit owns those settings.
The review unit starts the model service and waits up to ten minutes for a nonempty
`/v1/models` response before starting the UI. Its first model ID must exactly match
`--expected-model` (use the ID returned by your intended server, including any
path or served-model alias). A mismatch refuses startup and logs expected and
actual IDs; simply having the expected model elsewhere in the list is insufficient
because analysis clients select the first model. This checks the server-reported
identity at startup, not the weights themselves or subsequent endpoint changes. `--api-url` overrides the endpoint and
sets `QWEN_API_URL` for the UI and its workers. Startup failures appear in the journal;
systemd retries failed startup. Starting the UI does not automatically resume jobs.

If the GPUs are assigned to another workload, install the review UI in CPU-only mode:

```bash
.venv/bin/python scripts/install_review_service.py \
  --workspace /path/to/videos --port 8766 --model-optional --install
```

This keeps frame review, cached preview playback, labels, corrections, and rerender
controls available without starting or validating vLLM. Model-backed description and
analysis actions still require the configured vision model; the queue service retains
its strict model-readiness check.

```bash
systemctl --user start action-reframe-review.service
systemctl --user status action-reframe-review.service vllm-vl.service
journalctl --user -u action-reframe-review.service -u vllm-vl.service -f
```

The enabled user service starts when the user's systemd manager starts (normally
at login; boot without login requires user lingering). Restarting this UI service
leaves detached queue workers running. The manual `run_review.sh` launcher remains
available for an externally managed model; do not run it on the same port as the
installed service.


### Persistent queue and automatic interruption recovery

Install alongside the review service (using the same endpoint/model):

```bash
.venv/bin/python scripts/install_queue_service.py \
  --workspace /path/to/videos --model-service vllm-vl.service \
  --expected-model /path/to/models/Qwen3-VL-32B-FP8 --install
systemctl --user status action-reframe-queue.service
```

The supervisor honors the saved queue pause setting. It resumes abandoned jobs
with valid state and unchanged code; it does not retry genuine failures or user
stops. A code change requires explicit retry. Render jobs now reuse validated
30-second encoding segments after interruption. See [recovery behavior and
limits](docs/REBOOT_RECOVERY.md).
