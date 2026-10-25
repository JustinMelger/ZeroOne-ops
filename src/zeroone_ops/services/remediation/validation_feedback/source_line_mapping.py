"""Prove unchanged diagnostic locations from actual source contents."""

from collections import Counter
from difflib import SequenceMatcher

from zeroone_ops.models.validation_evidence import SourceChange


def unchanged_line_map(change: SourceChange) -> dict[int, int]:
    """Map old to new lines, rejecting ambiguous relocation of repeated source text."""
    if change.before is None or change.after is None:
        return {}
    before = _source_lines(change.before)
    after = _source_lines(change.after)
    if before == after:
        return {index + 1: index + 1 for index in range(len(before))}

    before_counts, after_counts = Counter(before), Counter(after)
    mapping: dict[int, int] = {}
    for block in SequenceMatcher(None, before, after, autojunk=False).get_matching_blocks():
        for offset in range(block.size):
            old, new = block.a + offset, block.b + offset
            # Repeated text does not prove which occurrence survived an edit.
            if before_counts[before[old]] == after_counts[after[new]] == 1:
                mapping[old + 1] = new + 1
    return mapping


def _source_lines(content: str) -> list[str]:
    """Count physical lines without treating form-feed or Unicode text as newlines."""
    return content.removesuffix("\n").split("\n") if content else []
