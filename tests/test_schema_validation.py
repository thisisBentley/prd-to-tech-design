import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / ("scripts" if ROOT.name == "ai-native-delivery" else "tools") / "validate_json_schemas.py"


class SchemaValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("schema_validator", TOOL)
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def test_valid_agent_task_instance_passes(self):
        schema = json.loads((ROOT / ("references" if ROOT.name == "ai-native-delivery" else "schemas") / "agent-task.schema.json").read_text())
        instance = json.loads((ROOT / "examples" / "agent-collaboration" / "agent-task.json").read_text())
        self.assertEqual(self.module.validate(instance, schema, schema), [])

    def test_invalid_role_and_missing_required_field_fail(self):
        schema = json.loads((ROOT / ("references" if ROOT.name == "ai-native-delivery" else "schemas") / "agent-task.schema.json").read_text())
        instance = json.loads((ROOT / "examples" / "agent-collaboration" / "agent-task.json").read_text())
        instance["role"] = "not-a-role"
        del instance["objective"]
        errors = self.module.validate(instance, schema, schema)
        self.assertTrue(any("missing required property objective" in error for error in errors))
        self.assertTrue(any("not in enum" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
