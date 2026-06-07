import py_compile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION_EXAMPLES = ROOT / "examples" / "integrations"


def test_integration_examples_are_present() -> None:
    expected_files = {
        "airflow_dag.py",
        "dbt_run_results.py",
        "github-actions-report.yml",
        "python_reporter.py",
    }

    actual_files = {path.name for path in INTEGRATION_EXAMPLES.iterdir() if path.is_file()}

    assert expected_files == actual_files


def test_python_integration_examples_compile() -> None:
    for path in sorted(INTEGRATION_EXAMPLES.glob("*.py")):
        py_compile.compile(str(path), doraise=True)


def test_integration_guide_links_to_examples() -> None:
    guide = (ROOT / "docs" / "integrations.md").read_text(encoding="utf-8")

    assert "python_reporter.py" in guide
    assert "dbt_run_results.py" in guide
    assert "airflow_dag.py" in guide
    assert "github-actions-report.yml" in guide