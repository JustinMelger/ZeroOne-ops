"""Render the GitLab policy issue body."""

from zeroone_ops.services.control_plane.policy.github_policy_issue_renderer import (
    GitHubPolicyIssueRenderer,
)


class GitLabPolicyIssueRenderer(GitHubPolicyIssueRenderer):
    """Render the compact machine-owned GitLab policy issue body.

    Policy Markdown is provider-neutral; GitLab-specific behavior is limited to
    issue transport, note authorization, and command polling.
    """
