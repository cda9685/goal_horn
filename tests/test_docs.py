"""The test case table in tests/README.md matches the tests."""

import importlib
from pathlib import Path

TESTS_DIR = Path(__file__).parent
README    = TESTS_DIR / "README.md"


def table_rows() -> dict:
    """{(file, test): status} from the rows between the test-cases markers."""
    text  = README.read_text()
    table = text.split("<!-- test-cases:start -->")[1].split("<!-- test-cases:end -->")[0]
    rows  = {}
    for line in table.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 6 and cells[0].startswith("`test_"):
            key = (cells[0].strip("`"), cells[1].strip("`"))
            assert key not in rows, f"{key} is listed twice"
            rows[key] = cells[5]
    return rows


def collect_tests() -> dict:
    """
    {(file, test): (issues, partly)} for every test function in tests/: the
    known-bug issues it's marked with, and whether only some of its cases are.
    """
    found = {}
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        module = importlib.import_module(path.stem)
        for name, test in vars(module).items():
            if not (name.startswith("test_") and callable(test)
                    and getattr(test, "__module__", None) == module.__name__):
                continue
            marks = getattr(test, "pytestmark", [])
            check_known_bug_marks(f"{path.name}::{name}", marks)
            issues = {m.kwargs["issue"] for m in marks if m.name == "known_bug"}
            partly = set()
            for m in marks:
                if m.name == "parametrize":
                    for case in m.args[1]:
                        case_marks = getattr(case, "marks", ())
                        check_known_bug_marks(f"{path.name}::{name}", case_marks)
                        partly |= {c.kwargs["issue"] for c in case_marks if c.name == "known_bug"}
            found[(path.name, name)] = (issues or partly, bool(partly) and not issues)
    return found


def check_known_bug_marks(where, marks):
    names = [m.name for m in marks]
    assert names.count("xfail") == names.count("known_bug"), (
        f"{where}: use @known_bug(issue, reason) or known_bug_marks(), not xfail")


def expected_status(issues, partly) -> str:
    if not issues:
        return "✅"
    listed = ", ".join(f"Issue #{n}" for n in sorted(issues))
    return f"❌ {listed} (some cases)" if partly else f"❌ {listed}"


def test_test_case_table_lists_every_test():
    rows, tests = table_rows(), collect_tests()
    assert sorted(set(tests) - set(rows)) == [], "add these tests to the table in tests/README.md"
    assert sorted(set(rows) - set(tests)) == [], "these rows name tests that don't exist"


def test_test_case_table_status_matches_known_bug():
    rows, tests = table_rows(), collect_tests()
    for key, status in rows.items():
        if key in tests:
            want = expected_status(*tests[key])
            assert status == want, f"{key}: status should be {want!r}, the table says {status!r}"
