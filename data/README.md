# Local video data

This directory is the default review workspace. Its contents, except this README, are ignored by Git. No private media or external directory link is required to start the application.

For the review interface, put your videos directly in this directory, then launch:

```bash
./scripts/run_review.sh --workspace ./data
```

Select a frame, draw a rectangle, describe the target, and create a project. The tool writes a project JSON file and creates outputs when processing starts. An empty directory is supported; no sailboat template needs to be copied.

Alternatively, choose any writable workspace with `--workspace /path/to/videos` or `LONGVIDEO_WORKSPACE`. Workspace configs use paths relative to that workspace. The browser server restricts access to the chosen workspace; links to files outside it are not followed for serving media.

The optional CLI configurations in `configs/` expect a user-provided `data/videos/example.mp4`. Their reference box/time describe the historical sailboat example and must be adjusted for other footage. They write to `data/outputs/`. These examples are not test fixtures.

Generated caches and run records can include resolved paths on the machine that produced them. Move source media and relative project configurations together; regenerate caches/results when moving a project to another machine. Preserve originals separately from generated files.

The automated tests create disposable synthetic footage in temporary directories. They require neither this directory's contents nor a running model service.
