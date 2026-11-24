import pytest
from refs_helpers import ingest, make_image_bytes, make_labels, make_record, resize_bytes

from m3_pipeline.refs.dedupe import apply_dedupe, find_duplicates
from m3_pipeline.refs.store import RefStore


def test_find_duplicates_keeps_larger_and_marks_resize(store: RefStore) -> None:
    big = ingest(store, make_image_bytes(3))
    small = ingest(store, resize_bytes(make_image_bytes(3), (500, 400)))
    other = ingest(store, make_image_bytes(9))
    d = find_duplicates(store.records())
    assert d == {small.id: big.id} and other.id not in d


@pytest.mark.parametrize("bits,dup", [(6, True), (7, False)])
def test_threshold_boundary(bits: int, dup: bool) -> None:
    a = make_record(id="a" * 64, phash="0" * 16)
    b = make_record(id="b" * 64, phash=format((1 << bits) - 1, "016x"), width=900, height=700)
    assert bool(find_duplicates([a, b])) is dup


def test_result_is_order_independent_and_scoped_per_subject() -> None:
    a = make_record(id="a" * 64, phash="0" * 16)
    b = make_record(id="b" * 64, phash="0" * 16, width=500, height=400)
    c = make_record(id="c" * 64, phash="0" * 16, subject="e46-coupe-interior")
    assert find_duplicates([a, b, c]) == find_duplicates([c, b, a]) == {b.id: a.id}


def test_equal_size_ties_break_by_lower_id() -> None:
    a, b = make_record(id="a" * 64), make_record(id="b" * 64)
    assert find_duplicates([b, a]) == {b.id: a.id}


def test_apply_dedupe_sets_status_keeps_labels_and_is_idempotent(store: RefStore) -> None:
    big = ingest(store, make_image_bytes(3))
    small = ingest(store, resize_bytes(make_image_bytes(3), (500, 400))).model_copy(
        update={"labels": make_labels(), "status": "labeled"}
    )
    store.update([big, small])
    report = apply_dedupe(store)
    saved = store.get(small.id)
    assert report.changed == report.duplicates == 1
    assert saved is not None and saved.status == "duplicate" and saved.duplicate_of == big.id
    assert saved.labels == small.labels
    assert apply_dedupe(store).changed == 0


def test_apply_dedupe_restores_status_when_the_winner_set_changes(store: RefStore) -> None:
    # A~B and B~C, but A is not near C. A new larger A frees the former B loser C.
    b = make_record(id="b" * 64, phash="000000000000003f", labels=make_labels(), status="labeled")
    c = make_record(
        id="c" * 64,
        phash="0000000000000fff",
        width=500,
        height=400,
        labels=make_labels(),
        status="labeled",
    )
    store.update([b, c])
    apply_dedupe(store)
    loser = store.get(c.id)
    assert loser is not None and loser.status == "duplicate"
    a = make_record(id="a" * 64, phash="0" * 16, width=2000, height=1600)
    store.update([a, *store.records()])
    assert apply_dedupe(store).changed == 2
    saved = store.get(c.id)
    assert saved is not None and saved.status == "labeled" and saved.duplicate_of is None
    assert saved.labels == c.labels
