from pathlib import Path

from ai_sonar_bot.models.state import AppState, RepositoryState
from ai_sonar_bot.services.state_store import StateStore


def test_state_store_round_trip(tmp_path: Path) -> None:
    state_path = tmp_path / ".ai-sonar-bot-state.json"
    store = StateStore(
        state_path,
        base_branch="main",
        gitlab_project_id="123",
        sonarqube_project_key="project-key",
    )

    initial = store.load()
    assert isinstance(initial, AppState)

    initial.active_issue_key = "ABC"
    store.save(initial)

    loaded = store.load()
    assert loaded.active_issue_key == "ABC"
    assert loaded.repository == RepositoryState(
        base_branch="main",
        gitlab_project_id="123",
        sonarqube_project_key="project-key",
    )
