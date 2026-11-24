# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
from dataclasses import dataclass
from io import BytesIO


@dataclass(frozen=True)
class ImageInfo:
    width: int
    height: int
    ext: str
    phash: str


class UnreadableImage(Exception):
    pass


def inspect_image(data: bytes) -> ImageInfo:
    import imagehash
    from PIL import Image, ImageOps

    try:
        with Image.open(BytesIO(data)) as original:
            fmt = original.format
            extensions = {"JPEG": "jpg", "MPO": "jpg", "PNG": "png", "WEBP": "webp", "AVIF": "avif"}
            if fmt not in extensions:
                raise UnreadableImage(f"unsupported format {fmt}")
            image = ImageOps.exif_transpose(original)
            image.load()
            return ImageInfo(
                image.width, image.height, extensions[fmt], str(imagehash.phash(image))
            )
    except (OSError, Image.DecompressionBombError, SyntaxError) as exc:
        raise UnreadableImage(str(exc)) from exc


def hamming(a: str, b: str) -> int:
    return (int(a, 16) ^ int(b, 16)).bit_count()
