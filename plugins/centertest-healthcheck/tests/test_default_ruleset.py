import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))


class DefaultRulesetTest(unittest.TestCase):
    def test_a_plain_run_checks_every_trust_rule(self):
        from eir_config import EirConfig
        from eir_report import TRUST_RULES
        config = EirConfig()
        config.__dict__.update(rules=None)
        if os.environ.get("EIR_REPORT_RULESET") or config.ruleset != "CenterTestFull":
            self.skipTest("a ruleset is configured on this machine")
        active = set(config.get_active_rule_ids())
        self.assertEqual(set(TRUST_RULES) - active, set())


if __name__ == "__main__":
    unittest.main()
