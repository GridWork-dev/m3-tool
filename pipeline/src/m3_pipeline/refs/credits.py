from m3_pipeline.refs.viewsets import ViewSet


def render_credits(viewset: ViewSet) -> str:
    records = {entry.image_id: entry for entry in viewset.entries()}
    lines: list[str] = []
    other = 0
    for entry in records.values():
        if entry.source_kind != "commons":
            other += 1
            continue
        author = entry.author or "Author unknown (see file page)"
        license_url = entry.license_url or "no license URL"
        lines.append(f"- {author} - {entry.license_short} ({license_url}) - {entry.page_url}")
    if other:
        lines.append(f"Not credited: {other} non-Commons images in this set.")
    return "\n".join(lines) + ("\n" if lines else "")
