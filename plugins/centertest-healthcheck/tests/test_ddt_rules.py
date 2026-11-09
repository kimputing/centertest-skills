import filecmp
import os
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
PLUGINS = os.path.dirname(PLUGIN)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(PLUGIN, "scripts"))
sys.path.insert(0, os.path.join(PLUGINS, "ddt-tools", "tests"))

try:
    import openpyxl  # noqa: F401
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

VENDORED = ("ddt_refcheck.py", "ddt_reference_scope.py")


class VendoredRefcheckTest(unittest.TestCase):
    def test_vendored_copies_match_ddt_tools(self):
        for name in VENDORED:
            mine = os.path.join(PLUGIN, "scripts", name)
            source = os.path.join(PLUGINS, "ddt-tools", "scripts", name)
            self.assertTrue(
                filecmp.cmp(mine, source, shallow=False),
                f"plugins/centertest-healthcheck/scripts/{name} must be an unchanged copy of "
                f"plugins/ddt-tools/scripts/{name}; copy it again with: "
                f"cp plugins/ddt-tools/scripts/{name} plugins/centertest-healthcheck/scripts/")


@unittest.skipUnless(HAS_OPENPYXL, "openpyxl not installed")
class DdtRulesAgreeWithValidatorTest(unittest.TestCase):
    def test_14003_plus_14004_equal_the_validator(self):
        from refcheck_fixture import build_project
        import rules.rule_ddt as rule_ddt
        tmp = tempfile.mkdtemp()
        try:
            build_project(tmp)
            config = SimpleNamespace(repository_dir=tmp)
            refs = rule_ddt.ddt_reference_integrity({}, config)
            rels = rule_ddt.ddt_relationship_integrity({}, config)
            self.assertEqual(sorted((r[1], r[2], r[3]) for r in refs.rows),
                             [(3, "@Submission.#Coverage", "Terrorism"), (4, "#Company", "Nope")])
            self.assertEqual([(r[1], r[2], r[3]) for r in rels.rows], [(4, "@Submission", "Missing")])
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
