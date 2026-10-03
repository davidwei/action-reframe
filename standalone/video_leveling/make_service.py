"""Generate a persistent systemd user service for a leveling plan."""

import argparse
import json
from pathlib import Path


def quote(value: str) -> str:
    """Quote one systemd argument without invoking a shell."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render(plan_path: Path) -> str:
    plan_path = plan_path.resolve()
    plan = json.loads(plan_path.read_text())
    working_directory = Path(plan["working_directory"]).resolve()
    # Preserve a virtual-environment launcher path. Resolving its symlink to the
    # system interpreter would bypass pyvenv.cfg and lose installed dependencies.
    python = Path(plan["python"]).absolute()
    production_service = plan["production_service"]
    restore = [production_service, *plan.get("pause_services", [])]

    lines = [
        "[Unit]",
        "Description=Standalone action-video leveling",
        "After=default.target",
        "",
        "[Service]",
        "Type=simple",
        f"WorkingDirectory={working_directory}",
        f"ExecStartPre=/usr/bin/systemctl --user start {production_service}",
        f"ExecStart={quote(str(python))} -m standalone.video_leveling.orchestrate {quote(str(plan_path))}",
        "Restart=on-abnormal",
        "RestartSec=30",
        "TimeoutStopSec=120",
        "KillMode=control-group",
    ]
    for service in restore:
        lines.append(f"ExecStopPost=-/usr/bin/systemctl --user start {service}")
    lines += ["", "[Install]", "WantedBy=default.target", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(args.plan))
    print(args.output.resolve())


if __name__ == "__main__":
    main()
