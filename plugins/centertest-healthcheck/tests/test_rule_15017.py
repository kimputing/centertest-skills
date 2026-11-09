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

CODE = """package com.acme;
public class Steps {
    void unzip(ZipInputStream zis) throws Exception {
        while ((entry = zis.getNextEntry()) != null) { log(entry); }
    }
    void fill(int index) {
        while (setAmount(index++)) { }
    }
    public void execute() {
        throw new IllegalArgumentException("execute() is not available in this class.");
    }
    Download open(Locator link, boolean again) {
        try { return download(link); } catch (RuntimeException e) { if (!again) throw e; return open(link, false); }
    }
    void spin() {
        while (!page.isReady()) { page.refresh(); }
    }
    void forever(int n) {
        forever(n + 1);
    }
}
"""


@unittest.skipUnless(HAS_JAVALANG, "javalang not installed")
class Rule15017Test(unittest.TestCase):
    def test_only_loops_and_recursion_that_can_run_forever(self):
        from eir_models import LOCAL_COMMIT
        from eir_parser import parse_directory
        import rules.rule_quality as rq
        tmp = tempfile.mkdtemp()
        try:
            folder = os.path.join(tmp, "src", "main", "java", "com", "acme")
            os.makedirs(folder)
            with open(os.path.join(folder, "Steps.java"), "w") as fh:
                fh.write(CODE)
            files = parse_directory(tmp, "src/main/java", [], [], True, None)
            rows = rq.unbounded_loops_and_recursion({LOCAL_COMMIT: files}, SimpleNamespace(repository_dir=tmp)).rows
            self.assertEqual(sorted((r[1], r[2]) for r in rows),
                             [("forever", "unbounded-recursion"), ("spin", "while-busy-wait")])
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
