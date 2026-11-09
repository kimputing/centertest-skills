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

FILES = {
    # The framework's own factory: a supported approach, with or without CenterTestAssertion.
    "FrameworkCheck": """import com.ankrpt.centertest.assertion.Assertions;
public class FrameworkCheck {
    void check(String a) { Assertions.assertThat(a).isEqualTo("x"); }
}""",
    "RawCheck": """import org.assertj.core.api.Assertions;
public class RawCheck {
    void check(String a, String b) {
        Assertions.assertThat(a).isEqualTo("x");
        Assertions.assertThat(b).isNotNull();
    }
}""",
    "StaticRawCheck": """import static org.assertj.core.api.Assertions.assertThat;
public class StaticRawCheck {
    void check(String a) { assertThat(a).isEqualTo("x"); }
}""",
    "JUnitCheck": """import org.junit.Assert;
public class JUnitCheck {
    void check(String a) { Assert.assertEquals("x", a); }
}""",
}


@unittest.skipUnless(HAS_JAVALANG, "javalang not installed")
class Rule9005Test(unittest.TestCase):
    def test_only_assertions_that_bypass_the_framework_are_reported(self):
        from eir_models import LOCAL_COMMIT
        from eir_parser import parse_directory
        import rules.rule_centertest as rc
        tmp = tempfile.mkdtemp()
        try:
            folder = os.path.join(tmp, "src", "main", "java", "com", "acme")
            os.makedirs(folder)
            for name, body in FILES.items():
                with open(os.path.join(folder, name + ".java"), "w") as fh:
                    fh.write("package com.acme;\n" + body.replace("public class", "\npublic class", 1) + "\n")
            files = parse_directory(tmp, "src/main/java", [], [], True, None)
            rows = rc.assertion_framework_usage({LOCAL_COMMIT: files}, SimpleNamespace(repository_dir=tmp)).rows
            got = sorted((r[0], r[2].split(" —")[0], "(2 calls" in r[2]) for r in rows)
            self.assertEqual(got, [("JUnitCheck", "Raw JUnit Assert", False),
                                   ("RawCheck", "Raw AssertJ (org.assertj)", True),
                                   ("StaticRawCheck", "Raw AssertJ (org.assertj)", False)])
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
