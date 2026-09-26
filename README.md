# Action Video

Offline subject tracking, camera leveling, smooth reframing, and review for action footage.

This repository contains the existing prototype and the proposed three-part workflow: design plans, validate them through offline trials, then process approved videos for final review and clip selection. The planning and batch workflow is not implemented yet.

## Repository layout

```text
docs/             Product design, implementation plan, decisions, prototype guide
src/              Python processing and review-server code
src/web/          Review/comparison pages and frame diagnostics
tests/            Geometry, backward recovery, and temporal-context tests
configs/          Example processing configurations
scripts/          Development launchers and test runner
data/             Local workspaces and outputs; excluded from Git
requirements.in   Dependency constraints
requirements.txt  Locked dependencies
```

Read [the project design](docs/PROJECT_DESIGN.md) and [the verifiable implementation plan](docs/PROJECT_PLAN.md) first. [Prototype documentation](docs/PROTOTYPE.md) records existing features and limitations; its older commands refer to the original workspace. Use the launchers below for this repository.

## Local setup

On this machine, `.venv` links to the existing dedicated video environment and `data/workspace` links to the original `/home/dwei/longvideo` workspace. Neither link is committed. No LeRobot environment is used, and videos have not been copied or moved.

For a fresh checkout, create an environment and configure a workspace containing your video files and project JSON files:

```bash
uv venv .venv --python /usr/bin/python3.12
uv pip sync requirements.txt --python .venv/bin/python
export LONGVIDEO_WORKSPACE=/absolute/path/to/video-workspace
```

The review server uses `LONGVIDEO_WORKSPACE`, otherwise the local `data/workspace` link, otherwise `data/`. Video and output paths in workspace configurations should be relative to that workspace. See [data setup](data/README.md).

## Develop and verify

```bash
./scripts/test.sh
./scripts/run_review.sh --port 8766
./scripts/run_reframe.sh --help
```

Open <http://127.0.0.1:8766/> or <http://127.0.0.1:8766/compare>. Port 8766 avoids the existing prototype server on 8765. Launchers can be called from any directory.

The linked workspace exposes the existing example and outputs. Editing settings or running jobs through the development UI writes to that workspace. For isolated development, point `LONGVIDEO_WORKSPACE` at a separate directory containing its own videos/configurations. Avoid concurrent jobs against the same output directory; the current prototype does not yet have a durable cross-process queue.

Run an isolated processing experiment with:

```bash
./scripts/run_reframe.sh configs/sailboat_example.json --stage all
```

The repository example configurations read source media through `data/workspace` and write new results under `data/outputs/`. These paths are resolved relative to the configuration file. CLI paths are interpreted from the repository root by the launcher. The CLI uses configuration paths independently of the review server's workspace setting.

Qwen is served separately by the existing local vLLM service. No model weights, videos, generated outputs, credentials, or environment files belong in Git.

## Development status

The repository starts from the working prototype, including its known leveling limitations. The refactor separates source/static assets from mutable data; it does not implement the planned three-workspace product. GitHub Actions runs the unit suite on pushes and pull requests, without requiring videos or a model server.

## Contributing

Use the milestone acceptance checks in `docs/PROJECT_PLAN.md`. Run `./scripts/test.sh` before committing and verify changed UI behavior in the browser. Keep machine-local paths, source footage, model credentials, and generated outputs out of tracked files. New model integrations should read secrets from the environment.

This repository does not yet declare an open-source license. Choose a license before offering it for public reuse.
