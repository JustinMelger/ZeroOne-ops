"""Projection clients stay lazy and construction failures retain caller ownership."""

from unittest.mock import Mock

import pytest

from zeroone_ops.models.config import AppConfig
from zeroone_ops.services.workflows import provider_workflow_builders
from zeroone_ops.settings import SettingsError


@pytest.mark.parametrize("platform", ["github", "gitlab"])
@pytest.mark.parametrize("failure", [None, "settings", "client", "projection"])
def test_projection_factory_defers_access_and_does_not_cache(monkeypatch, platform, failure):
    config = AppConfig.model_validate(
        {
            "platform": platform,
            platform: {},
            "base_branch": "main",
            "remediation": {"target_branch": "main"},
        }
    )
    settings = Mock(return_value=object())
    client = Mock()
    facade = Mock()
    projection = Mock()
    dependencies = {"settings": settings, "client": client, "projection": projection}
    if failure is not None:
        dependencies[failure].side_effect = SettingsError("Unavailable")
    name = "GitHub" if platform == "github" else "GitLab"
    monkeypatch.setattr(provider_workflow_builders, f"load_{platform}_connection_config", settings)
    monkeypatch.setattr(provider_workflow_builders, f"{name}WorkItemClient", client)
    monkeypatch.setattr(provider_workflow_builders, f"{name}WorkItemService", facade)
    monkeypatch.setattr(provider_workflow_builders, f"{name}ReviewProjectionService", projection)

    factory = provider_workflow_builders.build_review_projection_factory(config)

    for dependency in (settings, client, facade, projection):
        dependency.assert_not_called()
    if failure is not None:
        with pytest.raises(SettingsError, match="Unavailable"):
            factory()
        return
    assert factory() is projection.return_value
    assert factory() is projection.return_value
    assert (
        settings.call_count == client.call_count == facade.call_count == projection.call_count == 2
    )
    client.assert_called_with(settings.return_value)
    facade.assert_called_with(client.return_value)
    assert projection.call_args.args == (facade.return_value,)
