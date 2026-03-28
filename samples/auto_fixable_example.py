"""Small sample module used for local dry-run SonarQube fixture testing."""


def is_enabled(enabled: bool) -> bool:
    """Return whether the feature is enabled."""
    if enabled == True:
        return True
    return False
