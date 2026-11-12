"""The test case table in tests/README.md matches the tests."""

import ast
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
    """{(file, test): known-bug issue number or None} for every test function in tests/."""
    found = {}
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        tree = ast.parse(path.read_text())
        # Module-level markers, for decorators like @CRASH = known_bug(37, "...")
        named = {t.id: n.value for n in tree.body if isinstance(n, ast.Assign)
                 for t in n.targets if isinstance(t, ast.Name)}
        for node in tree.body:
            if not (isinstance(node, ast.FunctionDef) and node.name.startswith("test_")):
                continue
            issue = None
            for dec in node.decorator_list:
                dec = named.get(dec.id, dec) if isinstance(dec, ast.Name) else dec
                assert "xfail" not in ast.unparse(dec), (
                    f"{path.name}::{node.name}: use @known_bug(issue, reason), not xfail")
                if (isinstance(dec, ast.Call) and ast.unparse(dec.func) == "known_bug"):
                    issue = dec.args[0].value
            found[(path.name, node.name)] = issue
    return found


def test_test_case_table_lists_every_test():
    rows, tests = table_rows(), collect_tests()
    assert sorted(set(tests) - set(rows)) == [], "add these tests to the table in tests/README.md"
    assert sorted(set(rows) - set(tests)) == [], "these rows name tests that don't exist"


def test_test_case_table_status_matches_known_bug():
    rows, tests = table_rows(), collect_tests()
    for key, status in rows.items():
        issue = tests.get(key)
        if issue is None:
            assert status == "✅", f"{key} has no @known_bug, so its status should be ✅"
        else:
            assert status == f"❌ Issue #{issue}", (
                f"{key} is @known_bug({issue}, ...): its status should be ❌ Issue #{issue}")
