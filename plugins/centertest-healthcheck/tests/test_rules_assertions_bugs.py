"""Rules 18001-18006 (Assertions) and 24001-24004 (Bugs): one BAD and one GOOD fixture each."""

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

PKG = "com/acme/reusable"

FILES = {
    # ---------------- 18001 ----------------
    "PC.java": """package com.acme.reusable;
public interface PC {
    static AssertPayment assertPayment(InvocationContext c) { return new AssertPayment(c); }
    static AssertBilling assertBilling(InvocationContext c) { return new AssertBilling(c); }
}
""",
    "AssertPayment.java": """package com.acme.reusable;
public class AssertPayment extends BaseScenarioPC {
    public AssertPayment(InvocationContext c) { super(c); }
    @Override
    public void execute() { assertPayment(); verifyLimit(null); }
    protected void assertPayment() {
        if (true) return;  // TODO determine what to verify
        new BillingPage(getContext()).getUnapplied().assertEqualsNumeric("10");
    }
    protected void verifyLimit(String limit) {
        if (limit == null) return;
        new BillingPage(getContext()).getLimit().assertEquals(limit);
    }
    protected void checkHook() { return; }
}
""",
    "AssertPaymentDetail.java": """package com.acme.reusable;
public class AssertPaymentDetail extends AssertPayment {
    public AssertPaymentDetail(InvocationContext c) { super(c); }
    @Override
    protected void checkHook() { new BillingPage(getContext()).getLimit().assertEquals("1"); }
}
""",
    "AssertBilling.java": """package com.acme.reusable;
public class AssertBilling extends BaseScenarioBC {
    public AssertBilling(InvocationContext c) { super(c); }
    public void execute() {
        return;
    }
}
""",
    "PaymentTest.java": """package com.acme.reusable;
@CenterTest
public class PaymentTest {
    @CenterTestCase(testCaseId = "T1")
    public void run(ScenarioContext scenarioContext) {
        PC.assertPayment(scenarioContext.getInvocationContext("u")).execute();
        PC.assertBilling(scenarioContext.getInvocationContext("u")).execute();
    }
}
""",
    # ---------------- 18002 ----------------
    "AbstractChange.java": """package com.acme.reusable;
public abstract class AbstractChange extends BaseScenarioPC {
    public AbstractChange(InvocationContext c) { super(c); }
    public void execute() {
        assertPreemption();
        setViolation();
        assertHook();
        beforeQuote();
    }
    protected void assertPreemption() {
    }
    private void setViolation() {
        //todo
    }
    protected void assertHook() {
        // filled in by the subclasses that need it
    }
    protected void beforeQuote() {
    }
    protected void assertNeverCalled() {
    }
}
""",
    "HomeChange.java": """package com.acme.reusable;
public class HomeChange extends AbstractChange {
    public HomeChange(InvocationContext c) { super(c); }
    @Override
    protected void assertHook() { new QuotePage(getContext()).getPremium().assertEquals("1"); }
}
""",
    "AutoChange.java": """package com.acme.reusable;
public class AutoChange extends HomeChange {
    public AutoChange(InvocationContext c) { super(c); }
    @Override
    protected void assertHook() {
    }
}
""",
    # ---------------- 18003 / 18004 / 18005 ----------------
    "Checks.java": """package com.acme.reusable;
import java.util.Iterator;
import java.util.Objects;
public class Checks extends BaseScenarioPC {
    private static final String NO_CHANGE = "$0.00";
    private static final String DEDUCTIBLE = "$500";
    private String mode;
    public Checks(InvocationContext c) { super(c); }
    public void execute() {
        Assertions.assertThat(page.getPolicyNumber().getValue()).isNotNull();
        Assertions.assertThat(page.getTotal().getValue())
            .as("The total must be shown")
            .isNotEmpty();
        CenterTestAssertion.withContext(getContext()).withDescription("all even")
            .assertThat(() -> Assertions.assertThat(allPass).isTrue());
        assertThat(count, is(3));
    }
    void money(String value) {
        if (!value.contains(".00")) { fail(); }
        Assertions.assertThat(quote.getChange().getValue()).as("premium changes").isNotEqualTo(NO_CHANGE);
        page.getTotal().assertEquals("$1,234.56");
        coverageUtil.assertEquals(COLLISION, DED, DEDUCTIBLE);
        page.getTotal().assertEqualsNumeric("$0.00");
        page.getDeductible().set("$100.00");
    }
    boolean hasMode(String reformMode) {
        return reformMode.equalsIgnoreCase(reformMode);
    }
    void selfChecks(Data a, int count, Iterator<String> it, double d, int b) {
        boolean x = Objects.equals(a.getB(), a.getB());
        Assertions.assertThat(a.getB()).as("b").isEqualTo(a.getB());
        if (count == count) { fail(); }
        boolean ok = this.mode.equals(mode);
        boolean n = it.next().equals(it.next());
        boolean nan = d != d;
        boolean sum = count + b == b;
    }
}
""",
    # ---------------- 18006 ----------------
    "Soft.java": """package com.acme.reusable;
public class Soft extends BaseScenarioPC {
    protected SoftAssertions shared = new SoftAssertions();
    protected AnkrPtSoftAssertions unused;
    public Soft(InvocationContext c) { super(c); }
    void lost(String a, String b) {
        var softly = new AnkrPtSoftAssertions();
        softly.assertThat(a).isEqualTo(b);
    }
    void finished(String a, String b) {
        var softly = new AnkrPtSoftAssertions();
        softly.assertThat(a).isEqualTo(b);
        softly.assertAll();
    }
    void framework(String a, String b) {
        var softly = getSoftAssertions();
        softly.assertThat(a).isEqualTo(b);
    }
    void handedOver(String a, String b) {
        SoftAssertions softly = new SoftAssertions();
        softly.assertThat(a).isEqualTo(b);
        finish(softly);
    }
}
""",
    "SoftChild.java": """package com.acme.reusable;
public class SoftChild extends Soft {
    public SoftChild(InvocationContext c) { super(c); }
    void check(String a) { shared.assertThat(a).isNotEmpty(); }
}
""",
    # ---------------- 24001 / 24002 / 24003 / 24004 ----------------
    "Account.java": """package com.acme.reusable;
import com.acme.generated.pages.pc.NewAccountPage;
public class Account extends BaseScenarioPC {
    private SharedData.Person personDDT;
    public Account(InvocationContext c) { super(c); }
    void concat() {
        var newAccountPage = new NewAccountPage(getContext());
        var crit = newAccountPage.getGlobalPersonName();
        Helper.getData(getContext()).setAccountName(crit.getFirstName().getValue() + " " + crit.getLastName());
        logger.info("name {}", WidgetLabel.get("Desktop-Name", getContext()));
        var t = "%s".formatted(new NewAccountPage(getContext()).getAccountNumber());
        var ok1 = "x" + crit.getLastName().getValue();
        var ok2 = "x" + personDDT.getFirstname();
        var ok3 = "n" + crit.getLastName().getLabel();
        var ok4 = "%s %s".formatted(personDDT.getFirstname(), count);
    }
    void format(Vehicle v, int i) {
        var title = "Add #%s - %s %s %s".formatted(i + 1, v.getModelyear().getValue(), v.getMake().getValue(),
            v.getModelyear().getValue());
        logger.info("{} and {}", v.getVin().getValue(), v.getVin().getValue());
        var ok1 = "%s-%s".formatted(i, i);
        var ok2 = String.format("%1$s %1$s", v.getVin().getValue(), v.getVin().getValue());
        var ok3 = "%s %s".formatted(v.getMake().getValue(), v.getModel().getValue());
    }
    void money(Policy policyData, String total, String ratio, String totalCount) {
        var payment = Float.parseFloat(policyData.getPaymentamount().getValue());
        var stripped = Double.parseDouble(total.replaceAll("[$,]", ""));
        double premium = Double.valueOf(total);
        var ok1 = Double.parseDouble(ratio);
        var ok2 = Integer.parseInt(total);
        var ok3 = Double.parseDouble(totalCount);
    }
    void setters(Summary summary, boolean a) {
        Helper.getData(getContext()).setPolicyEffectiveDate(summary.getEffectiveDate().getValue());
        Helper.getData(getContext()).setInvoiceDate(summary.getEffectiveDate().getValue());
        var helperData = Helper.getData(getContext());
        helperData.setPolicyNumber(summary.getPolicyNumber().getValue());
        helperData.setProduct(summary.getProduct().getValue());
        helperData.setPolicyNumber(summary.getAccountNumber().getValue());
        if (a) {
            helperData.setAddress(summary.getAddress().getValue());
        } else {
            helperData.setMailingAddress(summary.getAddress().getValue());
        }
        coverageUtil.setSelected(COLLISION, true);
        coverageUtil.setSelected(COMPREHENSIVE, true);
        coverageUtil.setCoverage(COLLISION, DEDUCTIBLE, "$500");
        coverageUtil.setCoverage(COMPREHENSIVE, DEDUCTIBLE, "$500");
        helperData.setStart(LocalDate.now());
        helperData.setEnd(LocalDate.now());
        helperData.setPremium(summary.getPremium().getValue());
        summary.getQuote().click();
        helperData.setPremium(summary.getPremium().getValue());
    }
}
""",
}


@unittest.skipUnless(HAS_JAVALANG, "javalang not installed")
class AssertionsAndBugsRulesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from eir_models import LOCAL_COMMIT
        from eir_parser import parse_directory
        cls.tmp = tempfile.mkdtemp()
        folder = os.path.join(cls.tmp, "src", "main", "java", PKG)
        os.makedirs(folder)
        for name, text in FILES.items():
            with open(os.path.join(folder, name), "w") as fh:
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
        """(class, method, source line number) per finding."""
        return sorted((r[0], r[1], int(r[4].rsplit(":", 1)[1])) for r in self.rows(func))

    # -- Assertions ------------------------------------------------------------------------------------

    def test_18001_short_circuited_verification(self):
        import rules.rule_assertions as ra
        rows = self.rows(ra.verification_short_circuited)
        self.assertEqual(sorted((r[0], r[1]) for r in rows),
                         [("AssertBilling", "execute"), ("AssertPayment", "assertPayment")])
        pay = next(r for r in rows if r[1] == "assertPayment")
        self.assertIn("if (true) return", pay[2])
        self.assertIn("PaymentTest", pay[3])
        self.assertTrue(pay[4].endswith("AssertPayment.java:7"))

    def test_18002_empty_called_methods_but_not_hooks(self):
        import rules.rule_assertions as ra
        self.assertEqual(sorted((r[0], r[1]) for r in self.rows(ra.empty_step_or_assert)),
                         [("AbstractChange", "assertPreemption"), ("AbstractChange", "setViolation")])

    def test_18003_assertj_without_description(self):
        import rules.rule_assertions as ra
        found = self.lines(ra.assertj_without_description)
        self.assertEqual([r for r in found if r[0] == "Checks"], [("Checks", "execute", 10)])
        # soft assertions are AssertJ chains too
        self.assertIn(("Soft", "lost", 8), found)

    def test_18004_money_as_text(self):
        import rules.rule_assertions as ra
        self.assertEqual(self.lines(ra.money_as_text),
                         [("Checks", "money", 19), ("Checks", "money", 20), ("Checks", "money", 21)])

    def test_18005_compared_with_itself(self):
        import rules.rule_assertions as ra
        self.assertEqual(self.lines(ra.compared_with_itself),
                         [("Checks", "hasMode", 27), ("Checks", "selfChecks", 30),
                          ("Checks", "selfChecks", 31), ("Checks", "selfChecks", 32)])

    def test_18006_soft_assertions_never_asserted(self):
        import rules.rule_assertions as ra
        rows = self.rows(ra.soft_assertions_never_asserted)
        self.assertEqual(sorted((r[0], r[1]) for r in rows), [("Soft", ""), ("Soft", "lost")])
        field = next(r for r in rows if r[1] == "")
        self.assertIn("shared", field[3])

    # -- Bugs ------------------------------------------------------------------------------------------

    def test_24001_widget_concatenated(self):
        import rules.rule_bugs as rb
        rows = self.rows(rb.widget_concatenated)
        texts = sorted(r[3].split(" is ")[0] for r in rows)
        self.assertEqual(texts, ['WidgetLabel.get("Desktop-Name",getContext())', "crit.getLastName()",
                                 "newNewAccountPage(getContext()).getAccountNumber()"])

    def test_24002_same_format_argument(self):
        import rules.rule_bugs as rb
        self.assertEqual(self.lines(rb.same_format_argument_twice), [("Account", "format", 18), ("Account", "format", 20)])

    def test_24003_money_parsed_as_float(self):
        import rules.rule_bugs as rb
        self.assertEqual(self.lines(rb.money_parsed_as_float),
                         [("Account", "money", 26), ("Account", "money", 27), ("Account", "money", 28)])

    def test_24004_setter_value_twice(self):
        import rules.rule_bugs as rb
        rows = self.rows(rb.setter_value_twice)
        self.assertEqual(sorted((r[1], int(r[4].rsplit(":", 1)[1])) for r in rows),
                         [("setters", 35), ("setters", 39)])
        self.assertIn("setPolicyEffectiveDate", next(r for r in rows if r[4].endswith(":35"))[3])


if __name__ == "__main__":
    unittest.main()
