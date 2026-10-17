"""Assign a batch identity only when creation is explicitly requested."""

from uuid import uuid4

from zeroone_ops.models.finding_batch import FindingBatchIdentity


def create_finding_batch_identity() -> FindingBatchIdentity:
    """Allocate one UUID4 for callers to retain across the same creation attempt."""
    identifier = uuid4().hex
    return FindingBatchIdentity(
        work_item_id=f"work-{identifier}", source_item_key=f"batch-v1:{identifier}"
    )
