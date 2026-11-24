import re
from dataclasses import dataclass
from typing import cast

from m3_pipeline.refs.models import Body, Kind


@dataclass(frozen=True)
class SubjectRef:
    subject: str
    kind: Kind
    generation: str | None
    body: Body | None
    part_id: str | None


def parse_subject(subject: str) -> SubjectRef:
    if m := re.fullmatch(r"product-(?P<part>[a-z0-9]+(-[a-z0-9]+)*)", subject):
        return SubjectRef(subject, "product", None, None, m["part"])
    if m := re.fullmatch(
        r"(?P<gen>[a-z0-9]+)-(?P<body>coupe|convertible|sedan)(?P<int>-interior)?", subject
    ):
        return SubjectRef(
            subject,
            "interior" if m["int"] else "base-car",
            m["gen"],
            cast(Body, m["body"]),
            None,
        )
    raise ValueError(f"invalid subject {subject!r}")
