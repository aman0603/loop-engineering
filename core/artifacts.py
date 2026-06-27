from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable
from uuid import uuid4


class ArtifactType(str, Enum):
    PLAN = "plan"
    CODE = "implementation"
    REVIEW = "review"
    VERIFICATION = "verification"
    LOG = "log"
    PATCH = "patch"
    DOCUMENTATION = "documentation"
    COMMAND = "command"
    TEST = "test"
    DIFF = "diff"
    BUILD = "build"
    RUNTIME_LOG = "runtime_log"


def artifact_id() -> str:
    return f"artifact_{uuid4().hex}"


@dataclass(frozen=True, slots=True)
class Artifact:
    type: ArtifactType | str
    producer: str
    content: Any
    metadata: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=artifact_id)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        artifact_type = self.type.value if isinstance(self.type, ArtifactType) else self.type
        return {
            "id": self.id,
            "type": artifact_type,
            "producer": self.producer,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
            "content": self.content,
        }


class PlanArtifact(Artifact):
    def __init__(self, producer: str, content: Any, **metadata: Any) -> None:
        super().__init__(ArtifactType.PLAN, producer, content, metadata)


class CodeArtifact(Artifact):
    def __init__(self, producer: str, content: Any, **metadata: Any) -> None:
        super().__init__(ArtifactType.CODE, producer, content, metadata)


class ReviewArtifact(Artifact):
    def __init__(self, producer: str, content: Any, **metadata: Any) -> None:
        super().__init__(ArtifactType.REVIEW, producer, content, metadata)


class VerificationArtifact(Artifact):
    def __init__(self, producer: str, content: Any, **metadata: Any) -> None:
        super().__init__(ArtifactType.VERIFICATION, producer, content, metadata)


class LogArtifact(Artifact):
    def __init__(self, producer: str, content: Any, **metadata: Any) -> None:
        super().__init__(ArtifactType.LOG, producer, content, metadata)


class PatchArtifact(Artifact):
    def __init__(self, producer: str, content: Any, **metadata: Any) -> None:
        super().__init__(ArtifactType.PATCH, producer, content, metadata)


class DocumentationArtifact(Artifact):
    def __init__(self, producer: str, content: Any, **metadata: Any) -> None:
        super().__init__(ArtifactType.DOCUMENTATION, producer, content, metadata)


class CommandArtifact(Artifact):
    def __init__(self, producer: str, content: Any, **metadata: Any) -> None:
        super().__init__(ArtifactType.COMMAND, producer, content, metadata)


class TestArtifact(Artifact):
    def __init__(self, producer: str, content: Any, **metadata: Any) -> None:
        super().__init__(ArtifactType.TEST, producer, content, metadata)


class DiffArtifact(Artifact):
    def __init__(self, producer: str, content: Any, **metadata: Any) -> None:
        super().__init__(ArtifactType.DIFF, producer, content, metadata)


class BuildArtifact(Artifact):
    def __init__(self, producer: str, content: Any, **metadata: Any) -> None:
        super().__init__(ArtifactType.BUILD, producer, content, metadata)


class RuntimeLogArtifact(Artifact):
    def __init__(self, producer: str, content: Any, **metadata: Any) -> None:
        super().__init__(ArtifactType.RUNTIME_LOG, producer, content, metadata)


class ArtifactStore:
    def __init__(self, artifacts: Iterable[Artifact] | None = None) -> None:
        self._artifacts: dict[str, Artifact] = {}
        self._by_type: dict[str, list[str]] = {}
        for artifact in artifacts or []:
            self.add(artifact)

    def add(self, artifact: Artifact) -> Artifact:
        artifact_type = self._type_key(artifact.type)
        self._artifacts[artifact.id] = artifact
        self._by_type.setdefault(artifact_type, []).append(artifact.id)
        return artifact

    def add_content(
        self,
        artifact_type: ArtifactType | str,
        producer: str,
        content: Any,
        metadata: dict[str, Any] | None = None,
    ) -> Artifact:
        return self.add(Artifact(artifact_type, producer, content, metadata or {}))

    def get(self, artifact_id: str) -> Artifact | None:
        return self._artifacts.get(artifact_id)

    def latest(self, artifact_type: ArtifactType | str) -> Artifact | None:
        ids = self._by_type.get(self._type_key(artifact_type), [])
        if not ids:
            return None
        return self._artifacts[ids[-1]]

    def latest_content(self, artifact_type: ArtifactType | str, default: Any = None) -> Any:
        artifact = self.latest(artifact_type)
        return artifact.content if artifact is not None else default

    def by_type(self, artifact_type: ArtifactType | str) -> list[Artifact]:
        return [self._artifacts[item] for item in self._by_type.get(self._type_key(artifact_type), [])]

    def list(self) -> list[Artifact]:
        return list(self._artifacts.values())

    def compatibility_view(self) -> dict[str, Any]:
        return {
            artifact_type: self._artifacts[ids[-1]].content
            for artifact_type, ids in self._by_type.items()
            if ids
        }

    def __contains__(self, artifact_type: object) -> bool:
        if not isinstance(artifact_type, (str, ArtifactType)):
            return False
        return bool(self._by_type.get(self._type_key(artifact_type), []))

    @staticmethod
    def _type_key(artifact_type: ArtifactType | str) -> str:
        return artifact_type.value if isinstance(artifact_type, ArtifactType) else artifact_type
