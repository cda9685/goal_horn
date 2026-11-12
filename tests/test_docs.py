"""The test case table in tests/README.md matches the tests."""

import ast
import re
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
    """{(file, test): xfail reason or None} for every test function in tests/."""
    found = {}
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        tree = ast.parse(path.read_text())
        # Module-level string constants, for reasons like reason=CRASH
        constants = {t.id: n.value.value for n in tree.body if isinstance(n, ast.Assign)
                     for t in n.targets if isinstance(t, ast.Name)
                     and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)}
        for node in tree.body:
            if not (isinstance(node, ast.FunctionDef) and node.name.startswith("test_")):
                continue
            reason = None
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call) and "xfail" in ast.unparse(dec.func):
                    for kw in dec.keywords:
                        if kw.arg == "reason":
                            value  = kw.value
                            reason = (value.value if isinstance(value, ast.Constant)
                                      else constants.get(getattr(value, "id", ""), ""))
            found[(path.name, node.name)] = reason
    return found


def test_test_case_table_lists_every_test():
    rows, tests = table_rows(), collect_tests()
    assert sorted(set(tests) - set(rows)) == [], "add these tests to the table in tests/README.md"
    assert sorted(set(rows) - set(tests)) == [], "these rows name tests that don't exist"


def test_test_case_table_status_matches_xfail():
    rows, tests = table_rows(), collect_tests()
    for key, status in rows.items():
        reason = tests.get(key, None)
        if reason is None:
            assert status == "✅", f"{key} passes, so its status should be ✅"
        else:
            issue = re.match(r"❌ Issue #(\d+)$", status)
            assert issue, f"{key} is a known bug: its status should be ❌ Issue #N"
            assert f"#{issue.group(1)}" in reason, (
                f"{key}: the table says Issue #{issue.group(1)}, the xfail says {reason!r}")
