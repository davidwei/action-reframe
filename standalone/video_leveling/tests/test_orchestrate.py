import json
import sys
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))

from standalone.video_leveling.orchestrate import command
from standalone.video_leveling.make_service import render


class OrchestrationTests(unittest.TestCase):
    def test_stage_command_carries_budget_models_and_options(self):
        plan=dict(python="python",primary=dict(served_name="gemma"),review=dict(served_name="qwen"),experiment_endpoint="http://model/v1")
        job=dict(video="/v.mp4",output="/out",hours=6,options=dict(base_fps=.5,motion_fps=5))
        value=command(plan,job,"primary")
        self.assertIn("gemma",value)
        self.assertIn("qwen",value)
        self.assertEqual(value[value.index("--hours")+1],"6")
        self.assertEqual(value[value.index("--base-fps")+1],"0.5")

    def test_service_is_reboot_resumable_and_restores_services(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            plan = root / "plan.json"
            plan.write_text(json.dumps({
                "working_directory": str(root / "repo"),
                "python": str(root / "venv" / "python"),
                "production_service": "model.service",
                "pause_services": ["queue.service"],
            }))
            unit = render(plan)
            self.assertIn("WantedBy=default.target", unit)
            self.assertIn("Restart=on-abnormal", unit)
            self.assertIn(str(root / "venv" / "python"), unit)
            self.assertIn("ExecStopPost=-/usr/bin/systemctl --user start model.service", unit)
            self.assertIn("ExecStopPost=-/usr/bin/systemctl --user start queue.service", unit)


if __name__=="__main__":unittest.main()
