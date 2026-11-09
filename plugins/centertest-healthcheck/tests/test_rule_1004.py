import os
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

try:
    import javalang  # noqa: F401
    HAS_JAVALANG = True
except ImportError:
    HAS_JAVALANG = False


@unittest.skipUnless(HAS_JAVALANG, "javalang not installed")
class Rule1004Test(unittest.TestCase):
    def test_a_sub_package_needs_three_classes_and_not_all_of_them(self):
        from eir_models import LOCAL_COMMIT
        from eir_parser import parse_directory
        import rules.rule_classnames as rcn
        tmp = tempfile.mkdtemp()
        try:
            names = ["WC_PaymentRefundTest", "WC_PaymentReversalTest", "WC_PaymentPlanTest",
                     "WC_ClaimInAndOutTest", "WC_ClaimNoteTest"]
            folder = os.path.join(tmp, "src", "main", "java", "com", "acme", "tests", "bc", "workerscomp")
            os.makedirs(folder)
            for n in names:
                with open(os.path.join(folder, n + ".java"), "w") as fh:
                    fh.write(f"package com.acme.tests.bc.workerscomp;\n@CenterTest\npublic class {n} {{ }}\n")
            files = parse_directory(tmp, "src/main/java", [], [], True, None)
            result = rcn.possible_new_packages({LOCAL_COMMIT: files}, SimpleNamespace(repository_dir=tmp))
            items = [i for s in result.sections for sub in s.subsections for i in sub.items]
            # Payment: 3 of 5. Not WC (all 5), not Claim (2), not In/And (connecting words).
            self.assertEqual(items, ["Payment: 3/5 (60%)"])
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
