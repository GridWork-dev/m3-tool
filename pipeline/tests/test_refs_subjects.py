import pytest

from m3_pipeline.refs.subjects import parse_subject


@pytest.mark.parametrize(
    "s,kind,gen,body,part",
    [
        ("e46-coupe", "base-car", "e46", "coupe", None),
        ("e46-coupe-interior", "interior", "e46", "coupe", None),
        ("product-wheel-a", "product", None, None, "wheel-a"),
    ],
)
def test_parse_subject(
    s: str, kind: str, gen: str | None, body: str | None, part: str | None
) -> None:
    r = parse_subject(s)
    assert (r.kind, r.generation, r.body, r.part_id) == (kind, gen, body, part)


def test_parse_subject_rejects_other_shapes() -> None:
    with pytest.raises(ValueError):
        parse_subject("E46 Coupe")
