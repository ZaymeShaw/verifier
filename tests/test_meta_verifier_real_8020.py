import importlib.util
import os
from pathlib import Path
import sys
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / ".claude" / "skills" / "meta-verifier" / "scripts" / "meta_verifier.py"
spec = importlib.util.spec_from_file_location("meta_verifier_skill", MODULE_PATH)
meta_verifier_skill = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules["meta_verifier_skill"] = meta_verifier_skill
spec.loader.exec_module(meta_verifier_skill)

MetaVerifierBrowserEvidenceExecutor = meta_verifier_skill.MetaVerifierBrowserEvidenceExecutor


@unittest.skipUnless(os.environ.get("RUN_REAL_META_VERIFIER_8020") == "1", "set RUN_REAL_META_VERIFIER_8020=1 to run real browser smoke")
class MetaVerifierReal8020SmokeTest(unittest.TestCase):
    def test_real_8020_entrypoint_navigation_returns_browser_evidence(self):
        executor = MetaVerifierBrowserEvidenceExecutor()

        evidence, findings = executor.run_plan(
            "C-real-8020",
            "http://127.0.0.1:8020/frontend/index.html",
            [
                {"type": "open", "target": "http://127.0.0.1:8020/frontend/index.html"},
                {"type": "assert_text", "text": "Live"},
                {"type": "open", "target": "http://127.0.0.1:8020/frontend/live.html"},
                {"type": "assert_text", "text": "运行"},
                {"type": "open", "target": "http://127.0.0.1:8020/frontend/summary.html"},
                {"type": "assert_text", "text": "归因"},
            ],
        )

        self.assertEqual(evidence.source, "browser")
        self.assertTrue(evidence.action_trace)
        self.assertIn(evidence.action_trace[-1]["status"], {"passed", "failed"})
        if findings:
            self.assertTrue(evidence.error_message or evidence.action_trace[-1].get("error_message"))


if __name__ == "__main__":
    unittest.main()
