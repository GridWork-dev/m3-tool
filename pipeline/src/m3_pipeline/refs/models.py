from dataclasses import dataclass
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

Kind = Literal["base-car", "interior", "product"]
Body = Literal["coupe", "convertible", "sedan"]
Trim = Literal["standard", "csl", "cs", "gtr", "unknown"]
SourceKind = Literal["commons", "local", "crawl"]
Status = Literal["new", "labeled", "duplicate"]
View = Literal[
    "front",
    "rear",
    "side_left",
    "side_right",
    "front_34_left",
    "front_34_right",
    "rear_34_left",
    "rear_34_right",
    "top",
    "interior_dash",
    "interior_gauges",
    "interior_seats",
    "interior_door",
    "interior_console",
    "interior_steering",
    "product_front",
    "product_side",
    "product_34",
    "product_detail",
    "detail",
    "other",
]


class Labels(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    generation: str = Field(pattern=r"^[a-z0-9]{2,8}$")
    body: Body | Literal["unknown"]
    market: Literal["us", "euro", "unknown"]
    stock: bool | None
    view: View
    drive_side: Literal["lhd", "rhd", "unknown"]
    trim: Trim
    occlusion: Literal["none", "minor", "major"]
    quality: int = Field(ge=1, le=5)
    seat: Literal["driver", "passenger", "both", "unknown"] = "unknown"
    notes: str = ""


class ImageRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str = Field(pattern=r"^[0-9a-f]{64}$")
    subject: str
    source_kind: SourceKind
    source_url: str | None
    page_url: str | None
    author: str | None
    license_short: str = "unknown"
    license_url: str | None = None
    source_note: str | None = None
    retrieved_at: AwareDatetime
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    ext: Literal["jpg", "png", "webp", "avif"]
    phash: str = Field(pattern=r"^[0-9a-f]{16}$")
    status: Status = "new"
    duplicate_of: str | None = None
    seen_urls: list[str] = Field(default_factory=list)
    labels: Labels | None = None


@dataclass(frozen=True)
class Source:
    kind: SourceKind
    source_url: str | None
    page_url: str | None
    author: str | None
    license_short: str = "unknown"
    license_url: str | None = None
    source_note: str | None = None
