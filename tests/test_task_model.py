from core.task_manager import JsonTaskRepository, Task, TaskStatus


def test_task_lifecycle_and_json_repository_roundtrip(tmp_path):
    task = Task(
        title="Add endpoint",
        description="Add a health endpoint",
        goal="Health endpoint is available",
        acceptance_criteria=["Endpoint returns success"],
    )
    task.transition_to(TaskStatus.PLANNING)
    task.add_log("planner", "started")

    repository = JsonTaskRepository(tmp_path / "tasks.json")
    repository.save(task)

    loaded = repository.get(task.id)

    assert loaded is not None
    assert loaded.id == task.id
    assert loaded.status == TaskStatus.PLANNING
    assert loaded.execution_logs[0].message == "started"


def test_invalid_task_transition_is_rejected():
    task = Task(title="x", description="x", goal="x")

    try:
        task.transition_to(TaskStatus.DONE)
    except ValueError as exc:
        assert "invalid task transition" in str(exc)
    else:
        raise AssertionError("transition should have failed")

