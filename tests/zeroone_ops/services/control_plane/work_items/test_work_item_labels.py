from zeroone_ops.services.control_plane.work_items.work_item_labels import (
    AUTHORITATIVE_WORK_ITEM_LABEL,
    dismissed_work_item_query_labels,
    render_work_item_labels,
    work_item_source_query_labels,
)

from .test_support import build_work_item


def test_rendered_labels_and_identity_query_share_the_source_index() -> None:
    work_item = build_work_item(status="approved")

    labels = render_work_item_labels(work_item)

    assert labels == [
        AUTHORITATIVE_WORK_ITEM_LABEL,
        "zeroone-status:approved",
        "zeroone-source:sonarqube",
    ]
    assert work_item_source_query_labels(work_item.source.source) == [
        AUTHORITATIVE_WORK_ITEM_LABEL,
        "zeroone-source:sonarqube",
    ]


def test_dismissal_query_uses_the_same_authoritative_and_status_indexes() -> None:
    assert dismissed_work_item_query_labels() == [
        AUTHORITATIVE_WORK_ITEM_LABEL,
        "zeroone-status:dismissed",
    ]
