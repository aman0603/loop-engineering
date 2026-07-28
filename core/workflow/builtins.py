from __future__ import annotations

from core.planning import RetryPolicy
from core.workflow.library import EngineeringWorkflowDefinition, WorkflowStepSpec


def built_in_workflows() -> list[EngineeringWorkflowDefinition]:
    return [
        _feature_development(),
        _bug_fix(),
        _refactoring(),
        _code_review(),
        _documentation(),
        _test_generation(),
        _dependency_upgrade(),
        _benchmark(),
    ]


def _step(
    id: str,
    description: str,
    capability: str,
    dependencies: list[str] | None = None,
    artifacts: list[str] | None = None,
    workflow: str | None = None,
    retry: int = 1,
    approval: bool = False,
) -> WorkflowStepSpec:
    return WorkflowStepSpec(
        id=id,
        description=description,
        capability=capability,
        dependencies=dependencies or [],
        expected_artifacts=artifacts or [],
        workflow=workflow,
        retry_policy=RetryPolicy(max_attempts=retry),
        approval=approval,
    )


def _feature_development() -> EngineeringWorkflowDefinition:
    return EngineeringWorkflowDefinition(
        name="feature-development",
        metadata={"title": "Feature Development", "description": "Plan, build, verify, review, and document a feature."},
        parameters={"verification": "standard", "human_review": "optional", "max_retries": 2},
        verification_stages=["tests"],
        approval_stages=[],
        outputs=["implementation", "test", "review", "documentation"],
        steps=[
            _step("planning", "Plan feature for {goal}", "planning", artifacts=["plan"]),
            _step("architecture", "Design architecture for {goal}", "architecture", ["planning"], ["documentation"]),
            _step("implementation", "Implement {goal}", "coding", ["architecture"], ["implementation"], retry=2),
            _step("tests", "Test {goal}", "testing", ["implementation"], ["test"], retry=2),
            _step("documentation", "Run documentation workflow", "documentation", ["tests"], ["documentation"], workflow="documentation"),
            _step("review", "Run code review workflow", "review", ["documentation"], ["review"], workflow="code-review"),
            _step("complete", "Complete feature workflow", "planning", ["review"], ["log"]),
        ],
    )


def _bug_fix() -> EngineeringWorkflowDefinition:
    return EngineeringWorkflowDefinition(
        name="bug-fix",
        metadata={"title": "Bug Fix", "description": "Reproduce, investigate, patch, test, and review a bug fix."},
        parameters={"priority": "normal", "max_retries": 2, "verification": "standard"},
        verification_stages=["tests", "regression-tests"],
        outputs=["patch", "test", "review"],
        steps=[
            _step("reproduce", "Reproduce bug for {goal}", "testing", artifacts=["test"]),
            _step("investigation", "Investigate failure", "debugging", ["reproduce"], ["documentation"]),
            _step("root-cause", "Identify root cause", "debugging", ["investigation"], ["documentation"]),
            _step("patch", "Patch root cause", "coding", ["root-cause"], ["patch", "implementation"], retry=2),
            _step("tests", "Run bug fix tests", "testing", ["patch"], ["test"], retry=2),
            _step("regression-tests", "Run regression tests", "testing", ["tests"], ["test"], retry=2),
            _step("review", "Review bug fix", "review", ["regression-tests"], ["review"]),
        ],
    )


def _refactoring() -> EngineeringWorkflowDefinition:
    return EngineeringWorkflowDefinition(
        name="refactoring",
        metadata={"title": "Refactoring", "description": "Analyze, refactor, test, check performance, and review."},
        parameters={"max_retries": 2, "verification": "standard"},
        verification_stages=["tests", "performance"],
        outputs=["patch", "test", "review"],
        steps=[
            _step("analysis", "Analyze refactor scope", "architecture", artifacts=["documentation"]),
            _step("refactor", "Refactor code", "refactoring", ["analysis"], ["patch"], retry=2),
            _step("tests", "Run tests after refactor", "testing", ["refactor"], ["test"], retry=2),
            _step("performance", "Check performance impact", "testing", ["tests"], ["build"]),
            _step("review", "Review refactor", "review", ["performance"], ["review"]),
        ],
    )


def _code_review() -> EngineeringWorkflowDefinition:
    return EngineeringWorkflowDefinition(
        name="code-review",
        metadata={"title": "Code Review", "description": "Run static, security, architecture, complexity, and style review."},
        parameters={"verification": "review"},
        outputs=["review"],
        steps=[
            _step("static-analysis", "Run static analysis", "review", artifacts=["review"]),
            _step("security-review", "Review security risks", "review", ["static-analysis"], ["review"]),
            _step("architecture-review", "Review architecture", "architecture", ["security-review"], ["review"]),
            _step("complexity-review", "Review complexity", "review", ["architecture-review"], ["review"]),
            _step("style-review", "Review style", "review", ["complexity-review"], ["review"]),
            _step("review-report", "Generate review report", "documentation", ["style-review"], ["review", "documentation"]),
        ],
    )


def _documentation() -> EngineeringWorkflowDefinition:
    return EngineeringWorkflowDefinition(
        name="documentation",
        metadata={"title": "Documentation", "description": "Analyze code, generate docs, verify links, and generate examples."},
        parameters={"verification": "links"},
        verification_stages=["verify-links"],
        outputs=["documentation"],
        steps=[
            _step("analyze-code", "Analyze code for documentation", "architecture", artifacts=["documentation"]),
            _step("generate-docs", "Generate documentation", "documentation", ["analyze-code"], ["documentation"]),
            _step("verify-links", "Verify documentation links", "testing", ["generate-docs"], ["test"]),
            _step("generate-examples", "Generate examples", "documentation", ["verify-links"], ["documentation"]),
        ],
    )


def _test_generation() -> EngineeringWorkflowDefinition:
    return EngineeringWorkflowDefinition(
        name="test-generation",
        metadata={"title": "Test Generation", "description": "Analyze code, generate tests, run tests, check coverage, refine."},
        parameters={"coverage_target": 80, "max_retries": 2},
        verification_stages=["run-tests", "coverage-check"],
        outputs=["test"],
        steps=[
            _step("analyze-code", "Analyze code for tests", "architecture", artifacts=["documentation"]),
            _step("generate-tests", "Generate tests", "testing", ["analyze-code"], ["test"], retry=2),
            _step("run-tests", "Run generated tests", "testing", ["generate-tests"], ["test"], retry=2),
            _step("coverage-check", "Check coverage target {coverage_target}", "testing", ["run-tests"], ["test"]),
            _step("refine-tests", "Refine tests", "testing", ["coverage-check"], ["test"], retry=2),
        ],
    )


def _dependency_upgrade() -> EngineeringWorkflowDefinition:
    return EngineeringWorkflowDefinition(
        name="dependency-upgrade",
        metadata={"title": "Dependency Upgrade", "description": "Analyze dependencies, upgrade, test, check compatibility, rollback if needed."},
        parameters={"max_retries": 2, "rollback": "if-needed"},
        verification_stages=["tests", "compatibility-check"],
        outputs=["patch", "test"],
        steps=[
            _step("analyze-dependencies", "Analyze dependencies", "research", artifacts=["documentation"]),
            _step("upgrade", "Upgrade dependencies", "coding", ["analyze-dependencies"], ["patch"], retry=2),
            _step("tests", "Run dependency tests", "testing", ["upgrade"], ["test"], retry=2),
            _step("compatibility-check", "Check compatibility", "testing", ["tests"], ["test"]),
            _step("rollback-if-necessary", "Rollback if necessary", "debugging", ["compatibility-check"], ["patch"]),
        ],
    )


def _benchmark() -> EngineeringWorkflowDefinition:
    return EngineeringWorkflowDefinition(
        name="benchmark",
        metadata={"title": "Benchmark", "description": "Run benchmark checks."},
        outputs=["build"],
        steps=[
            _step("benchmark", "Run benchmark for {goal}", "testing", artifacts=["build"]),
        ],
    )

