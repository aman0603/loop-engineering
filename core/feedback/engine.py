from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from verification.pipeline import VerificationReport


class FailureCategory(str, Enum):
    VERIFICATION = "verification"
    TEST = "test"
    LINT = "lint"
    TYPECHECK = "typecheck"
    SECURITY = "security"
    BENCHMARK = "benchmark"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class FeedbackItem:
    source: str
    category: FailureCategory
    summary: str
    suggestion: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "category": self.category.value,
            "summary": self.summary,
            "suggestion": self.suggestion,
            "details": self.details,
        }


class FeedbackEngine:
    def from_verification(self, report: VerificationReport) -> list[FeedbackItem]:
        feedback: list[FeedbackItem] = []
        for result in report.failed_results:
            category = self._categorize(result.name)
            feedback.append(
                FeedbackItem(
                    source=result.name,
                    category=category,
                    summary=result.summary,
                    suggestion=self._suggestion_for(category),
                    details=result.details,
                )
            )
        return feedback

    def _categorize(self, check_name: str) -> FailureCategory:
        lowered = check_name.lower()
        for category in FailureCategory:
            if category != FailureCategory.UNKNOWN and category.value in lowered:
                return category
        return FailureCategory.VERIFICATION

    def _suggestion_for(self, category: FailureCategory) -> str:
        suggestions = {
            FailureCategory.TEST: "Inspect failing tests and adjust the implementation or test setup.",
            FailureCategory.LINT: "Apply the project formatting and linting conventions.",
            FailureCategory.TYPECHECK: "Fix type contract mismatches before retrying.",
            FailureCategory.SECURITY: "Remove unsafe data flow or add an explicit guard before retrying.",
            FailureCategory.BENCHMARK: "Measure the regression and choose a lower-cost implementation.",
            FailureCategory.VERIFICATION: "Update the next plan to directly address the failed verification check.",
            FailureCategory.UNKNOWN: "Collect more diagnostic context before retrying.",
        }
        return suggestions[category]

