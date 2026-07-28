import json

import pytest

from loop_cli.main import main


def run_cli(args, capsys):
    code = main(args)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_cli_help_page(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])

    out = capsys.readouterr().out

    assert exc.value.code == 0
    assert "Loop Engineering workflow runner" in out
    assert "new-project" in out


def test_cli_version_and_lists(capsys):
    code, out, _ = run_cli(["version", "--json"], capsys)
    assert code == 0
    assert json.loads(out)["version"]

    code, out, _ = run_cli(["workflows", "--json"], capsys)
    workflows = json.loads(out)
    assert code == 0
    assert any(item["name"] == "feature-development" for item in workflows)

    code, out, _ = run_cli(["agents", "--json"], capsys)
    assert code == 0
    assert any(item["name"] == "planner" for item in json.loads(out))

    code, out, _ = run_cli(["adapters", "--json"], capsys)
    assert code == 0
    assert json.loads(out)[0]["name"] == "mock.agent"


def test_cli_run_workflow_json_and_dry_run(capsys):
    code, out, _ = run_cli(
        ["run", "bug-fix", "--goal", "Fix parser bug", "--parameters", '{"max_retries": 2}', "--json"],
        capsys,
    )
    result = json.loads(out)

    assert code == 0
    assert result["status"] == "DONE"
    assert result["workflow"] == "bug-fix"

    code, out, _ = run_cli(["run", "feature", "--goal", "Build auth", "--dry-run", "--json"], capsys)
    dry_run = json.loads(out)

    assert code == 0
    assert dry_run["dry_run"] is True
    assert dry_run["workflow"] == "feature-development"
    assert dry_run["plan"]["steps"]


def test_cli_run_supports_workflow_option_issue_and_key_value_parameters(capsys):
    code, out, _ = run_cli(
        [
            "run",
            "--workflow",
            "documentation",
            "--issue",
            "Document configuration",
            "--parameters",
            "max_retries=2,verification=links",
            "--json",
            "--verbose",
        ],
        capsys,
    )
    result = json.loads(out)

    assert code == 0
    assert result["workflow"] == "documentation"
    assert result["execution"]["metrics"]["values"]["workflow.documentation.success"] == 1


def test_cli_new_project_dry_run(capsys):
    code, out, _ = run_cli(["new-project", "--goal", "Build a FastAPI Todo backend", "--dry-run", "--json"], capsys)
    result = json.loads(out)

    assert code == 0
    assert result["workflow"] == "feature-development"
    assert result["plan"]["metadata"]["workflow"] == "feature-development"


def test_cli_config_init_show_set(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LOOP_CONFIG_HOME", str(tmp_path))

    code, out, _ = run_cli(["config", "init", "--json"], capsys)
    assert code == 0
    assert json.loads(out)["path"].endswith("config.json")

    code, out, _ = run_cli(["config", "set", "retry_limits", "5", "--json"], capsys)
    assert code == 0
    assert json.loads(out)["value"]["retry_limits"] == 5

    code, out, _ = run_cli(["config", "show", "--json"], capsys)
    assert code == 0
    assert json.loads(out)["retry_limits"] == 5


def test_cli_doctor_and_benchmark(capsys):
    code, out, _ = run_cli(["doctor", "--json"], capsys)
    doctor = json.loads(out)
    assert "checks" in doctor
    assert any(item["name"] == "python" for item in doctor["checks"])
    assert code in {0, 1}

    code, out, _ = run_cli(["benchmark", "feature", "--json"], capsys)
    benchmark = json.loads(out)
    assert code == 0
    assert benchmark["benchmarks"][0]["workflow"] == "feature-development"
    assert benchmark["benchmarks"][0]["success"] is True


def test_cli_unknown_workflow_returns_error(capsys):
    code, _, err = run_cli(["run", "missing-workflow", "--goal", "x", "--json"], capsys)

    assert code == 1
    assert "missing-workflow" in err


def test_pyproject_exposes_loop_entry_point_and_no_setup_py():
    content = open("pyproject.toml", encoding="utf-8").read()

    assert '[project.scripts]' in content
    assert 'loop = "loop_cli.main:main"' in content
    assert "[dependency-groups]" in content
    assert not __import__("pathlib").Path("setup.py").exists()
