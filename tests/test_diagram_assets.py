import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DiagramAssetTests(unittest.TestCase):
    def test_readme_embeds_swimlane_and_mermaid(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("docs/assets/agent-collaboration-swimlane.svg", readme)
        self.assertIn("docs/assets/agent-collaboration-swimlane-zh.png", readme)
        self.assertIn("flowchart LR", readme)
        self.assertIn("Deterministic Gatekeeper", readme)

    def test_assets_are_standalone(self):
        for name in [
            "agent-collaboration-swimlane.svg",
            "agent-collaboration-swimlane-zh.svg",
            "agent-collaboration-swimlane.png",
            "agent-collaboration-swimlane-zh.png",
            "agent-collaboration.mmd",
        ]:
            path = ROOT / "docs" / "assets" / name
            self.assertTrue(path.exists(), path)
            self.assertGreater(path.stat().st_size, 500, path)

    def test_svg_contains_role_boundaries(self):
        svg = (ROOT / "docs/assets/agent-collaboration-swimlane.svg").read_text(encoding="utf-8")
        for label in [
            "Discovery Producer",
            "Delivery Intake Reviewer",
            "Delivery Reviewer + QA Red Team",
            "Tech PRD Diagnostician",
            "Tech Producer",
            "Tech Reviewer",
            "Product Acceptance Reviewer",
            "Deterministic Gatekeeper",
        ]:
            self.assertIn(label, svg)


if __name__ == "__main__":
    unittest.main()
