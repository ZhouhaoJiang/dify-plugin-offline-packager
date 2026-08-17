from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/build-offline-package.yml"


class PackagingWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.content = WORKFLOW.read_text(encoding="utf-8")

    def test_is_manual_only_and_least_privilege(self) -> None:
        self.assertIn("  workflow_dispatch:\n", self.content)
        self.assertNotIn("pull_request_target:", self.content)
        self.assertNotRegex(self.content, r"(?m)^  (push|pull_request|repository_dispatch):")
        self.assertIn("permissions:\n  contents: read\n", self.content)

    def test_all_external_actions_are_commit_pinned(self) -> None:
        uses = re.findall(r"(?m)^\s+uses:\s+([^\s#]+)", self.content)
        self.assertTrue(uses)
        for action in uses:
            with self.subTest(action=action):
                self.assertRegex(action, r"^[^@]+@[0-9a-f]{40}$")

    def test_checkout_credentials_and_private_key_are_not_artifacts(self) -> None:
        self.assertIn("persist-credentials: false", self.content)
        upload_step = self.content.split("- name: Upload offline package", maxsplit=1)[1]
        self.assertNotIn("private.pem", upload_step)
        self.assertIn("/dist/", upload_step)

    def test_artifact_name_matches_generated_package(self) -> None:
        self.assertIn(
            'artifact_name="${output_stem}-offline-linux-${INPUT_ARCHITECTURE}"',
            self.content,
        )
        self.assertIn('echo "artifact_name=$artifact_name"', self.content)
        upload_step = self.content.split("- name: Upload offline package", maxsplit=1)[1]
        self.assertIn("name: ${{ steps.workspace.outputs.artifact_name }}", upload_step)
        self.assertNotIn("github.run_number", upload_step)


if __name__ == "__main__":
    unittest.main()
