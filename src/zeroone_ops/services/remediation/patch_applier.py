"""Patch application service.

This module validates and applies unified diff patches to the local git
repository.
"""

from __future__ import annotations

import re

# Bandit: this service intentionally uses subprocess for trusted git CLI patch operations.
import subprocess  # nosec B404
import tempfile
from pathlib import Path, PurePosixPath

from zeroone_ops.models.analysis import PatchProposal


class PatchApplyError(RuntimeError):
    """Raised when a proposed patch cannot be applied safely."""


class PatchApplier:
    """Validate and apply unified diff patches.

    Args:
        repo_root: Repository root where patch application will run.
    """

    def __init__(self, repo_root: Path) -> None:
        """Initialize the patch applier.

        Args:
            repo_root: Repository root where patch application will run.
        """
        self.repo_root = repo_root

    def apply(self, proposal: PatchProposal) -> None:
        """Validate and apply a patch proposal.

        Args:
            proposal: Proposed patch to apply.

        Raises:
            PatchApplyError: If the patch is unsafe or cannot be applied.
        """
        self._validate_patch_paths(proposal.files_touched)
        self._ensure_git_repository()
        self._validate_diff_structure(proposal)
        self._run_git_apply(proposal.unified_diff)

    def validate(self, proposal: PatchProposal) -> None:
        """Validate a patch proposal without applying it.

        Args:
            proposal: Proposed patch to validate.

        Raises:
            PatchApplyError: If the patch is unsafe or malformed.
        """
        self._validate_patch_paths(proposal.files_touched)
        self._validate_diff_structure(proposal)

    def _validate_patch_paths(self, files_touched: list[str]) -> None:
        """Validate patch paths stay inside the repository.

        Args:
            files_touched: Paths declared by the patch proposal.

        Raises:
            PatchApplyError: If any path is unsafe.
        """
        if not files_touched:
            raise PatchApplyError("Patch proposal does not declare any touched files.")

        for file_path in files_touched:
            posix_path = PurePosixPath(file_path)
            if posix_path.is_absolute():
                raise PatchApplyError(f"Patch path must be relative: {file_path}")
            if ".." in posix_path.parts:
                raise PatchApplyError(f"Patch path escapes repository root: {file_path}")
            resolved_path = (self.repo_root / Path(posix_path)).resolve()
            repo_root_resolved = self.repo_root.resolve()
            if (
                repo_root_resolved not in resolved_path.parents
                and resolved_path != repo_root_resolved
            ):
                raise PatchApplyError(f"Patch path escapes repository root: {file_path}")

    def _ensure_git_repository(self) -> None:
        """Verify the target directory is a git repository.

        Raises:
            PatchApplyError: If the repository check fails.
        """
        # Repository checks intentionally invoke the trusted local git CLI with explicit argv.
        completed = subprocess.run(  # nosec B603 B607
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=self.repo_root,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0 or completed.stdout.strip() != "true":
            raise PatchApplyError("Patch application requires a git repository.")

    def _run_git_apply(self, unified_diff: str) -> None:
        """Apply a unified diff with git.

        Args:
            unified_diff: Unified diff content.

        Raises:
            PatchApplyError: If git apply fails.
        """
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".diff",
            dir=self.repo_root,
            delete=False,
        ) as handle:
            handle.write(unified_diff)
            temp_path = Path(handle.name)

        try:
            # Patch application intentionally invokes the trusted
            # local git CLI on a local temp diff.
            completed = subprocess.run(  # nosec B603 B607
                ["git", "apply", "--reject", "--whitespace=nowarn", str(temp_path)],
                cwd=self.repo_root,
                check=False,
                capture_output=True,
                text=True,
            )
        finally:
            temp_path.unlink(missing_ok=True)

        if completed.returncode != 0:
            message = completed.stderr.strip() or completed.stdout.strip() or "git apply failed."
            raise PatchApplyError(message)

    def _validate_diff_structure(self, proposal: PatchProposal) -> None:
        """Perform basic structural validation for a unified diff.

        Args:
            proposal: Patch proposal to validate.

        Raises:
            PatchApplyError: If the diff structure is malformed.
        """
        lines = proposal.unified_diff.splitlines()
        if not lines:
            raise PatchApplyError("Malformed unified diff: patch content is empty.")
        if not lines[0].startswith("diff --git "):
            raise PatchApplyError("Malformed unified diff: missing `diff --git` header.")

        declared_files = set(proposal.files_touched)
        seen_files: set[str] = set()
        index = 0
        while index < len(lines):
            line = lines[index]
            if not line.startswith("diff --git "):
                raise PatchApplyError(
                    "Malformed unified diff: each file section must start with `diff --git`."
                )
            diff_path = _parse_diff_git_path(line)
            index += 1
            if index < len(lines) and lines[index].startswith(
                (
                    "GIT binary patch",
                    "Binary files ",
                    "similarity index ",
                    "rename from ",
                    "rename to ",
                    "copy from ",
                    "copy to ",
                    "new file mode ",
                    "deleted file mode ",
                )
            ):
                raise PatchApplyError(
                    "Malformed unified diff: only in-place text edits are supported."
                )
            if index >= len(lines) or not lines[index].startswith("--- "):
                raise PatchApplyError("Malformed unified diff: missing `---` file header.")
            old_path = _parse_file_header_path(lines[index], prefix="--- ", side="a")
            index += 1
            if index >= len(lines) or not lines[index].startswith("+++ "):
                raise PatchApplyError("Malformed unified diff: missing `+++` file header.")
            new_path = _parse_file_header_path(lines[index], prefix="+++ ", side="b")
            if old_path != diff_path or new_path != diff_path:
                raise PatchApplyError(
                    "Malformed unified diff: diff and file headers must describe the same path."
                )
            seen_files.add(diff_path)
            index += 1
            saw_hunk = False
            while index < len(lines) and not lines[index].startswith("diff --git "):
                header = lines[index]
                if not header.startswith("@@ "):
                    raise PatchApplyError("Malformed unified diff: missing `@@` hunk header.")
                old_expected, new_expected = _parse_hunk_header(header)
                index += 1
                old_actual = 0
                new_actual = 0
                body_lines = 0
                while index < len(lines) and not lines[index].startswith(("diff --git ", "@@ ")):
                    body_line = lines[index]
                    if body_line.startswith("\\ No newline at end of file"):
                        index += 1
                        continue
                    if not body_line or body_line[0] not in {" ", "+", "-"}:
                        raise PatchApplyError(
                            "Malformed unified diff: invalid hunk body line prefix."
                        )
                    if body_line[0] in {" ", "-"}:
                        old_actual += 1
                    if body_line[0] in {" ", "+"}:
                        new_actual += 1
                    body_lines += 1
                    index += 1
                if body_lines == 0:
                    raise PatchApplyError("Malformed unified diff: empty hunk body.")
                if old_actual != old_expected or new_actual != new_expected:
                    raise PatchApplyError(
                        "Malformed unified diff: hunk header line counts do not match body."
                    )
                saw_hunk = True
            if not saw_hunk:
                raise PatchApplyError("Malformed unified diff: file section has no hunks.")
        self._validate_patch_paths(list(seen_files))
        if declared_files != seen_files:
            missing_files = ", ".join(sorted(declared_files - seen_files))
            unexpected_files = ", ".join(sorted(seen_files - declared_files))
            details = []
            if missing_files:
                details.append(f"missing {missing_files}")
            if unexpected_files:
                details.append(f"unexpected {unexpected_files}")
            raise PatchApplyError(
                "Malformed unified diff: files_touched must exactly match diff content "
                f"({'; '.join(details)})."
            )


_HUNK_HEADER_RE = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? "
    r"\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@"
)


def _parse_hunk_header(line: str) -> tuple[int, int]:
    """Parse unified diff hunk counts from a header line."""
    match = _HUNK_HEADER_RE.match(line)
    if match is None:
        raise PatchApplyError("Malformed unified diff: invalid `@@` hunk header.")
    old_count = match.group("old_count")
    new_count = match.group("new_count")
    return int(old_count or "1"), int(new_count or "1")


def _parse_diff_git_path(line: str) -> str:
    """Parse the repository-relative path from a `diff --git` header."""
    if '"' in line:
        raise PatchApplyError("Malformed unified diff: quoted paths are not supported.")
    parts = line.split()
    if len(parts) != 4:
        raise PatchApplyError("Malformed unified diff: invalid `diff --git` header.")
    left = parts[2]
    right = parts[3]
    if not left.startswith("a/") or not right.startswith("b/"):
        raise PatchApplyError(
            "Malformed unified diff: expected `a/` and `b/` paths in diff header."
        )
    if left[2:] != right[2:]:
        raise PatchApplyError("Malformed unified diff: renames are not supported.")
    return left[2:]


def _parse_file_header_path(line: str, *, prefix: str, side: str) -> str:
    """Return one unambiguous in-place file-header path."""
    value = line.removeprefix(prefix)
    if value == "/dev/null":
        raise PatchApplyError(
            "Malformed unified diff: file additions and deletions are not supported."
        )
    if "\t" in value or " " in value or value.startswith('"'):
        raise PatchApplyError("Malformed unified diff: ambiguous file headers are not supported.")
    expected_prefix = f"{side}/"
    if not value.startswith(expected_prefix):
        raise PatchApplyError(
            f"Malformed unified diff: expected `{expected_prefix}` path in file header."
        )
    return value[len(expected_prefix) :]
