import pytest
from refs_helpers import make_labels, make_record

from m3_pipeline.refs.filters import FilterTarget, evaluate
from m3_pipeline.refs.models import Labels

T = FilterTarget("base-car", "e46", "coupe", "standard")


@pytest.mark.parametrize(
    "labels,reason",
    [
        (None, "unlabeled"),
        (make_labels(stock=False), "modified"),
        (make_labels(generation="e36"), "wrong_generation"),
        (make_labels(generation="unknown"), "wrong_generation"),
        (make_labels(body="sedan"), "wrong_body"),
        (make_labels(body="unknown"), "wrong_body"),
        (make_labels(occlusion="major"), "major_occlusion"),
        (make_labels(view="interior_dash"), "wrong_view_family"),
        (make_labels(view="detail"), "wrong_view_family"),
    ],
)
def test_base_car_rejections(labels: Labels | None, reason: str) -> None:
    decision = evaluate(make_record(labels=labels), T)
    assert not decision.accepted and reason in decision.reasons


def test_base_car_accepts_clean_stock_and_tolerates_unknown_stock_and_minor_occlusion() -> None:
    assert all(
        evaluate(make_record(labels=labels), T).accepted
        for labels in (
            make_labels(),
            make_labels(stock=None),
            make_labels(occlusion="minor"),
            make_labels(trim="unknown"),
        )
    )


def test_csl_rejected_for_standard_coupe() -> None:
    d = evaluate(make_record(labels=make_labels(trim="csl")), T)
    assert not d.accepted and d.reasons == ("trim",)
    assert FilterTarget.from_subject("e46-coupe").trim == "standard"
    assert FilterTarget.from_subject("product-wheel-a").trim is None


def test_duplicates_are_rejected_and_reasons_accumulate() -> None:
    d = evaluate(
        make_record(status="duplicate", labels=make_labels(stock=False, generation="e36")), T
    )
    assert not d.accepted and set(d.reasons) == {"duplicate", "modified", "wrong_generation"}


def test_interior_ignores_body_drive_side_and_major_occlusion_but_not_modified_or_generation() -> (
    None
):
    t = FilterTarget.from_subject("e46-coupe-interior")
    labels = make_labels(
        view="interior_gauges", body="convertible", drive_side="rhd", occlusion="major"
    )
    assert evaluate(make_record(labels=labels), t).accepted
    d = evaluate(
        make_record(labels=labels.model_copy(update={"stock": False, "generation": "e36"})), t
    )
    assert not d.accepted and set(d.reasons) == {"modified", "wrong_generation"}


def test_product_only_needs_a_label_a_product_view_and_non_duplicate() -> None:
    t = FilterTarget.from_subject("product-wheel-a")
    labels = make_labels(
        view="product_front",
        generation="unknown",
        body="unknown",
        trim="gtr",
        stock=False,
        occlusion="major",
    )
    assert evaluate(make_record(labels=labels), t).accepted
    assert evaluate(make_record(labels=None), t).reasons == ("unlabeled",)
    assert evaluate(make_record(labels=labels, status="duplicate"), t).reasons == ("duplicate",)
    assert evaluate(make_record(labels=make_labels(view="detail")), t).reasons == (
        "wrong_view_family",
    )
