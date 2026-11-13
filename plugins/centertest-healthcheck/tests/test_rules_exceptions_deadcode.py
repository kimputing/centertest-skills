"""Rules 22001-22005 (Exceptions) and 23001-23007 (DeadCode): one BAD and one GOOD case per rule."""

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


ACCOUNT_STEP = """package com.acme.steps;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class SearchForAccountStep extends BaseScenarioPC {
    private static final Logger logger = LoggerFactory.getLogger(SearchForAccountStep.class);

    public void execute() {
        search();
    }

    void branchBad() {
        try {
            save();
        } catch (Exception e) {
            logger.warn("Guidewire Optimistic Locking Exception");
            retry();
        }
    }

    void branchGood() {
        try { save(); } catch (Exception e) { logger.warn("Not saved yet", e); retry(); }
        try { save(); } catch (Exception e) { }
        try { save(); } catch (TimeoutException e) { retry(); }
        try { save(); } catch (Exception e) { throw e; }
        try { save(); } catch (Exception ignored) { retry(); }
    }

    void rethrowBad() {
        try {
            find();
        } catch (NoSuchElementException e) {
            throw new CoverageNotFoundException("Coverage %s cannot be found".formatted(name));
        }
        try { find(); } catch (NoSuchElementException e) { throw new CoverageNotFoundException(e.getMessage()); }
    }

    void rethrowGood() {
        try { find(); } catch (NoSuchElementException e) { throw new CoverageNotFoundException("Coverage cannot be found", e); }
        try { find(); } catch (IOException ex) { logger.error("could not read", ex); throw new IllegalStateException("bad"); }
        try { find(); } catch (IOException e) { throw new RuntimeException("Unable to write the report", e); }
    }

    void search() {
        if (rows.isEmpty()) throw new IllegalArgumentException("Submission: " + number + " could not be found");
        if (other.isEmpty()) throw new RuntimeException("Policy is not in Billing Center.");
    }

    void validate(String tab) {
        switch (tab) {
            default:
                throw new IllegalArgumentException("Unknown coverage tab: " + tab);
        }
    }

    void logs() {
        logger.info("Created account %s".formatted(number));
        logger.debug("Row " + row + " selected");
        logger.info("Created account {}", number);
        logger.info("a long message " + "split in two");
        logger.warn("plain");
    }
}
"""

SUBMISSION_STEP = """package com.acme.steps;

public class SearchForSubmissionStep extends BaseScenarioPC {
    public void execute() {
        if (rows.isEmpty()) throw new IllegalArgumentException("Submission: " + number + " could not be found");
    }
}
"""

UTIL = """package com.acme.util;

public final class ConfigUtil {
    static String read(String key) {
        if (key == null) throw new RuntimeException("bad configuration key");
        if (rows.isEmpty()) throw new RuntimeException("Row was not found");
        return key;
    }
}
"""

GENERATED = """package com.acme.generated.pages;

public class Page {
    void open() {
        try { go(); } catch (Exception e) { retry(); }
        // TODO generated
    }
}
"""

PA_TEST = """package com.acme.tests;

/**
 * Example: {@code @Test} and
 * TODO in Javadoc without ticket
 */
@CenterTest
public class PA_Test {
//  @DataDriven(datasource = "testdata/x.xlsx")
    @CenterTestCase
    public void run(ScenarioContext scenarioContext) {
//    if (true) throw new RuntimeException("HARD FAILURE - X");
        step();
//    takeScreenshot("PC Payment Plan");
//    wizardPage.getPaymentStep().click();
//    waitForPageTitle("Payment");

        // The payment step is skipped because
        // the account has no billing; see the
        // @Test notes in the wiki for the reason.
        var x = 1;
        int used = 0;
        use(used);
        for (var r : rows) {
            // logger.info(r);
        }
        if (true) throw new CenterTestNotImplementedException("for GRID Rating");
        next();
        more();
    }

    void other() {
        if (ready) {
        } else {
            go();
        }
        do {
            a();
        } while (false);
        // TODO KIM
        // TODO remove once fixed. Jira CTAP-139
        // TODO remove the trailing
        // space. ServiceNow CS0853057
        String s = "TODO in a string";
        call(); // FIXME see https://example.com/issue
        // format: XXX-XXXX
    }

    void finished() {
        if (false) {
            old();
        }
        // throw new RuntimeException("keep going");
    }
}
"""

ABSTRACT_CHANGE = """package com.acme.steps;

import org.slf4j.Logger;

public abstract class AbstractChange extends BaseScenarioPC {
    private static final Logger logger = LoggerFactory.getLogger(AbstractChange.class);
    private static final long serialVersionUID = 1L;
    protected LocalDate vehicleClassification;
    protected String description;
    private String reformMessage;
    private List<String> modes;
    private String name;
    private int counter;
    @Inject private Foo injected;
    public String visible;

    public AbstractChange(InvocationContext context) {
        super(context);
        this.reformMessage = "x";
    }

    public AbstractChange withName(String name) {
        this.name = name;
        return this;
    }

    boolean has(String mode) {
        counter++;
        return modes.contains(mode);
    }
}
"""

CONCRETE_CHANGE = """package com.acme.steps.pa;

public class ConcreteChange extends AbstractChange {
    public ConcreteChange(InvocationContext context) { super(context); }

    public void execute() {
        log(description);
    }
}
"""

# Java 14+ syntax outside a method body: javalang cannot parse it even lowered (regex fallback, no
# fields). Its own field of the same name must not count as a read of AbstractChange.vehicleClassification.
MODERN = """package com.acme.other;

public class Modern {
    private final String vehicleClassification = "x";
    private static final String Y = switch (1) { case 1 -> "a"; default -> "b"; };

    String kind(int k) {
        return vehicleClassification + Y;
    }
}
"""


@unittest.skipUnless(HAS_JAVALANG, "javalang not installed")
class ExceptionsAndDeadCodeRulesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from eir_models import LOCAL_COMMIT
        from eir_parser import parse_directory
        cls.tmp = tempfile.mkdtemp()
        root = os.path.join(cls.tmp, "src", "main", "java", "com", "acme")
        sources = {
            "steps/SearchForAccountStep.java": ACCOUNT_STEP,
            "steps/SearchForSubmissionStep.java": SUBMISSION_STEP,
            "steps/AbstractChange.java": ABSTRACT_CHANGE,
            "steps/pa/ConcreteChange.java": CONCRETE_CHANGE,
            "util/ConfigUtil.java": UTIL,
            "generated/pages/Page.java": GENERATED,
            "tests/PA_Test.java": PA_TEST,
            "other/Modern.java": MODERN,
        }
        for rel, text in sources.items():
            path = os.path.join(root, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as fh:
                fh.write(text)
        files = parse_directory(cls.tmp, "src/main/java", [], [], True, None)
        cls.commits = {LOCAL_COMMIT: files}
        cls.config = SimpleNamespace(repository_dir=cls.tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def rows(self, func):
        return func(self.commits, self.config).rows

    def lines(self, func):
        """[(class, file:line)] of a rule's findings."""
        return sorted((r[0], r[-1].rsplit("/", 1)[-1]) for r in self.rows(func))

    # ---------------- Exceptions ----------------

    def test_22001_broad_catch_used_as_branch(self):
        import rules.rule_exceptions as rx
        self.assertEqual(self.lines(rx.broad_catch_as_branch), [("SearchForAccountStep", "SearchForAccountStep.java:16")])

    def test_22002_rethrow_drops_cause(self):
        import rules.rule_exceptions as rx
        rows = self.rows(rx.rethrow_drops_cause)
        self.assertEqual(sorted((r[1], r[-1].rsplit(":", 1)[-1]) for r in rows), [("rethrowBad", "34"), ("rethrowBad", "36")])
        self.assertIn("CoverageNotFoundException", rows[0][3])

    def test_22003_generic_runtime_exception(self):
        import rules.rule_exceptions as rx
        rows = self.rows(rx.generic_runtime_exception)
        got = sorted((r[0], r[2]) for r in rows)
        self.assertEqual(got, [
            ("ConfigUtil", 'if (rows.isEmpty()) throw new RuntimeException("Row was not found");'),
            ("SearchForAccountStep", 'if (other.isEmpty()) throw new RuntimeException("Policy is not in Billing Center.");'),
            ("SearchForAccountStep", 'if (rows.isEmpty()) throw new IllegalArgumentException("Submission: " + number + " could not be found");'),
            ("SearchForSubmissionStep", 'if (rows.isEmpty()) throw new IllegalArgumentException("Submission: " + number + " could not be found");'),
        ])

    def test_22004_copied_failure_message(self):
        import rules.rule_exceptions as rx
        rows = self.rows(rx.copied_failure_message)
        self.assertEqual([(r[0], r[1]) for r in rows], [("SearchForAccountStep", "search")])
        self.assertIn("SearchForSubmissionStep", rows[0][3])

    def test_22005_log_message_built(self):
        import rules.rule_exceptions as rx
        rows = self.rows(rx.log_message_built)
        self.assertEqual([r[2] for r in rows], ['logger.info("Created account %s".formatted(number));',
                                                'logger.debug("Row " + row + " selected");'])

    # ---------------- DeadCode ----------------

    def test_23001_commented_out_code(self):
        import rules.rule_deadcode as rd
        rows = self.rows(rd.commented_out_code)
        self.assertEqual([(r[0], r[1], r[-1].rsplit(":", 1)[-1]) for r in rows], [("PA_Test", "run", "14")])
        self.assertIn("3 commented-out lines", rows[0][3])

    def test_23002_commented_out_annotation(self):
        import rules.rule_deadcode as rd
        rows = self.rows(rd.commented_out_annotation)
        self.assertEqual([r[-1].rsplit("/", 1)[-1] for r in rows], ["PA_Test.java:9"])
        self.assertIn("@DataDriven", rows[0][3])

    def test_23003_commented_out_debug_switch(self):
        import rules.rule_deadcode as rd
        rows = self.rows(rd.commented_out_debug_switch)
        self.assertEqual([r[-1].rsplit("/", 1)[-1] for r in rows], ["PA_Test.java:12"])

    def test_23004_constant_condition(self):
        import rules.rule_deadcode as rd
        rows = self.rows(rd.constant_condition)
        self.assertEqual([(r[1], r[-1].rsplit(":", 1)[-1]) for r in rows], [("run", "27"), ("finished", "50")])
        self.assertIn("2 code line(s)", rows[0][3])

    def test_23005_todo_without_ticket(self):
        import rules.rule_deadcode as rd
        rows = self.rows(rd.todo_without_ticket)
        self.assertEqual(sorted(r[-1].rsplit("/", 1)[-1] for r in rows), ["PA_Test.java:40", "PA_Test.java:5"])

    def test_23006_debugger_anchors(self):
        import rules.rule_deadcode as rd
        rows = self.rows(rd.debugger_anchors)
        self.assertEqual([r[2] for r in rows], ["var x = 1;", "for (var r : rows) {"])

    def test_23007_field_never_read(self):
        import rules.rule_deadcode as rd
        rows = self.rows(rd.field_never_read)
        names = sorted(r[2] for r in rows)
        self.assertEqual(names, ["private String name;", "private String reformMessage;",
                                 "protected LocalDate vehicleClassification;"])


if __name__ == "__main__":
    unittest.main()
