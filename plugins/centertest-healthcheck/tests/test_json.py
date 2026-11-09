import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import eir_json  # noqa: E402
from eir_models import RuleResult  # noqa: E402


class JsonOutputTest(unittest.TestCase):
    def test_health_json_is_plain_json_with_the_trust_verdict(self):
        results = [RuleResult(rule_id="15018", description="Discarded .equals()", category="Quality",
                              headers=["Class", "Method", "Location"], rows=[["A", "run", "src/A.java:3"]]),
                   RuleResult(rule_id="4001", description="Variable substitutions", category="Methods",
                              headers=["Class"], rows=[])]
        doc = eir_json.health_json(results, "acme", 10, data={"scenarios": 5, "codes": {"x"}})
        with tempfile.TemporaryDirectory() as out:
            path = eir_json.write(doc, out, "HealthCheck")
            with open(path, encoding="utf-8") as fh:
                back = json.load(fh)
        self.assertEqual(back["schema"], eir_json.SCHEMA)
        self.assertEqual(back["trust"]["blockers"][0]["rule_id"], "15018")
        self.assertEqual(back["trust"]["blockers"][0]["locations"], ["src/A.java:3"])
        self.assertEqual([r["id"] for r in back["rules"]], ["15018", "4001"])
        self.assertEqual(back["data"]["codes"], ["x"])  # sets become lists

    def test_review_json_carries_verdict_and_exit_code(self):
        doc = eir_json.review_json([], {"rerun": [{"test": "T", "codes": [], "reasons": ["x"]}]})
        self.assertEqual((doc["exit_code"], doc["meta"]["rerun"][0]["test"]), (0, "T"))
        json.dumps(doc)


if __name__ == "__main__":
    unittest.main()
