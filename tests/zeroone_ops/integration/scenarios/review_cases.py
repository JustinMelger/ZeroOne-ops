"""Reconstruct frozen review inputs as actual local Git revisions."""

import json
from dataclasses import dataclass, replace
from pathlib import Path

from zeroone_ops.models.review import ReviewFinding

from .repository import git

FIXTURES = Path(__file__).parents[2] / "services/review/pipeline/fixtures/precision_v1"
REVIEW_PATH = "src/subject.py"


@dataclass(frozen=True)
class ReviewCase:
    """Bind reconstructed source, diff, finding, and request identity independently."""

    number: int
    root: Path
    name: str
    before: str
    after: str
    base_sha: str
    head_sha: str
    diff: str
    finding: ReviewFinding

    @property
    def branch(self) -> str:
        """Return the actual local source branch."""
        return f"review/request-{self.number}"

    @property
    def marker(self) -> str:
        """Identify request-specific guidance and source context."""
        return f"OFFLINE_REVIEW_{self.number}"

    @property
    def url(self) -> str:
        """Return the exact synthetic request URL used by verified linkage."""
        return f"https://provider.invalid/offline/application/requests/{self.number}"


def create_review_case(directory: Path, *, number: int, name: str) -> ReviewCase:
    """Reuse frozen snapshots without claiming historical SHAs or model inputs."""
    case = next(
        case for case in json.loads((FIXTURES / "cases.json").read_text()) if case["name"] == name
    )
    root = directory / f"review-{number}"
    source = root / REVIEW_PATH
    source.parent.mkdir(parents=True)
    prefix = f"# OFFLINE_REVIEW_{number}\n"
    before = prefix + (FIXTURES / name / "before.txt").read_text()
    after = prefix + (FIXTURES / name / "after.txt").read_text()
    source.write_text(before, encoding="utf-8")
    (root / "AGENTS.md").write_text(
        f"# Review Expectations\n\n- Check OFFLINE_REVIEW_{number} against the changed code.\n",
        encoding="utf-8",
    )
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Offline Review")
    git(root, "config", "user.email", "offline@example.invalid")
    git(root, "config", "commit.gpgsign", "false")
    git(root, "add", ".")
    git(root, "commit", "-m", "Seed reconstructed review base")
    base_sha = git(root, "rev-parse", "HEAD")
    git(root, "checkout", "-b", f"review/request-{number}")
    source.write_text(after, encoding="utf-8")
    git(root, "add", REVIEW_PATH)
    git(root, "commit", "-m", "Apply reconstructed review change")
    head_sha = git(root, "rev-parse", "HEAD")
    diff = git(root, "diff", "--no-ext-diff", base_sha, head_sha, "--", REVIEW_PATH)
    diff = "\n".join(diff.splitlines()[4:])
    finding = ReviewFinding.model_validate(case["finding"]).model_copy(
        update={
            "file_path": REVIEW_PATH,
            "line_start": case["finding"]["line_start"] + 1,
            "line_end": case["finding"]["line_end"] + 1,
        }
    )
    return ReviewCase(number, root, name, before, after, base_sha, head_sha, diff, finding)


def advance_review_case(previous: ReviewCase, *, after: str, finding: ReviewFinding) -> ReviewCase:
    """Commit another head on the same request, retaining its original merge base."""
    assert git(previous.root, "rev-parse", "HEAD") == previous.head_sha
    (previous.root / REVIEW_PATH).write_text(after, encoding="utf-8")
    git(previous.root, "add", REVIEW_PATH)
    git(previous.root, "commit", "-m", "Advance offline review request")
    head_sha = git(previous.root, "rev-parse", "HEAD")
    diff = git(
        previous.root, "diff", "--no-ext-diff", previous.base_sha, head_sha, "--", REVIEW_PATH
    )
    return replace(
        previous,
        after=after,
        head_sha=head_sha,
        diff="\n".join(diff.splitlines()[4:]),
        finding=finding.model_copy(deep=True),
    )
