"""Compatibility exports for GitLab dashboard policy-note authorization."""

from zeroone_ops.services.control_plane.policy.gitlab_policy_note_authorization_service import (
    GitLabPolicyNoteAuthorizationService,
    GitLabPolicyNotePermissionLookup,
)

__all__ = ["GitLabPolicyNoteAuthorizationService", "GitLabPolicyNotePermissionLookup"]
