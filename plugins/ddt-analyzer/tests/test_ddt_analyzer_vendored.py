import filecmp
import os
import unittest

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(os.path.dirname(PLUGIN), "ddt-tools", "scripts")


class VendoredEngineTest(unittest.TestCase):
    def test_vendored_copies_match_ddt_tools(self):
        for name in ("ddt_refcheck.py", "ddt_reference_scope.py"):
            self.assertTrue(
                filecmp.cmp(os.path.join(PLUGIN, "scripts", name), os.path.join(SOURCE, name), shallow=False),
                f"plugins/ddt-analyzer/scripts/{name} must be an unchanged copy of plugins/ddt-tools/scripts/{name}; "
                f"copy it again with: cp plugins/ddt-tools/scripts/{name} plugins/ddt-analyzer/scripts/")


if __name__ == "__main__":
    unittest.main()
