import pytest
from PIL import features
from refs_helpers import make_image_bytes, resize_bytes

from m3_pipeline.refs.imaging import UnreadableImage, hamming, inspect_image


def test_inspect_reads_size_ext_and_phash() -> None:
    i = inspect_image(make_image_bytes(1))
    assert (i.width, i.height, i.ext) == (1000, 800, "jpg") and len(i.phash) == 16


def test_inspect_ext_comes_from_content() -> None:
    assert inspect_image(make_image_bytes(1, fmt="WEBP")).ext == "webp"


def test_inspect_applies_exif_rotation() -> None:
    i = inspect_image(make_image_bytes(1, exif_orientation=6))
    assert (i.width, i.height) == (800, 1000)


@pytest.mark.skipif(not features.check("avif"), reason="Pillow built without AVIF")
def test_inspect_accepts_avif() -> None:
    assert inspect_image(make_image_bytes(1, fmt="AVIF")).ext == "avif"


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"<html>Too many requests</html>",
        make_image_bytes(1)[:3000],
        b"\x00\x00\x00\x18ftypheic" + b"\0" * 64,
    ],
)
def test_inspect_rejects_undecodable_bytes(data: bytes) -> None:
    with pytest.raises(UnreadableImage):
        inspect_image(data)


def test_inspect_rejects_decodable_but_unsupported_format() -> None:
    with pytest.raises(UnreadableImage, match="GIF"):
        inspect_image(make_image_bytes(1, fmt="GIF"))


def test_phash_is_stable_across_resize_and_hamming_counts_bits() -> None:
    a = inspect_image(make_image_bytes(3))
    b = inspect_image(resize_bytes(make_image_bytes(3), (500, 400)))
    assert hamming(a.phash, b.phash) <= 6 and hamming("0" * 16, "0" * 15 + "f") == 4
