# Phase 0B: Photo Tooling (`pipeline refs`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the reference-photo tooling (design section 9.1): collectors, curation, matched view sets, descriptions, R2 sync and a runbook, so the user can run collection on online E46 photos.

**Architecture:** A `m3_pipeline.refs` package behind a Typer sub-app (`pipeline refs ...`) plus one registered stage (`refs`). Every image lives in a private local store (hash-addressed files plus one JSONL manifest) outside the repo. Collectors differ only in how they fetch bytes and what provenance they attach; all go through `RefStore.ingest_bytes`. Curation (dedupe, filter, view-set scoring, description) is pure functions over manifest records, tested with tiny generated images.

**Tech Stack:** Python 3.14 + uv, Typer, pydantic 2.14.4, httpx 0.28.1, Pillow 13.0.0, imagehash 4.3.2, Playwright 1.65.2, rembg 2.0.87 (optional group `bg`), boto3 1.44.9, pytest.

**Spec:** `docs/superpowers/specs/2026-11-23-m3-tool-design.md`

## Global Constraints

- Python `>=3.14,<3.15` via uv. Dev tools stay at ruff 0.17.6, pyright 1.1.414 (strict), pytest 9.2.0; Typer 0.29.2; pyyaml 6.0.4.
- Pins added here, exact: `pydantic==2.14.4`, `httpx==0.28.1`, `pillow==13.0.0`, `imagehash==4.3.2`, `playwright==1.65.2`, `boto3==1.44.9`, `rembg[cpu]==2.0.87` (dependency group `bg` only). If a pin does not resolve on 3.14, stop and report; never change a pin or the Python range.
- Pyright strict stays on. Untyped libraries (imagehash, boto3, rembg) are touched only inside the façade named in each task, with a file-level `# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false`. No other `# type: ignore`.
- Reference photos "stay private (private R2 bucket plus a local cache) and never go in the public repo". Store: `<work_dir>/refs/images/<sha256[:2]>/<sha256>.<ext>` plus `<work_dir>/refs/manifest.jsonl`; `work_dir` is `M3_WORK_DIR` (default `~/.cache/m3-tool`). `RefStore` refuses a `work_dir` inside the repo.
- Collector defaults: respect robots.txt, rate-limit, generic user agent, record source URL, author, license and date for every image. Blocked pages are logged and skipped. No features for getting past bot blocking: no stealth plugins, proxy rotation, captcha solving or browser UA spoofing in any code path. Browserbase sessions turn captcha solving, proxies and stealth/fingerprint options off explicitly.
- Default User-Agent everywhere: `m3-tool-refs/0.1 (+https://github.com/GridWork-dev/m3-tool)`; configurable (`refs-sources.toml` `[http] user_agent`, env `M3_REFS_USER_AGENT`); no personal email; always sent, including from Playwright.
- Commons: MediaWiki API through httpx; `maxlag=5`; one request at a time; 3 s between requests by default (floor 1 s), through one limiter shared by API calls and thumbnail downloads; page size 50 (`gcmlimit=50`); thumbnails at `iiurlwidth=1920` (a standard Wikimedia step; 2560 is not one); `Retry-After` honored with capped, backed-off retries and a log line. Category names and search terms come only from `pipeline/refs-sources.toml` and are never hard-coded.
- Crawler: robots.txt checked with the UA before every page and image; 3 s per host by default; keep images with min side >= 800 px; HTTP 403/429 or a challenge page is blocked (log, skip, retry once at most).
- Curation constants: pHash Hamming distance <= 6 is a duplicate (keep the larger image); classify batches of 40; a labeled trim other than the target's (`standard` for `e46-coupe`) is rejected, `unknown` passes; up to 5 views per exterior or product set and per interior component (six components; one with fewer than 3 views is reported missing); exterior priority `front_34_left`, `rear_34_right`, `side_left`, `front`, `rear`. Interior mirroring is per component: RHD steering, gauge-cluster, console and seat photos are used as-is; an RHD whole dash or door is used only as `mirrored: true` with `contains_text_risk: true`; steering and gauge images are never mirrored. The car is left-hand drive.
- Secrets come from env only: `M3_R2_ACCOUNT_ID`, `M3_R2_ACCESS_KEY_ID`, `M3_R2_SECRET_ACCESS_KEY`, `M3_BROWSERBASE_API_KEY`, `M3_BROWSERBASE_PROJECT_ID`. Never print, log or store a value; the Browserbase `connectUrl` embeds the key, so it is never logged. Never use `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`. Test credentials are obviously fake (`test-key`).
- Tests reach no network beyond 127.0.0.1 and use generated images, never real photos. Public repo: conventional commits; no `Claude-Session` trailers or session URLs in commits or PR bodies; gitleaks runs in CI and pre-push; `main` is protected.
- **Landing (every task):** before Step 1 run `git switch main && git pull --ff-only && git switch -c feat/refs-<slug>`; after the commit step run `git push -u origin HEAD && gh pr create --title "<commit subject>" --body "<what changed, how tested>"`. Gate: `pnpm check:pipeline` exits 0.

## Review Focus

Failure modes the spec implies and no happy path covers, most likely first. Each has a named test in its owning task.

1. Commons pages that arrive incomplete: no `imageinfo` (continuation batches), no `extmetadata`, empty license or artist. Expect merge by title, skip without a crash, license `unknown`, author `None`, and the set's `all_cc_or_pd` false. Task 2 `test_collect_survives_continuation_batches_without_imageinfo`, `test_missing_extmetadata_gives_unknown_license`; Task 8 `test_unknown_license_blocks_all_cc_or_pd`.
2. A run killed mid-way then resumed: orphan image file, torn last manifest line, corrupt middle line. Expect resume without duplicates, torn tail dropped, corrupt middle line refused (never silently dropped or overwritten). Task 1 `test_resume_after_crash_between_file_write_and_manifest_append`, `test_torn_last_manifest_line_is_dropped_and_manifest_stays_appendable`, `test_corrupt_middle_manifest_line_raises_with_line_number`.
3. Local imports of WebP, AVIF, HEIC, EXIF-rotated, wrongly named or undecodable files (an HTML error page saved as `.jpg`). Expect extension from content, rotation applied to size and hash, bad files reported and skipped, the rest imported. Task 1 `test_inspect_*`; Task 3 `test_import_continues_past_bad_files_and_reports_them`.
4. The same photo via two collectors, or at two URLs and sizes. Expect one record, one file, and a known license replacing an `unknown` one. Task 1 `test_second_collector_same_bytes_keeps_one_record_and_upgrades_unknown_license`; Task 7 `test_find_duplicates_keeps_larger_and_marks_resize`.
5. Wikimedia pushing back mid-run (maxlag error inside a 200 body, 429 with `Retry-After`, rejected thumbnail widths). Expect bounded backoff, a clean stop with progress kept, and a message naming the cause. Task 2 `test_maxlag_error_in_body_waits_then_retries`, `test_429_with_retry_after_sleeps_via_the_injected_clock_then_succeeds`, `test_429_exhausts_retries_and_stops_cleanly`, `test_thumbnail_step_rejection_stops_with_config_hint`.

## File Structure
```
pipeline/refs-sources.toml, pipeline/descriptions/<subject>.md           user-edited config; optional hand-written notes (Tasks 2, 9)
pipeline/src/m3_pipeline/refs/   Task 1: models subjects manifest imaging store | 2: throttle sources commons | 3: importer | 4-5: crawl/{robots,blocked,extract,engine,fetchers,browserbase}
                                 6: classify | 7: dedupe filters cutouts | 8: viewsets credits | 9: description | 10: sync | cli.py (thin wrappers, grows per task)
pipeline/src/m3_pipeline/stages/refs.py (Task 9)   pipeline/tests/{conftest,refs_helpers,refs_fakes,refs_site}.py + test_refs_*.py + fixtures/refs/   docs/runbooks/refs-collection.md (Task 10)
```

### Task 1: Records, manifest and store
**Files** (branch `feat/refs-store`):
- Modify: `pipeline/pyproject.toml` (`uv add pydantic==2.14.4 pillow==13.0.0 imagehash==4.3.2`; register pytest marker `browser`), `pipeline/src/m3_pipeline/cli.py` (`app.add_typer(refs_app, name="refs")`)
- Create: `pipeline/src/m3_pipeline/refs/{__init__,models,subjects,manifest,imaging,store,cli}.py`
- Create: `pipeline/tests/{conftest.py,refs_helpers.py,test_refs_subjects.py,test_refs_imaging.py,test_refs_manifest.py,test_refs_store.py}`

**Interfaces:**
- Consumes: `Settings` (`config.py`), `app` (`cli.py`).
- Produces:
```python
# models.py (pydantic, frozen, extra="forbid")
Kind = Literal["base-car","interior","product"]; Body = Literal["coupe","convertible","sedan"]
Trim = Literal["standard","csl","cs","gtr","unknown"]
SourceKind = Literal["commons","local","crawl"]; Status = Literal["new","labeled","duplicate"]
View = Literal["front","rear","side_left","side_right","front_34_left","front_34_right","rear_34_left","rear_34_right","top",
  "interior_dash","interior_gauges","interior_seats","interior_door","interior_console","interior_steering",
  "product_front","product_side","product_34","product_detail","detail","other"]
class Labels(BaseModel): generation: str  # ^[a-z0-9]{2,8}$, "unknown" allowed
    body: Body | Literal["unknown"]; market: Literal["us","euro","unknown"]; stock: bool | None; view: View
    drive_side: Literal["lhd","rhd","unknown"]; trim: Trim; occlusion: Literal["none","minor","major"]; quality: int  # 1..5
    seat: Literal["driver","passenger","both","unknown"] = "unknown"   # role of the seat shown; meaningful for interior_seats
    notes: str = ""
class ImageRecord(BaseModel): id: str  # sha256 hex of stored bytes
    subject: str; source_kind: SourceKind; source_url: str | None; page_url: str | None; author: str | None
    license_short: str = "unknown"; license_url: str | None = None; source_note: str | None = None
    retrieved_at: AwareDatetime; width: int; height: int; ext: Literal["jpg","png","webp","avif"]; phash: str  # 16 hex
    status: Status = "new"; duplicate_of: str | None = None; seen_urls: list[str] = []; labels: Labels | None = None
@dataclass(frozen=True) class Source: kind: SourceKind; source_url: str | None; page_url: str | None; author: str | None
    license_short: str = "unknown"; license_url: str | None = None; source_note: str | None = None
# subjects.py
@dataclass(frozen=True) class SubjectRef: subject: str; kind: Kind; generation: str | None; body: Body | None; part_id: str | None
def parse_subject(subject: str) -> SubjectRef   # ValueError for any other shape
# imaging.py
@dataclass(frozen=True) class ImageInfo: width: int; height: int; ext: str; phash: str
class UnreadableImage(Exception)
def inspect_image(data: bytes) -> ImageInfo; def hamming(a: str, b: str) -> int
# manifest.py
class ManifestError(Exception)
class Manifest: @classmethod def load(cls, path: Path) -> "Manifest"; def get(self, image_id: str) -> ImageRecord | None
    def records(self) -> list[ImageRecord]; def id_for_url(self, url: str) -> str | None
    def append(self, record: ImageRecord) -> None; def replace_all(self, records: Iterable[ImageRecord]) -> None
# store.py
class RefsStoreError(Exception)
@dataclass(frozen=True) class IngestResult: outcome: Literal["added","known_bytes","rejected"]; record: ImageRecord | None; reason: str | None
class RefStore:
    def __init__(self, settings: Settings) -> None   # attributes: settings, work_dir
    def ingest_bytes(self, data: bytes, *, subject: str, source: Source, now: datetime | None = None) -> IngestResult
    def records(self, subject: str | None = None) -> list[ImageRecord]; def get(self, image_id: str) -> ImageRecord | None
    def update(self, records: Iterable[ImageRecord]) -> None; def known_url(self, url: str) -> bool
    def record_skip(self, url: str, reason: str) -> None; def was_skipped(self, url: str) -> bool
    @staticmethod def image_relpath(record: ImageRecord) -> str   # "refs/images/ab/<sha>.<ext>"
    def image_path(self, record: ImageRecord) -> Path
# tests/refs_helpers.py (also fixtures `settings`, `store` in conftest.py: repo_root tmp/"repo", work_dir tmp/"work")
def make_image_bytes(seed: int = 0, size: tuple[int, int] = (1000, 800), fmt: str = "JPEG", exif_orientation: int | None = None) -> bytes
def resize_bytes(data: bytes, size: tuple[int, int]) -> bytes
def make_record(**overrides: Any) -> ImageRecord; def make_labels(**overrides: Any) -> Labels   # defaults: e46-coupe, e46/coupe/us/stock/lhd/standard/front_34_left/none/4
def ingest(store: RefStore, data: bytes, subject: str = "e46-coupe", **source_kw: Any) -> ImageRecord
def write_jsonl(directory: Path, rows: Sequence[Mapping[str, Any]]) -> Path
class FakeClock: def now(self) -> float; def sleep(self, s: float) -> None; slept: list[float]
```
- [ ] **Step 1: Write the failing tests**

```python
# test_refs_subjects.py
@pytest.mark.parametrize("s,kind,gen,body,part", [("e46-coupe","base-car","e46","coupe",None),
    ("e46-coupe-interior","interior","e46","coupe",None), ("product-wheel-a","product",None,None,"wheel-a")])
def test_parse_subject(s, kind, gen, body, part): r = parse_subject(s); assert (r.kind, r.generation, r.body, r.part_id) == (kind, gen, body, part)
def test_parse_subject_rejects_other_shapes():
    with pytest.raises(ValueError): parse_subject("E46 Coupe")
# test_refs_imaging.py
def test_inspect_reads_size_ext_and_phash():
    i = inspect_image(make_image_bytes(1)); assert (i.width, i.height, i.ext) == (1000, 800, "jpg") and len(i.phash) == 16
def test_inspect_ext_comes_from_content(): assert inspect_image(make_image_bytes(1, fmt="WEBP")).ext == "webp"
def test_inspect_applies_exif_rotation():
    i = inspect_image(make_image_bytes(1, exif_orientation=6)); assert (i.width, i.height) == (800, 1000)
@pytest.mark.skipif(not features.check("avif"), reason="Pillow built without AVIF")
def test_inspect_accepts_avif(): assert inspect_image(make_image_bytes(1, fmt="AVIF")).ext == "avif"
@pytest.mark.parametrize("data", [b"", b"<html>Too many requests</html>", make_image_bytes(1)[:3000], b"\x00\x00\x00\x18ftypheic" + b"\0" * 64])
def test_inspect_rejects_undecodable_bytes(data):
    with pytest.raises(UnreadableImage): inspect_image(data)
def test_inspect_rejects_decodable_but_unsupported_format():
    with pytest.raises(UnreadableImage, match="GIF"): inspect_image(make_image_bytes(1, fmt="GIF"))
def test_phash_is_stable_across_resize_and_hamming_counts_bits():
    a, b = inspect_image(make_image_bytes(3)), inspect_image(resize_bytes(make_image_bytes(3), (500, 400)))
    assert hamming(a.phash, b.phash) <= 6 and hamming("0" * 16, "0" * 15 + "f") == 4
# test_refs_manifest.py
def test_torn_last_manifest_line_is_dropped_and_manifest_stays_appendable(tmp_path):
    p = tmp_path / "m.jsonl"; r1, r2 = make_record(id="a" * 64), make_record(id="b" * 64)
    p.write_text(r1.model_dump_json() + "\n" + r2.model_dump_json()[:40])
    m = Manifest.load(p); assert [r.id for r in m.records()] == [r1.id]
    m.append(r2); assert [r.id for r in Manifest.load(p).records()] == [r1.id, r2.id]
def test_corrupt_middle_manifest_line_raises_with_line_number(tmp_path):
    p = tmp_path / "m.jsonl"; a, b = make_record(id="a" * 64), make_record(id="b" * 64)
    p.write_text(a.model_dump_json() + "\n{not json}\n" + b.model_dump_json() + "\n")
    with pytest.raises(ManifestError, match=r"m\.jsonl:2"): Manifest.load(p)
    assert "{not json}" in p.read_text()  # untouched
# Also, one test each: `test_replace_all_keeps_a_bak_and_leaves_no_temp_files`; `test_append_rejects_an_existing_id`
# test_refs_store.py
SRC = Source(kind="local", source_url=None, page_url=None, author=None, source_note="n")
def test_work_dir_inside_repo_is_refused(tmp_path):
    with pytest.raises(RefsStoreError, match="outside the repo"): RefStore(Settings(repo_root=tmp_path, work_dir=tmp_path / "w"))
def test_ingest_stores_by_hash_and_writes_manifest(store):
    d = make_image_bytes(1); r = store.ingest_bytes(d, subject="e46-coupe", source=SRC); i = hashlib.sha256(d).hexdigest()
    assert r.outcome == "added" and r.record.id == i and r.record.retrieved_at.tzinfo
    assert (store.work_dir / f"refs/images/{i[:2]}/{i}.jpg").read_bytes() == d
    assert Manifest.load(store.work_dir / "refs/manifest.jsonl").get(i) == r.record
# Also, one test each: `test_ingest_same_bytes_twice_is_idempotent` (second outcome "known_bytes"; one manifest line, one file)
def test_second_collector_same_bytes_keeps_one_record_and_upgrades_unknown_license(store):
    d = make_image_bytes(2); store.ingest_bytes(d, subject="e46-coupe", source=Source("crawl", "https://a/x.jpg", "https://a/p", None))
    r = store.ingest_bytes(d, subject="e46-coupe", source=Source("commons", "https://c/t.jpg", "https://c/File:x", "Jane", "CC BY-SA 4.0", "https://cc/by-sa"))
    assert len(store.records()) == 1 and r.outcome == "known_bytes"
    assert (r.record.source_kind, r.record.license_short, r.record.author) == ("commons", "CC BY-SA 4.0", "Jane")
    assert {"https://a/x.jpg", "https://c/t.jpg", "https://c/File:x"} <= set(r.record.seen_urls)
# Also, one test each: `test_known_license_is_never_downgraded_by_a_later_unknown`; `test_same_bytes_under_other_subject_keeps_first_subject` (reason names the first subject); `test_known_url_and_was_skipped_after_ingest_and_record_skip`
def test_resume_after_crash_between_file_write_and_manifest_append(store, monkeypatch):
    d = make_image_bytes(4)
    with monkeypatch.context() as m:
        m.setattr(Manifest, "append", lambda self, rec: (_ for _ in ()).throw(KeyboardInterrupt()))
        with pytest.raises(KeyboardInterrupt): store.ingest_bytes(d, subject="e46-coupe", source=SRC)
    fresh = RefStore(store.settings); assert fresh.records() == []
    assert fresh.ingest_bytes(d, subject="e46-coupe", source=SRC).outcome == "added" and len(RefStore(store.settings).records()) == 1
# Also, one test each: `test_undecodable_bytes_are_rejected_and_not_stored` (outcome "rejected"; no file, no manifest line)
def test_refs_stats_cli_counts_by_subject(store, monkeypatch):
    ingest(store, make_image_bytes(1)); ingest(store, make_image_bytes(2)); monkeypatch.setenv("M3_WORK_DIR", str(store.work_dir))
    r = CliRunner().invoke(app, ["refs", "stats"]); assert r.exit_code == 0 and "e46-coupe images=2 new=2 labeled=0 duplicate=0" in r.output
def test_external_network_is_blocked():  # autouse guard in conftest.py
    with pytest.raises(OSError): socket.create_connection(("example.com", 80), timeout=1)
```
- [ ] **Step 2: Run to verify failure:** `cd pipeline && uv run pytest tests/test_refs_subjects.py tests/test_refs_imaging.py tests/test_refs_manifest.py tests/test_refs_store.py -q`; expected: collection errors `ModuleNotFoundError: No module named 'm3_pipeline.refs'`.
- [ ] **Step 3: Implement**
  - `parse_subject` tries `^product-(?P<part>[a-z0-9]+(-[a-z0-9]+)*)$` first, then `^(?P<gen>[a-z0-9]+)-(?P<body>coupe|convertible|sedan)(?P<int>-interior)?$`.
  - `imaging.py` (imagehash façade): Pillow open, `ImageOps.exif_transpose`, `.load()` so truncated files fail; map `OSError`, `Image.DecompressionBombError`, `SyntaxError` to `UnreadableImage`. Accept JPEG, MPO (ext `jpg`), PNG, WEBP, AVIF; any other decodable format raises `UnreadableImage("unsupported format GIF")`. Width, height and `imagehash.phash` (hex) come from the transposed image; stored bytes are never modified.
  - `manifest.py`: one `model_dump_json()` per line. `load`: an invalid last line with no trailing newline is a torn write, so copy the file to `.bak`, rewrite without it, log a warning; any other invalid line raises `ManifestError(f"{path}:{lineno}: {reason}")` and the file stays untouched. `append` writes line and `\n`, flushes, fsyncs. `replace_all` writes a temp file in the same directory, copies the old file to `.bak`, then `os.replace`.
  - `store.py`: `__init__` raises `RefsStoreError("work_dir must be outside the repo ...")`. Skips live in `<work_dir>/refs/skipped.jsonl`. `ingest_bytes`: `inspect_image` (failure -> `rejected` with reason); `id = sha256(data)`; if the id exists, return `known_bytes` after merging: keep the first subject (reason names it), union `seen_urls` with `source_url` and, for Commons, `page_url`; if the stored `license_short` is `unknown` and the incoming one is known, replace `source_kind, source_url, page_url, author, license_short, license_url, source_note`; never replace a known license; persist with `replace_all`. Otherwise write the image to a temp file in its directory and `os.replace` it (skip if present), then `manifest.append`: file first, manifest second, so a crash leaves at worst an orphan file.
  - `cli.py`: `refs_app = typer.Typer(help="Reference photo collection and curation")`; `stats` prints `<subject> images=N new=N labeled=N duplicate=N` per subject. Commands stay thin; settings via `load_settings()`.
  - `conftest.py`: autouse fixture patching `socket.socket.connect` to allow only `127.0.0.1`, `::1`, `localhost`.
- [ ] **Step 4: Run to verify pass:** the Step 2 command; expected: all pass (AVIF may skip). Then `pnpm check:pipeline` exits 0.
- [ ] **Step 5: Commit and land:** `git add pipeline && git commit -m "feat(refs): add record models, jsonl manifest and hash-addressed store"`, then push and open the PR per Landing.

### Task 2: Wikimedia Commons collector
**Files** (branch `feat/refs-commons`):
- Modify: `pipeline/pyproject.toml` (`uv add httpx==0.28.1`), `pipeline/src/m3_pipeline/refs/cli.py`
- Create: `pipeline/refs-sources.toml`, `pipeline/src/m3_pipeline/refs/{throttle,sources,commons}.py`, `pipeline/tests/{refs_fakes.py,test_refs_sources.py,test_refs_commons.py}`

**Interfaces:**
- Consumes: `RefStore`, `Source`, `FakeClock`, `make_image_bytes` (Task 1).
- Produces:
```python
# throttle.py
class Throttle:
    def __init__(self, min_interval_s: float, *, clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep) -> None
    def wait(self, key: str = "", min_interval_s: float | None = None) -> None   # sleeps so >= interval has passed since the last wait for `key`
    def pause(self, seconds: float) -> None
# sources.py
DEFAULT_USER_AGENT = "m3-tool-refs/0.1 (+https://github.com/GridWork-dev/m3-tool)"
@dataclass(frozen=True) class CommonsSettings: thumb_width: int = 1920; min_interval_s: float = 3.0   # thumb_width must be a standard Wikimedia step; min_interval_s is floored at 1.0
@dataclass(frozen=True) class CrawlSettings: delay_s: float = 3.0; max_pages: int = 25; min_side_px: int = 800
@dataclass(frozen=True) class SubjectSources: commons_categories: tuple[str, ...] = (); search_terms: tuple[str, ...] = (); crawl_urls: tuple[str, ...] = ()
@dataclass(frozen=True) class RefsSources: user_agent: str; commons: CommonsSettings; crawl: CrawlSettings; subjects: Mapping[str, SubjectSources]
class SourcesError(ValueError)
def load_sources(path: Path, env: Mapping[str, str] | None = None) -> RefsSources   # env M3_REFS_USER_AGENT overrides [http] user_agent
# commons.py
PAGE_SIZE = 50
class CommonsFile(BaseModel): title: str; page_url: str; thumb_url: str; mime: str; license_short: str; license_url: str | None; author: str | None
def merge_batch(acc: dict[str, dict[str, Any]], pages: Sequence[Mapping[str, Any]]) -> None   # merge by title; imageinfo[0] dicts are updated, never replaced
def parse_page(page: Mapping[str, Any]) -> CommonsFile | None   # None: non-image mime or no imageinfo
class CommonsThrottled(Exception); class CommonsThumbWidthRejected(Exception)
@dataclass class CommonsReport: seen: int = 0; added: int = 0; known: int = 0; skipped_mime: int = 0; skipped_no_imageinfo: int = 0
    failed: int = 0; stopped_early: bool = False; stop_reason: str | None = None
class CommonsClient:
    def __init__(self, http: httpx.Client, store: RefStore, *, sources: RefsSources, throttle: Throttle, max_retries: int = 3) -> None
    def collect(self, subject: str, categories: Sequence[str] = (), *, search_terms: Sequence[str] = (), limit: int | None = None) -> CommonsReport  # limit: files per category or term
# tests/refs_fakes.py
class FakeWikimedia:   # .transport (httpx.MockTransport), .requests, .request_times (from the injected clock)
    def __init__(self, pages: list[dict[str, Any]], *, page_size: int = 2, clock: FakeClock | None = None) -> None
    maxlag_first: int = 0; api_429_first: int = 0; retry_after: int = 2; thumb_status: int | None = None; thumb_body: bytes | None = None
    quirky_continuations: bool = False   # serves a distinct generated JPEG per thumbnail URL and answers the categorymembers and search generators alike; each continuation batch starts with the previous last title minus imageinfo; the first title's extmetadata arrives one batch late
```
CLI: `pipeline refs commons --subject <id> [--limit N]`; categories and terms come from `refs-sources.toml`.
- [ ] **Step 1: Write the failing tests** (fixtures: `clock` = `FakeClock`; `world` = `FakeWikimedia` with 3 pages (all with the FULL metadata below), `page_size=2`, `clock`; `make_client(thumb_width=1920)` returns a `CommonsClient` over `httpx.Client(transport=world.transport, headers={"User-Agent": DEFAULT_USER_AGENT})`, default sources, `Throttle(3.0, clock=clock.now, sleep=clock.sleep)`; `client` = `make_client()`)

```python
def commons_page(name, meta=None):
    ii = {"url": f"https://upload.wikimedia.org/o/{name}", "thumburl": f"https://upload.wikimedia.org/t/{name}", "mime": "image/jpeg",
          "descriptionurl": f"https://commons.wikimedia.org/wiki/File:{name}", "width": 4000, "height": 3000}
    if meta is not None: ii["extmetadata"] = meta
    return {"title": f"File:{name}", "imageinfo": [ii]}
FULL = {"LicenseShortName": {"value": "CC BY-SA 4.0"}, "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/4.0"},
        "Artist": {"value": '<a href="//x">Jane <b>Doe</b></a>'}}
def test_parse_page_reads_license_author_and_urls():
    f = parse_page(commons_page("a.jpg", FULL)); assert (f.license_short, f.author) == ("CC BY-SA 4.0", "Jane Doe") and f.license_url.endswith("/by-sa/4.0")
    assert f.thumb_url.endswith("/t/a.jpg") and f.page_url.endswith("File:a.jpg")
@pytest.mark.parametrize("meta", [None, {}, {"LicenseShortName": {"value": ""}}, {"Artist": {"value": "<br/>"}}])
def test_missing_extmetadata_gives_unknown_license(meta):
    f = parse_page(commons_page("a.jpg", meta)); assert (f.license_short, f.license_url, f.author) == ("unknown", None, None)
@pytest.mark.parametrize("mime", ["image/svg+xml", "application/pdf", "video/webm"])
def test_parse_page_skips_non_image_mimes(mime):
    p = commons_page("a.jpg"); p["imageinfo"][0]["mime"] = mime; assert parse_page(p) is None
def test_merge_batch_joins_by_title_and_pages_without_imageinfo_stay_unparseable():
    acc = {}; merge_batch(acc, [{"title": "File:a.jpg", "imageinfo": [{"url": "u", "mime": "image/jpeg"}]}, {"title": "File:b.jpg"}])
    merge_batch(acc, [{"title": "File:a.jpg", "imageinfo": [{"extmetadata": FULL}]}, {"title": "File:b.jpg"}])
    assert acc["File:a.jpg"]["imageinfo"][0] == {"url": "u", "mime": "image/jpeg", "extmetadata": FULL} and parse_page(acc["File:b.jpg"]) is None
def test_collect_survives_continuation_batches_without_imageinfo(world, client, store):
    world.quirky_continuations = True; rep = client.collect("e46-coupe", ["Test cars"])
    assert rep.added == 3 and rep.skipped_no_imageinfo == 0 and {r.license_short for r in store.records()} == {"CC BY-SA 4.0"}  # late extmetadata merged by title
def test_request_params_and_user_agent_are_pinned(world, client):
    client.collect("e46-coupe", ["Test cars"]); req = world.requests[0]; q = req.url.params
    assert (q["generator"], q["gcmtitle"], q["gcmtype"], q["gcmlimit"], q["prop"]) == ("categorymembers", "Category:Test cars", "file", "50", "imageinfo")
    assert (q["iiprop"], q["iiurlwidth"], q["maxlag"]) == ("url|size|mime|extmetadata", "1920", "5") and req.headers["user-agent"] == DEFAULT_USER_AGENT
def test_collect_follows_continuation_and_records_provenance(world, client, store):
    rep = client.collect("e46-coupe", ["Test cars"]); recs = store.records()  # 3 pages over 2 batches
    assert (rep.seen, rep.added) == (3, 3) and {r.source_kind for r in recs} == {"commons"} and all(r.source_url.startswith("https://upload.wikimedia.org/t/") and r.page_url for r in recs)
def test_search_terms_use_the_file_namespace_search_generator(world, client, store):
    rep = client.collect("e46-coupe-interior", [], search_terms=["E46 M3 interior"]); q = world.requests[0].url.params
    assert (q["gsrsearch"], q["gsrnamespace"], q["prop"]) == ("E46 M3 interior", "6", "imageinfo") and rep.added == 3 and len(store.records()) == 3
# Also, one test each: `test_same_file_from_category_and_search_is_ingested_once` (collect with both -> 3 records, second pass reports known == 3)
def test_rerun_skips_known_urls_without_downloading(world, client):
    client.collect("e46-coupe", ["Test cars"]); n = len(world.requests); rep = client.collect("e46-coupe", ["Test cars"])
    assert rep.known == 3 and [r for r in world.requests[n:] if r.url.host == "upload.wikimedia.org"] == []
def test_api_calls_and_thumbnail_downloads_share_one_three_second_limiter(world, client):
    client.collect("e46-coupe", ["Test cars"]); t = world.request_times
    assert any(r.url.host == "upload.wikimedia.org" for r in world.requests) and all(b - a >= 3.0 for a, b in zip(t, t[1:]))
def test_maxlag_error_in_body_waits_then_retries(world, client, clock):
    world.maxlag_first = 1; world.retry_after = 7  # 200 + {"error": {"code": "maxlag"}} + Retry-After: 7
    assert client.collect("e46-coupe", ["Test cars"]).added == 3 and 7.0 in clock.slept
def test_429_with_retry_after_sleeps_via_the_injected_clock_then_succeeds(world, client, clock, caplog):
    caplog.set_level(logging.INFO); world.api_429_first = 1  # Retry-After: 2
    assert client.collect("e46-coupe", ["Test cars"]).added == 3 and 2.0 in clock.slept and "Retry-After 2" in caplog.text
def test_429_exhausts_retries_and_stops_cleanly(world, client, clock, store):
    world.thumb_status = 429  # Retry-After: 2 on every thumbnail request
    rep = client.collect("e46-coupe", ["Test cars"]); assert rep.stopped_early and "429" in rep.stop_reason and store.records() == []
    assert {2.0, 4.0, 8.0} <= set(clock.slept)  # doubles per retry
    assert len([r for r in world.requests if r.url.host == "upload.wikimedia.org"]) == 1 + 3  # first try plus max_retries, then nothing more
def test_thumbnail_step_rejection_stops_with_config_hint(world, make_client):
    client = make_client(thumb_width=2560)  # a non-standard width, set explicitly
    world.thumb_status, world.thumb_body = 429, b"Use thumbnail steps listed on https://w.wiki/GHai"
    rep = client.collect("e46-coupe", ["Test cars"]); assert rep.stopped_early and "thumb_width" in rep.stop_reason and world.requests[0].url.params["iiurlwidth"] == "2560"
    assert len([r for r in world.requests if r.url.host == "upload.wikimedia.org"]) == 1  # not a rate limit, so not retried
# Also, one test each: `test_non_image_thumbnail_body_counts_as_failed_not_stored` (200 text/html -> report.failed == 1, nothing stored)
def test_no_category_names_or_search_terms_are_hard_coded():
    src = Path(commons_module.__file__).read_text(); assert not re.search(r"Category:[A-Za-z]", src) and "E46" not in src and "BMW" not in src
# test_refs_sources.py
# Also, one test each: `test_load_sources_reads_subjects_and_defaults` (categories/search_terms as tuples; commons min_interval_s 3.0; crawl 3.0/25/800); `test_commons_interval_below_one_second_is_floored` (0.2 loads as 1.0); `test_env_user_agent_overrides_toml`; `test_shipped_sources_file_parses_and_holds_the_example_subjects` (e46-coupe has commons_categories; e46-coupe-interior has categories and search_terms); `test_commons_cli_without_categories_or_terms_exits_2` (M3_REPO_ROOT=tmp with an empty refs-sources.toml; message names pipeline/refs-sources.toml)
```
- [ ] **Step 2: Run to verify failure:** `cd pipeline && uv run pytest tests/test_refs_sources.py tests/test_refs_commons.py -q`; expected: collection errors, `ModuleNotFoundError` for `m3_pipeline.refs.sources` and `.commons`.
- [ ] **Step 3: Implement**
  - `throttle.py`: last-completed time per key; `wait` sleeps `last + interval - now` when positive; `pause` calls the injected sleep.
  - `sources.py`: `tomllib`; shape `[http] user_agent`, `[commons] thumb_width, min_interval_s`, `[crawl] delay_s, max_pages, min_side_px`, `[subjects.<id>] commons_categories, search_terms, crawl_urls`. Ship `pipeline/refs-sources.toml` with example config only (recon of 2026-11-23): `e46-coupe` -> `commons_categories = ["Category:BMW M3 (E46/2S)"]` (coupe, 369 files); `e46-coupe-interior` -> `["Category:BMW M3 (E46/2CS)"]` (convertible, 144 files; useful for front-interior shots because the cabriolet shares the dash and seats; most files are exteriors the filter will drop) and `search_terms = ["E46 M3 interior", "BMW E46 interior"]`; a comment lists `Category:BMW M3 CSL (E46)` (74 files) as collectable into the same `e46-coupe` subject, because the `trim` label lets the filter drop it. Default `thumb_width = 1920`.
  - `commons.py` request: `GET https://commons.wikimedia.org/w/api.php` with `action=query, format=json, formatversion=2, prop=imageinfo, iiprop=url|size|mime|extmetadata, iiurlwidth=<thumb_width>, maxlag=5` plus either `generator=categorymembers, gcmtitle, gcmtype=file, gcmlimit=50` (prefix `Category:` only when missing) or `generator=search, gsrsearch, gsrnamespace=6, gsrlimit=50` (the generator form of `list=search` with `srnamespace=6`). Follow `continue` until absent.
  - `collect` per category or term: first list every batch into one dict with `merge_batch` (so a title that spans batches is complete), then process in title order: skip and count pages `parse_page` rejects (`skipped_no_imageinfo` or `skipped_mime`), skip when `store.known_url(thumb_url)` or `known_url(page_url)`, else download `thumb_url` exactly as returned (never build thumbnail URLs), require `image/*`, then `store.ingest_bytes(..., Source("commons", thumb_url, page_url, author, license_short, license_url))`. `parse_page` strips HTML from `Artist` (tags removed, `html.unescape`, whitespace collapsed; empty -> `None`) and accepts jpeg, png, webp and tiff mimes.
  - `_get(url, params=None)`: `throttle.wait("commons")` before every request (API and thumbnails share the key). Retry on HTTP 200 with `error.code in {"maxlag","ratelimited"}` or HTTP 429/503: wait `Retry-After` seconds (5 when absent), doubled on each further retry of that request, capped at 120, through `throttle.pause`; log `commons: HTTP 429 from <host>; Retry-After 2s; retry 1/3`; after `max_retries` raise `CommonsThrottled`. A 429 whose body contains "thumbnail steps" raises `CommonsThumbWidthRejected` at once. `collect` catches both, sets `stopped_early` and `stop_reason` (width case: `thumbnail width rejected; set commons.thumb_width to a standard step (1920 or 3840) in pipeline/refs-sources.toml`), keeps what was ingested, and returns.
  - CLI `commons`: `httpx.Client(headers={"User-Agent": ua}, timeout=30, follow_redirects=True)`; print the report; exit 2 when the subject has neither categories nor terms.
- [ ] **Step 4: Run to verify pass:** the Step 2 command; expected: all pass. Then `pnpm check:pipeline` exits 0.
- [ ] **Step 5: Commit and land:** `git add pipeline && git commit -m "feat(refs): add Wikimedia Commons collector and refs-sources config"`, then push and open the PR per Landing.

### Task 3: Local-folder importer
**Files** (branch `feat/refs-import`):
- Create: `pipeline/src/m3_pipeline/refs/importer.py`, `pipeline/tests/test_refs_importer.py`
- Modify: `pipeline/src/m3_pipeline/refs/cli.py`

**Interfaces:**
- Consumes: `RefStore.ingest_bytes`, `Source`, `parse_subject` (Task 1).
- Produces:
```python
@dataclass class ImportReport: added: int = 0; known: int = 0; skipped: list[tuple[str, str]] = field(default_factory=list)  # (path, reason)
def import_directory(store: RefStore, directory: Path, *, subject: str, source_note: str, license_short: str | None = None) -> ImportReport
```
CLI: `pipeline refs import <dir> --subject <id> --source-note <text> [--license <name>]`.
- [ ] **Step 1: Write the failing tests**

```python
def make_dir(tmp_path, files): ...  # {name: bytes} -> tmp_path/"in"
def test_import_adds_files_with_unknown_license_by_default(store, tmp_path):
    d = make_dir(tmp_path, {"a.jpg": make_image_bytes(1)}); rep = import_directory(store, d, subject="e46-coupe", source_note="my own search")
    r = store.records()[0]; assert rep.added == 1 and (r.source_kind, r.license_short, r.source_note, r.source_url) == ("local", "unknown", "my own search", None)
# Also, one test each: `test_import_license_flag_sets_license_short` ("CC BY 4.0" -> license_short "CC BY 4.0", license_url None)
def test_import_continues_past_bad_files_and_reports_them(store, tmp_path):
    d = make_dir(tmp_path, {"good.jpg": make_image_bytes(1), "page.jpg": b"<html>error</html>", "phone.heic": b"\x00\x00\x00\x18ftypheic" + b"\0" * 64,
        "anim.gif": make_image_bytes(2, fmt="GIF"), "notes.txt": b"x", ".DS_Store": b"x"})
    rep = import_directory(store, d, subject="e46-coupe", source_note="n"); why = {Path(p).name: r for p, r in rep.skipped}
    assert rep.added == 1 and set(why) == {"page.jpg", "phone.heic", "anim.gif"} and "JPEG" in why["phone.heic"]  # tells the user how to convert
# Also, one test each: `test_import_takes_extension_from_content_not_filename` (WebP bytes named x.jpg -> record.ext == "webp"); `test_import_recurses_and_is_idempotent` (nested dir; rerun: added == 0, known == 1, one file on disk); `test_import_leaves_the_source_files_untouched`; `test_import_cli_requires_source_note_and_a_valid_subject` (exit 2 without --source-note; exit 2 for --subject "Bad Id")
```
- [ ] **Step 2: Run to verify failure:** `cd pipeline && uv run pytest tests/test_refs_importer.py -q`; expected: `ModuleNotFoundError: No module named 'm3_pipeline.refs.importer'`.
- [ ] **Step 3: Implement**
  - `import_directory`: `sorted(directory.rglob("*"))`; consider regular files whose lowercase suffix is in `{.jpg,.jpeg,.png,.webp,.avif,.heic,.heif,.tif,.tiff,.gif,.bmp}` and ignore the rest silently. `ingest_bytes` with `Source(kind="local", source_url=None, page_url=None, author=None, license_short=license_short or "unknown", source_note=source_note)`. A `rejected` result goes to `skipped`; for `.heic`/`.heif` the reason adds `convert to JPEG first (macOS: sips -s format jpeg in.heic --out out.jpg)`. Never move or delete originals.
  - CLI prints `added=N known=N skipped=N` then one `skipped <path>: <reason>` line each; `--subject` is checked with `parse_subject` (exit 2 on `ValueError`).
- [ ] **Step 4: Run to verify pass:** the Step 2 command; expected: all pass. Then `pnpm check:pipeline` exits 0.
- [ ] **Step 5: Commit and land:** `git add pipeline && git commit -m "feat(refs): add local-folder importer"`, then push and open the PR per Landing.

### Task 4: Crawler engine (robots, blocked detection, extraction, runner)
**Files** (branch `feat/refs-crawl-engine`):
- Create: `pipeline/src/m3_pipeline/refs/crawl/{__init__,robots,blocked,extract,engine}.py`, `pipeline/tests/{refs_site.py,test_refs_crawl_parts.py,test_refs_crawl_engine.py}`

**Interfaces:**
- Consumes: `RefStore`, `Source`, `inspect_image` (Task 1); `Throttle`, `CrawlSettings`, `DEFAULT_USER_AGENT` (Task 2); `FakeClock`.
- Produces:
```python
# robots.py
def parse_robots(status: int, body: str) -> RobotFileParser   # 200 parse; 404/410 allow all; any other status disallow all
class RobotsCache:
    def __init__(self, http: httpx.Client, user_agent: str) -> None
    def allowed(self, url: str) -> bool; def crawl_delay(self, url: str) -> float | None   # one robots.txt fetch per host, with our UA
# blocked.py
def is_blocked(status: int, title: str, text_head: str) -> bool   # 403/429, or markers "just a moment", "attention required", "security checkpoint", "verify you are human", "captcha", "access denied" in title or head
# extract.py
def extract_image_urls(html: str, base_url: str) -> list[str]   # img src/data-src/srcset(largest), a href to images, og:image; absolute http(s); stable order, deduped
# engine.py
@dataclass(frozen=True) class PageResult: status: int; html: str; final_url: str
class PageFetcher(Protocol): def fetch(self, url: str) -> PageResult
@dataclass class CrawlReport: pages_fetched: int = 0; blocked: list[str] = []; disallowed: list[str] = []; images_added: int = 0; images_known: int = 0; images_small: int = 0; images_failed: int = 0
def crawl_pages(subject: str, urls: Sequence[str], *, settings: CrawlSettings, user_agent: str, fetcher: PageFetcher,
                http: httpx.Client, store: RefStore, throttle: Throttle) -> CrawlReport
# tests/refs_site.py: fixture `site` = ThreadingHTTPServer on 127.0.0.1:0
class Site: def url(self, path: str) -> str; def add(self, path: str, *, status: int = 200, body: bytes | str = b"", content_type: str = "text/html") -> None
    requests: list[SeenRequest]  # (path, user_agent); def hits(self, path: str) -> int
# tests: HttpxPageFetcher(http) implements PageFetcher with plain httpx (no browser)
```
- [ ] **Step 1: Write the failing tests** (`site` defaults: `/ok.html` links `/big.jpg` 1000x800 and `/small.jpg` 300x200; `/private/page.html`; `/blocked.html` 403; `/checkpoint.html` 429 titled "Vercel Security Checkpoint"; `/challenge.html` 200 "Just a moment..."; `/robots.txt` disallows `/private/`)

```python
@pytest.mark.parametrize("status,expect", [(404, True), (410, True), (500, False), (403, False)])
def test_parse_robots_status_rules(status, expect): assert parse_robots(status, "").can_fetch(DEFAULT_USER_AGENT, "https://h/x") is expect
def test_robots_matches_our_product_token_and_exposes_crawl_delay():
    p = parse_robots(200, "User-agent: m3-tool-refs\nCrawl-delay: 10\nDisallow: /private/\n")
    assert not p.can_fetch(DEFAULT_USER_AGENT, "https://h/private/a") and p.can_fetch(DEFAULT_USER_AGENT, "https://h/public/a") and p.crawl_delay(DEFAULT_USER_AGENT) == 10
@pytest.mark.parametrize("status,title,head,blocked", [(403, "", "", True), (429, "Vercel Security Checkpoint", "", True), (200, "Just a moment...", "", True),
    (200, "x", "Please verify you are human", True), (200, "Vercel Security Checkpoint", "", True), (200, "E46 M3 gallery", "photos", False)])
def test_is_blocked(status, title, head, blocked): assert is_blocked(status, title, head) is blocked
def test_extract_image_urls_covers_img_srcset_links_og_and_lazy_attrs():
    html = '<meta property="og:image" content="/og.jpg"><img src="a.jpg"><img data-src="b.jpg"><img srcset="c1.jpg 400w, c2.jpg 1600w"><a href="d.png">x</a><img src="data:image/gif;base64,AAAA">'
    assert extract_image_urls(html, "https://h/p/") == ["https://h/og.jpg", "https://h/p/a.jpg", "https://h/p/b.jpg", "https://h/p/c2.jpg", "https://h/p/d.png"]
# test_refs_crawl_engine.py; run(site, store, urls, clock, **kw) builds httpx.Client(headers UA), RobotsCache, Throttle(3.0, clock=clock.now, sleep=clock.sleep), HttpxPageFetcher
def test_disallowed_page_is_skipped_and_never_requested(site, store, clock):
    rep = run(site, store, [site.url("/private/page.html")], clock); assert rep.disallowed == [site.url("/private/page.html")] and site.hits("/private/page.html") == 0
def test_403_page_is_logged_as_blocked_with_an_import_hint_and_retried_once(site, store, clock, caplog):
    rep = run(site, store, [site.url("/blocked.html")], clock); assert rep.blocked == [site.url("/blocked.html")] and site.hits("/blocked.html") == 2
    assert "refs import" in caplog.text  # tells the user to save the photos in a normal browser and import them
# Also, one test each: `test_429_checkpoint_page_is_blocked_and_never_ingested` (/checkpoint.html -> blocked, store empty; 200 challenge page behaves the same)
def test_big_image_is_ingested_with_crawl_provenance_and_small_one_is_remembered(site, store, clock):
    rep = run(site, store, [site.url("/ok.html")], clock); r = store.records()[0]
    assert (rep.images_added, rep.images_small) == (1, 1) and (r.source_kind, r.license_short, r.page_url) == ("crawl", "unknown", site.url("/ok.html"))
    run(site, store, [site.url("/ok.html")], clock); assert site.hits("/small.jpg") == 1 and site.hits("/big.jpg") == 1  # rerun requests neither again
# Also, one test each: `test_image_403_is_logged_blocked_and_skipped` (images_failed == 1, nothing stored)
def test_waits_between_requests_to_the_same_host(site, store, clock):
    run(site, store, [site.url("/ok.html")], clock); assert clock.slept.count(3.0) >= 2
# Also, one test each: `test_crawl_delay_larger_than_default_is_honored` (robots Crawl-delay: 10 -> 10.0 in clock.slept); `test_robots_applies_to_images_as_well_as_pages` (a disallowed image path is never requested); `test_max_pages_caps_visits` (max_pages=1 with two URLs -> pages_fetched == 1)
def test_every_request_carries_our_user_agent(site, store, clock):
    run(site, store, [site.url("/ok.html")], clock); assert {r.user_agent for r in site.requests} == {DEFAULT_USER_AGENT}
```
- [ ] **Step 2: Run to verify failure:** `cd pipeline && uv run pytest tests/test_refs_crawl_parts.py tests/test_refs_crawl_engine.py -q`; expected: collection errors `ModuleNotFoundError: m3_pipeline.refs.crawl`.
- [ ] **Step 3: Implement**
  - `robots.py`: build a `RobotFileParser`; set `allow_all` or `disallow_all` per the status rule, else `parse(body.splitlines())`. `RobotsCache` fetches `<scheme>://<host>/robots.txt` through the shared httpx client (never `RobotFileParser.read`, which sends Python's own UA) and caches per host.
  - `blocked.py`, `extract.py`: stdlib only (`html.parser`, `urllib.parse.urljoin`); `srcset` takes the largest `w` descriptor, else the last entry.
  - `engine.py`: for each of `urls[:max_pages]`: `robots.allowed` else `disallowed.append` and continue; `throttle.wait(host, max(delay_s, crawl_delay or 0))`; `fetcher.fetch`; if `is_blocked(status, title, head)`, wait `2 * delay_s` and retry once; still blocked -> `blocked.append(url)`, log `blocked (HTTP <status>): <url>; save the photos in a normal browser and add them with `pipeline refs import``, continue. Then per `extract_image_urls` result: skip if `known_url` or `was_skipped`; skip if robots disallows; throttle by image host; GET with `http`; 403/429 or non-`image/*` -> `images_failed`, log, continue; `inspect_image`; `min(width, height) < min_side_px` -> `record_skip(url, "small")`, `images_small += 1`; else `ingest_bytes(..., Source("crawl", img_url, page_url, None))`. It visits only the URLs it is given and never follows links.
  - `Site`: handler thread records `(path, User-Agent)`; `/robots.txt` default `User-agent: *\nDisallow: /private/\n`.
- [ ] **Step 4: Run to verify pass:** the Step 2 command; expected: all pass. Then `pnpm check:pipeline` exits 0.
- [ ] **Step 5: Commit and land:** `git add pipeline && git commit -m "feat(refs): add crawler engine with robots, throttle and blocked-page handling"`, then push and open the PR per Landing.

### Task 5: Browser backends and `refs crawl`
**Files** (branch `feat/refs-crawl-backends`):
- Modify: `pipeline/pyproject.toml` (`uv add playwright==1.65.2`), `pipeline/tests/conftest.py` (skip `browser` tests without Chromium), `pipeline/src/m3_pipeline/refs/cli.py`
- Create: `pipeline/src/m3_pipeline/refs/crawl/{fetchers,browserbase}.py`, `pipeline/tests/test_refs_backends.py`

**Interfaces:**
- Consumes: `PageFetcher`, `PageResult`, `crawl_pages`, `RobotsCache` (Task 4); `load_sources`, `RefsSources` (Task 2); `Site` fixture.
- Produces:
```python
# browserbase.py
def browserbase_session_payload(project_id: str, *, timeout_s: int = 900) -> dict[str, Any]
@dataclass(frozen=True) class BrowserbaseSession: id: str; connect_url: str = field(repr=False)
def create_session(http: httpx.Client, api_key: str, project_id: str) -> BrowserbaseSession
def release_session(http: httpx.Client, api_key: str, project_id: str, session_id: str) -> None
def redact(text: str) -> str   # apiKey=... -> apiKey=***
# fetchers.py
class MissingCredentials(Exception)   # names variables only
def open_fetcher(backend: Literal["local","browserbase"], *, user_agent: str, env: Mapping[str, str], http: httpx.Client) -> ContextManager[PageFetcher]
```
CLI: `pipeline refs crawl --subject <id> [--url <u> ...] [--backend local|browserbase] [--max-pages N] [--delay S]`. URLs: `--url` values, else the subject's `crawl_urls`; none -> exit 2.
- [ ] **Step 1: Write the failing tests**

```python
def test_session_payload_turns_off_captcha_proxies_and_stealth():
    p = browserbase_session_payload("proj"); b = p["browserSettings"]
    assert p["projectId"] == "proj" and p["proxies"] is False and p["timeout"] == 900
    assert b["solveCaptchas"] is False and b["advancedStealth"] is False and "fingerprint" not in b
def test_create_session_sends_key_header_and_never_logs_connect_url(caplog):
    t = httpx.MockTransport(lambda r: httpx.Response(200, json={"id": "s1", "connectUrl": "wss://h?apiKey=test-key&sessionId=s1"}))
    s = create_session(httpx.Client(transport=t), "test-key", "proj"); assert s.id == "s1" and "test-key" not in caplog.text and "test-key" not in repr(s)
def test_redact_strips_api_key_query(): assert redact("wss://h?apiKey=abc&sessionId=1") == "wss://h?apiKey=***&sessionId=1"
# Also, one test each: `test_release_session_is_called_even_when_the_crawl_raises` (exit open_fetcher("browserbase") with an exception -> release request recorded (MockTransport, fake playwright))
def test_browserbase_backend_names_only_the_missing_variables():
    with pytest.raises(MissingCredentials) as e: open_fetcher("browserbase", user_agent=DEFAULT_USER_AGENT, env={"M3_BROWSERBASE_API_KEY": "test-key"}, http=httpx.Client())
    assert "M3_BROWSERBASE_PROJECT_ID" in str(e.value) and "test-key" not in str(e.value) and "M3_BROWSERBASE_API_KEY" not in str(e.value)
def test_no_evasion_code_is_present():
    text = "".join(p.read_text() for p in Path(crawl_pkg.__file__).parent.glob("*.py"))
    assert not [t for t in ("playwright_stealth", "stealth_sync", "fake_useragent", "2captcha", "Mozilla/5.0", "HeadlessChrome") if t in text]
# Also, one test each: `test_crawl_cli_without_urls_exits_2` (no --url, no crawl_urls; message names pipeline/refs-sources.toml)
@pytest.mark.browser
def test_playwright_fetcher_reports_status_and_sends_our_user_agent(site):
    with open_fetcher("local", user_agent=DEFAULT_USER_AGENT, env={}, http=httpx.Client()) as f: r = f.fetch(site.url("/ok.html"))
    assert r.status == 200 and "big.jpg" in r.html and {x.user_agent for x in site.requests if x.path == "/ok.html"} == {DEFAULT_USER_AGENT}
@pytest.mark.browser
def test_playwright_fetcher_reports_403_status(site):
    with open_fetcher("local", user_agent=DEFAULT_USER_AGENT, env={}, http=httpx.Client()) as f: assert f.fetch(site.url("/blocked.html")).status == 403
```
- [ ] **Step 2: Run to verify failure:** `cd pipeline && uv run pytest tests/test_refs_backends.py -q`; expected: collection error `ModuleNotFoundError: m3_pipeline.refs.crawl.browserbase`.
- [ ] **Step 3: Implement**
  - `browserbase.py`: first check the current session-create fields at docs.browserbase.com (Exa) and keep the semantics the tests pin. `POST https://api.browserbase.com/v1/sessions` with header `X-BB-API-Key`; body from `browserbase_session_payload`: `projectId`, `proxies: False`, `timeout`, `browserSettings` with `solveCaptchas: False`, `advancedStealth: False`, no fingerprint key. `release_session` posts the release status. Every log line passes through `redact`; `connect_url` is never logged.
  - `fetchers.py`: `open_fetcher` is a context manager. `local`: headless Chromium, `new_context(user_agent=<our UA>)`. `browserbase`: create a session, `chromium.connect_over_cdp(connect_url)`, use the default context, set our UA per page through CDP `Network.setUserAgentOverride`; release the session in `finally`. `fetch`: `page.goto(url, wait_until="domcontentloaded", timeout=30000)`, return `PageResult(status=response.status if response else 0, html=page.content(), final_url=page.url)`.
  - `conftest.py`: `pytest_collection_modifyitems` skips `browser`-marked tests (reason `chromium not installed: uv run playwright install chromium`) unless `Path(sync_playwright().chromium.executable_path).exists()`.
  - CLI `crawl`: build `RobotsCache`, `Throttle`, `open_fetcher`, run `crawl_pages`, print the report as `key=value` lines plus the blocked and disallowed URLs; for `browserbase` also print `browserbase sessions used: 1` (the user logs it in `docs/spend-ledger.md`).
- [ ] **Step 4: Run to verify pass:** the Step 2 command; expected: all pass; the two `browser` tests pass with Chromium installed (`uv run playwright install chromium`), else they show as skipped. Then `pnpm check:pipeline` exits 0.
- [ ] **Step 5: Commit and land:** `git add pipeline && git commit -m "feat(refs): add playwright and browserbase backends with refs crawl command"`, then push and open the PR per Landing.

### Task 6: Classification export and import
**Files** (branch `feat/refs-classify`):
- Create: `pipeline/src/m3_pipeline/refs/classify.py`, `pipeline/tests/test_refs_classify.py`
- Modify: `pipeline/src/m3_pipeline/refs/cli.py` (sub-app `classify`)

**Interfaces:**
- Consumes: `RefStore`, `Labels`, `View`, `ImageRecord` (Task 1).
- Produces:
```python
class LabelLine(Labels): id: str   # one JSONL line; extra fields forbidden
class LabelImportError(Exception): errors: list[str]   # "line 3: unknown id ..."
@dataclass(frozen=True) class ExportResult: directory: Path; batches: list[Path]; images: int
def export_batches(store: RefStore, subject: str, *, batch_size: int = 40, out_dir: Path | None = None) -> ExportResult   # default <work_dir>/refs/classify/<subject>/
def render_classify_md(subject: str) -> str
@dataclass(frozen=True) class LabelImportResult: labeled: int; relabeled: int
def import_labels(store: RefStore, path: Path) -> LabelImportResult   # all-or-nothing
```
Batch file `batch-001.json`: `{"subject": s, "batch": 1, "of": N, "images": [{"id": sha, "path": "<absolute path>"}]}`. CLI: `pipeline refs classify export --subject <id> [--batch-size 40]`, `pipeline refs classify import <file>`.
- [ ] **Step 1: Write the failing tests**

```python
GOOD = lambda rec: {"id": rec.id, **make_labels().model_dump()}
def test_export_writes_batches_of_forty_and_a_classify_md(store):
    for i in range(85): ingest(store, make_image_bytes(i))
    r = export_batches(store, "e46-coupe"); batches = [json.loads(p.read_text()) for p in r.batches]
    assert [len(b["images"]) for b in batches] == [40, 40, 5] and r.images == 85 and (r.directory / "CLASSIFY.md").exists()
    assert all(Path(i["path"]).is_absolute() and Path(i["path"]).exists() for b in batches for i in b["images"])
def test_classify_md_embeds_every_enum_value_and_the_output_file_name():
    md = render_classify_md("e46-coupe"); assert all(v in md for v in get_args(View)) and "labels-001.jsonl" in md and "unknown" in md and "quality" in md
    assert all(w in md for w in ("drive_side", "lhd", "rhd", "seat", "driver", "passenger", "trim", "csl", "ducktail"))
# Also, one test each: `test_export_skips_duplicates_and_already_labeled`; `test_export_clears_stale_batch_files` (re-export after labeling leaves only the remaining batch files)
def test_import_marks_labeled_and_stores_labels(store, tmp_path):
    rec = ingest(store, make_image_bytes(1)); f = write_jsonl(tmp_path, [GOOD(rec)]); res = import_labels(store, f)
    assert res.labeled == 1 and store.get(rec.id).status == "labeled" and store.get(rec.id).labels.view == "front_34_left"
def test_import_is_all_or_nothing_and_reports_every_bad_line(store, tmp_path):
    rec = ingest(store, make_image_bytes(1)); g = GOOD(rec)
    f = write_jsonl(tmp_path, [g, {**g, "id": "f" * 64}, {**g, "view": "side"}, {**g, "quality": 6}])
    with pytest.raises(LabelImportError) as e: import_labels(store, f)
    assert len(e.value.errors) == 3 and e.value.errors[0].startswith("line 2") and store.get(rec.id).labels is None
# Also, one test each: `test_import_rejects_duplicate_ids_invalid_json_and_extra_fields`; `test_import_rejects_an_unknown_drive_side_or_trim_value` ("left", "gt" -> LabelImportError); `test_relabeling_overwrites_and_counts_it` (second import of the same id -> relabeled == 1); `test_labeling_a_duplicate_keeps_its_duplicate_status`; `test_classify_cli_roundtrip` (export, write labels from the batch file, import; output has "labeled=2")
```
- [ ] **Step 2: Run to verify failure:** `cd pipeline && uv run pytest tests/test_refs_classify.py -q`; expected: `ModuleNotFoundError: No module named 'm3_pipeline.refs.classify'`.
- [ ] **Step 3: Implement**
  - `export_batches`: candidates are the subject's records with `status == "new"`, sorted by id; delete existing `batch-*.json` and `CLASSIFY.md` in `out_dir`, then write batches (absolute paths via `store.image_path`) and `CLASSIFY.md`.
  - `render_classify_md`: instructions for any agent session with image access: read each batch file, open each image path, write one JSON object per line to `labels-<batch>.jsonl` next to it, one line per image, no commentary. Embed the field table built from `get_args` of the Literals, `Labels.model_json_schema()` and one example line. Rules: use `unknown` rather than guess; `stock` is `null` when it can't be told; judge only what is visible, never the file name; `quality` 1 (unusable) to 5 (sharp, well lit, unobstructed); `drive_side` is `lhd` or `rhd` from where the steering wheel sits and `unknown` when no steering wheel or other unmistakable cue is visible; `seat` is only for `interior_seats` and names the seat's role (`driver`, `passenger`, `both`), never its side; `interior_gauges` is a tight close-up of the instrument cluster and any wider dash shot is `interior_dash`; `trim` is `standard`, `csl`, `cs` or `gtr`, judged from visible cues only (a CSL has the carbon roof, the ducktail trunk lid and the single-intake front bumper), and `unknown` rather than a guess; put anything else notable (aftermarket parts) in `notes`.
  - `import_labels`: parse every non-blank line, collect all errors with 1-based line numbers (invalid JSON, pydantic errors, unknown id, id repeated in the file); raise `LabelImportError` if any; otherwise one `store.update` setting `labels` and `status="labeled"` (a `duplicate` record keeps its status).
  - CLI: `classify_app = typer.Typer()` attached as `classify`; `import` prints `labeled=N relabeled=N`, or the error list with exit 1.
- [ ] **Step 4: Run to verify pass:** the Step 2 command; expected: all pass. Then `pnpm check:pipeline` exits 0.
- [ ] **Step 5: Commit and land:** `git add pipeline && git commit -m "feat(refs): add classification batch export and validated label import"`, then push and open the PR per Landing.

### Task 7: Curation: dedupe, filter rules and background removal
**Files** (branch `feat/refs-curate`):
- Modify: `pipeline/pyproject.toml` (`uv add --group bg "rembg[cpu]==2.0.87"`), `pipeline/src/m3_pipeline/refs/cli.py`
- Create: `pipeline/src/m3_pipeline/refs/{dedupe,filters,cutouts}.py`, `pipeline/tests/{test_refs_dedupe.py,test_refs_filters.py,test_refs_cutouts.py}`

**Interfaces:**
- Consumes: `ImageRecord`, `Labels`, `RefStore`, `hamming`, `parse_subject`, `Kind`, `Body`, `Trim` (Task 1).
- Produces:
```python
# dedupe.py
def find_duplicates(records: Sequence[ImageRecord], max_distance: int = 6) -> dict[str, str]   # loser id -> winner id, per subject
@dataclass(frozen=True) class DedupeReport: duplicates: int; changed: int
def apply_dedupe(store: RefStore, subject: str | None = None) -> DedupeReport
# filters.py
@dataclass(frozen=True) class FilterTarget: kind: Kind; generation: str | None; body: Body | None; trim: Trim | None = None
    @classmethod def from_subject(cls, subject: str) -> "FilterTarget"   # base-car and interior subjects get trim "standard" (variants render as the standard car in v1); products None
@dataclass(frozen=True) class FilterDecision: accepted: bool; reasons: tuple[str, ...]
def evaluate(record: ImageRecord, target: FilterTarget) -> FilterDecision
# cutouts.py (rembg façade)
Remover = Callable[[Image.Image], Image.Image]
class BackgroundRemovalUnavailable(RuntimeError)
def load_remover(model: str = "birefnet-general", *, models_dir: Path) -> Remover   # lazy importlib.import_module("rembg"); sets U2NET_HOME
def cutout_relpath(image_id: str) -> str   # "refs/cutouts/<id>.png"
@dataclass(frozen=True) class CutoutReport: created: int; existing: int; failed: int
def make_cutouts(store: RefStore, subject: str, remover: Remover) -> CutoutReport   # only images that pass `evaluate`
```
CLI: `pipeline refs dedupe [--subject <id>]`, `pipeline refs cutouts --subject <id>` (models in `<work_dir>/refs/models`).
- [ ] **Step 1: Write the failing tests**

```python
def test_find_duplicates_keeps_larger_and_marks_resize(store):
    big = ingest(store, make_image_bytes(3)); small = ingest(store, resize_bytes(make_image_bytes(3), (500, 400))); other = ingest(store, make_image_bytes(9))
    d = find_duplicates(store.records()); assert d == {small.id: big.id} and other.id not in d
@pytest.mark.parametrize("bits,dup", [(6, True), (7, False)])
def test_threshold_boundary(bits, dup):
    a = make_record(id="a" * 64, phash="0" * 16); b = make_record(id="b" * 64, phash=format((1 << bits) - 1, "016x"), width=900, height=700)
    assert bool(find_duplicates([a, b])) is dup
def test_result_is_order_independent_and_scoped_per_subject():
    a, b = make_record(id="a" * 64, phash="0" * 16), make_record(id="b" * 64, phash="0" * 16, width=500, height=400)
    c = make_record(id="c" * 64, phash="0" * 16, subject="e46-coupe-interior"); assert find_duplicates([a, b, c]) == find_duplicates([c, b, a]) == {b.id: a.id}
# Also, one test each: `test_equal_size_ties_break_by_lower_id`; `test_apply_dedupe_sets_status_keeps_labels_and_is_idempotent` (first run changed == 1, labeled loser keeps labels, status "duplicate"; second run changed == 0); `test_apply_dedupe_restores_status_when_the_winner_set_changes` (a larger image arrives; labels intact)
# test_refs_filters.py
T = FilterTarget("base-car", "e46", "coupe", "standard"); L = make_labels
@pytest.mark.parametrize("labels,reason", [(None, "unlabeled"), (L(stock=False), "modified"), (L(generation="e36"), "wrong_generation"), (L(generation="unknown"), "wrong_generation"),
    (L(body="sedan"), "wrong_body"), (L(body="unknown"), "wrong_body"), (L(occlusion="major"), "major_occlusion"), (L(view="interior_dash"), "wrong_view_family"), (L(view="detail"), "wrong_view_family")])
def test_base_car_rejections(labels, reason): d = evaluate(make_record(labels=labels), T); assert not d.accepted and reason in d.reasons
def test_base_car_accepts_clean_stock_and_tolerates_unknown_stock_and_minor_occlusion():
    assert all(evaluate(make_record(labels=l), T).accepted for l in (L(), L(stock=None), L(occlusion="minor"), L(trim="unknown")))
def test_csl_rejected_for_standard_coupe():
    d = evaluate(make_record(labels=L(trim="csl")), T); assert not d.accepted and d.reasons == ("trim",)
    assert FilterTarget.from_subject("e46-coupe").trim == "standard" and FilterTarget.from_subject("product-wheel-a").trim is None
# Also, one test each: `test_duplicates_are_rejected_and_reasons_accumulate` (status "duplicate" -> "duplicate"; modified + wrong generation lists both); `test_interior_ignores_body_drive_side_and_major_occlusion_but_not_modified_or_generation` (accepts `interior_gauges` from an RHD car); `test_product_only_needs_a_label_a_product_view_and_non_duplicate`
# test_refs_cutouts.py
# Also, one test each: `test_make_cutouts_writes_rgba_png_for_accepted_images_only` (remover = lambda im: im.convert("RGBA"); the modified image gets no file; CutoutReport(created=1, ...)); `test_make_cutouts_skips_existing_and_survives_a_failing_remover` (existing == 1; a raising remover -> failed == 1, others continue)
def test_missing_rembg_gives_actionable_error(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "rembg", None)
    with pytest.raises(BackgroundRemovalUnavailable, match="uv sync --group bg"): load_remover(models_dir=tmp_path)
def test_importing_the_cli_does_not_import_rembg():
    out = subprocess.run([sys.executable, "-c", "import sys, m3_pipeline.cli; print('rembg' in sys.modules)"], capture_output=True, text=True); assert out.stdout.strip() == "False"
```
- [ ] **Step 2: Run to verify failure:** `cd pipeline && uv run pytest tests/test_refs_dedupe.py tests/test_refs_filters.py tests/test_refs_cutouts.py -q`; expected: collection errors `ModuleNotFoundError` for `dedupe`, `filters`, `cutouts`.
- [ ] **Step 3: Implement**
  - `find_duplicates`: group by subject; sort each group by `(-(width*height), id)`; greedy: keep a record unless it is within `max_distance` (`hamming` on the stored hashes) of an already-kept one, whose first match becomes its winner. Recomputed from all records each run, so ingest order does not matter.
  - `apply_dedupe`: loser -> `status="duplicate"`, `duplicate_of=winner`; a `duplicate` record that is no longer a loser -> `labeled` if it has labels else `new`, `duplicate_of=None`; one `store.update` call.
  - `evaluate`, collecting all reasons: no labels -> `unlabeled` and stop; `status == "duplicate"` -> `duplicate`; view outside the kind's family (base-car: `front, rear, side_*, *_34_*, top`; interior: `interior_*`; product: `product_*`; `detail` and `other` never) -> `wrong_view_family`. For `base-car` and `interior`: `stock is False` -> `modified`; `labels.generation != target.generation` (`unknown` included) -> `wrong_generation`; `target.trim` set and `labels.trim` neither equal to it nor `unknown` -> `trim`. For `base-car` only: `labels.body != target.body` (`unknown` included) -> `wrong_body`; `occlusion == "major"` -> `major_occlusion`.
  - `load_remover`: `os.environ.setdefault("U2NET_HOME", str(models_dir))`; `importlib.import_module("rembg")` (ImportError -> `BackgroundRemovalUnavailable("rembg is not installed; run `uv sync --group bg`")`); `new_session(model)`; return `lambda im: remove(im, session=session)`. The first use downloads a large model.
  - `make_cutouts`: for the subject's non-duplicate records that `evaluate` accepts, write `<work_dir>/refs/cutouts/<id>.png` (RGBA) unless it exists; catch per-image exceptions, log, count `failed`.
  - CLI: `dedupe` prints `duplicates=N changed=N`; `cutouts` prints `created=N existing=N failed=N`.
- [ ] **Step 4: Run to verify pass:** the Step 2 command; expected: all pass. Then `pnpm check:pipeline` exits 0 (the `bg` group is not installed).
- [ ] **Step 5: Commit and land:** `git add pipeline && git commit -m "feat(refs): add phash dedupe, filter rules and background removal"`, then push and open the PR per Landing.

### Task 8: View sets and credits
**Files** (branch `feat/refs-viewsets`):
- Create: `pipeline/src/m3_pipeline/refs/{viewsets,credits}.py`, `pipeline/tests/{test_refs_viewsets.py,test_refs_credits.py}`
- Modify: `pipeline/src/m3_pipeline/refs/cli.py` (sub-app `viewsets`, command `credits`)

**Interfaces:**
- Consumes: `ImageRecord`, `RefStore.image_relpath`, `parse_subject` (Task 1); `evaluate`, `FilterTarget`, `cutout_relpath` (Task 7).
- Produces:
```python
EXTERIOR_PRIORITY = ("front_34_left","rear_34_right","side_left","front","rear")
INTERIOR_ORDER = ("interior_dash","interior_gauges","interior_steering","interior_seats","interior_door","interior_console")   # six interior components, each its own multi-view set
DRIVE_DEPENDENT = ("interior_dash","interior_door")   # LHD preferred; RHD only as mirrored=True with contains_text_risk=True
NEVER_MIRRORED = ("interior_steering","interior_gauges")
PRODUCT_ORDER = ("product_34","product_front","product_side","product_detail")
MIRROR_OF: dict[str, str]   # front_34_left<->front_34_right, rear_34_left<->rear_34_right, side_left<->side_right
@dataclass(frozen=True) class ViewsetPolicy: max_views: int = 5; min_views: int = 3; prefer_market: Literal["us","euro"] | None = "us"
    spread_bits: int = 12   # max_views caps an exterior or product set and each interior component; min_views is the floor before a set is ok or a component is not missing
def score_image(record: ImageRecord, policy: ViewsetPolicy = ViewsetPolicy()) -> float
def is_cc_or_pd(license_short: str) -> bool
def pick_spread(ranked: Sequence[ImageRecord], limit: int, *, taken: Sequence[ImageRecord] = (), min_distance: int = 12) -> list[ImageRecord]
    # rank-ordered in; pass 1 keeps images whose pHash is > min_distance bits from every chosen or taken image, or whose non-unknown seat label is new; pass 2 fills the rest in rank order
class ViewEntry(BaseModel): view: str; image_id: str; image_path: str; cutout_path: str | None; mirrored: bool; score: float
    source_kind: SourceKind; license_short: str; license_url: str | None; author: str | None; page_url: str | None
    drive_side: str; seat: str | None; contains_text_risk: bool   # seat only for interior_seats
class ViewSet(BaseModel): subject: str; kind: Kind; views: list[ViewEntry]   # exterior and product: one entry per slot, <= max_views
    components: dict[str, list[ViewEntry]]   # interior only: keys from INTERIOR_ORDER, each a rank-ordered list of <= max_views entries, absent when empty
    missing: list[str]   # exterior/product: slots with no image; interior: components with fewer than min_views entries
    all_cc_or_pd: bool; licenses: list[str]; rejected: dict[str, int]
    def entries(self) -> list[ViewEntry]   # views plus every component entry
def build_viewset(subject: str, records: Sequence[ImageRecord], *, cutouts: Collection[str] = (), policy: ViewsetPolicy = ViewsetPolicy()) -> ViewSet
def write_viewset(store: RefStore, subject: str, dest: Path, *, policy: ViewsetPolicy = ViewsetPolicy()) -> ViewSet   # finds existing cutouts on disk
def render_credits(viewset: ViewSet) -> str
```
Paths in `ViewEntry` are relative to `work_dir`; a consumer flips `mirrored` entries horizontally and treats `contains_text_risk` entries as having reversed text. `viewset.json` has `views` for exterior and product sets and `components` for interior sets. Stored set: `<work_dir>/refs/viewsets/<subject>.json`. CLI: `pipeline refs viewsets build --subject <id>`, `pipeline refs credits --subject <id>`.
- [ ] **Step 1: Write the failing tests**

```python
def rec(i, view, lab=None, **kw): return make_record(id=f"{i:064x}", labels=make_labels(view=view, **(lab or {})), **kw)
def test_exterior_picks_priority_views_in_order():
    vs = build_viewset("e46-coupe", [rec(i, v) for i, v in enumerate(["rear", "front", "side_left", "rear_34_right", "front_34_left", "top"], 1)])
    assert [e.view for e in vs.views] == list(EXTERIOR_PRIORITY) and vs.missing == [] and not any(e.mirrored for e in vs.views)
# Also, one test each: `test_missing_left_view_is_filled_by_mirroring_the_right` (only side_right -> entry "side_left", mirrored True, image_id == right's; other views in `missing`); `test_direct_view_beats_a_mirrored_one`; `test_product_sets_never_mirror`; `test_exterior_mirroring_is_unchanged_and_carries_no_text_risk_flag`
INT = "e46-coupe-interior"; irec = lambda i, view, side, **lab: rec(i, view, lab={"drive_side": side, **lab}); flags = lambda es: [(e.mirrored, e.contains_text_risk) for e in es]
def test_each_interior_component_takes_up_to_five_views():
    vs = build_viewset(INT, [irec(i, "interior_steering", "lhd") for i in range(1, 8)] + [irec(20, "interior_seats", "lhd", seat="driver")])
    assert len(vs.components["interior_steering"]) == 5 and len(vs.components["interior_seats"]) == 1 and vs.views == []
def test_interior_component_under_min_views_is_reported_missing():
    vs = build_viewset(INT, [irec(i, "interior_console", "lhd") for i in (1, 2)] + [irec(i, "interior_steering", "lhd") for i in (3, 4, 5)])
    assert len(vs.components["interior_console"]) == 2 and {"interior_console", "interior_dash"} <= set(vs.missing) and "interior_steering" not in vs.missing
def test_spread_prefers_visually_distinct_images_then_fills_by_rank():
    a, b, c = (make_record(id=f"{i:064x}", phash=h) for i, h in ((1, "0" * 16), (2, "0" * 15 + "1"), (3, "f" * 16)))
    assert [r.id for r in pick_spread([a, b, c], 2)] == [a.id, c.id] and [r.id for r in pick_spread([a, b, c], 3)] == [a.id, c.id, b.id]
def test_seats_with_different_seat_labels_count_as_distinct():
    mk = lambda i, seat: make_record(id=f"{i:064x}", phash="0" * 16, labels=make_labels(view="interior_seats", seat=seat))
    d1, d2, p = mk(1, "driver"), mk(2, "driver"), mk(3, "passenger"); assert [r.id for r in pick_spread([d1, d2, p], 2)] == [d1.id, p.id]
def test_rhd_steering_gauges_and_console_are_used_as_is_and_never_mirrored():
    vs = build_viewset(INT, [irec(1, "interior_steering", "rhd"), irec(2, "interior_gauges", "rhd"), irec(3, "interior_console", "rhd")])
    assert {c: flags(es) for c, es in vs.components.items()} == {"interior_gauges": [(False, False)], "interior_steering": [(False, False)], "interior_console": [(False, False)]}
@pytest.mark.parametrize("side", ["lhd", "rhd", "unknown"])
def test_steering_and_gauges_are_never_mirrored_whatever_the_drive_side(side):
    vs = build_viewset(INT, [irec(1, v, side) for v in NEVER_MIRRORED]); assert set(vs.components) == set(NEVER_MIRRORED) and not any(e.mirrored for e in vs.entries())
def test_lhd_whole_dash_entries_rank_before_rhd_ones_which_are_mirrored_and_flagged():
    es = build_viewset(INT, [irec(1, "interior_dash", "lhd", quality=2), irec(2, "interior_dash", "rhd", quality=5)]).components["interior_dash"]
    assert [(e.image_id, e.mirrored, e.contains_text_risk) for e in es] == [(f"{1:064x}", False, False), (f"{2:064x}", True, True)]
def test_rhd_whole_dash_is_used_only_mirrored_and_flagged_when_no_lhd_exists():
    e = build_viewset(INT, [irec(2, "interior_dash", "rhd")]).components["interior_dash"][0]; assert (e.mirrored, e.contains_text_risk, e.drive_side) == (True, True, "rhd")
def test_whole_dash_with_unknown_drive_side_is_skipped_and_counted():
    vs = build_viewset(INT, [irec(1, "interior_dash", "unknown")]); assert "interior_dash" not in vs.components and vs.rejected["drive_side_unknown"] == 1
def test_seats_are_valid_from_either_drive_side_and_record_which_seat():
    e = build_viewset(INT, [irec(1, "interior_seats", "rhd", seat="driver")]).components["interior_seats"][0]; assert (e.seat, e.mirrored, e.contains_text_risk) == ("driver", False, False)
# Also, one test each: `test_door_follows_the_whole_dash_rule` (LHD entries first; RHD only mirrored with contains_text_risk)
def test_best_score_wins_and_ties_break_by_lower_id():
    hi, lo = rec(1, "front", lab={"quality": 5}), rec(2, "front", lab={"quality": 3}); assert build_viewset("e46-coupe", [lo, hi]).views[0].image_id == hi.id
    assert score_image(rec(1, "front")) > score_image(rec(1, "front", lab={"occlusion": "minor"}))
    assert build_viewset("e46-coupe", [rec(2, "front"), rec(1, "front")]).views[0].image_id == rec(1, "front").id
# Also, one test each: `test_rejected_images_are_never_selected_and_are_counted` (modified / wrong body / major occlusion -> vs.rejected == {"modified": 1, ...}); `test_exterior_set_is_capped_at_max_views_and_lists_missing_views`; `test_empty_candidates_give_an_empty_set_not_an_error` (views == [] and components == {}, all_cc_or_pd is False)
@pytest.mark.parametrize("name,ok", [("CC BY-SA 4.0", True), ("CC BY 2.0", True), ("CC0", True), ("Public domain", True), ("PD-USGov", True),
    ("CC BY-NC 4.0", False), ("CC BY-ND 2.0", False), ("GFDL 1.2", False), ("unknown", False), ("", False)])
def test_is_cc_or_pd(name, ok): assert is_cc_or_pd(name) is ok
def test_unknown_license_blocks_all_cc_or_pd():
    open_, unk = rec(1, "front", license_short="CC BY-SA 4.0"), rec(2, "rear", license_short="unknown", source_kind="commons")
    assert build_viewset("e46-coupe", [open_]).all_cc_or_pd and not build_viewset("e46-coupe", [open_, unk]).all_cc_or_pd
# Also, one test each: `test_paths_are_relative_and_cutouts_attach_only_for_known_ids` (image_path == "refs/images/<id[:2]>/<id>.jpg")
# test_refs_credits.py
# Also, one test each: `test_credits_list_commons_entries_once_with_author_license_and_urls` (a mirrored plus direct use of one image appears once; line has author, license short, license url, page url); `test_credits_mark_unknown_author_and_count_non_commons_images` ("Author unknown" text; trailing "Not credited: N non-Commons images"); `test_viewsets_build_cli_writes_json_and_credits_cli_reads_it` (refs/viewsets/e46-coupe.json exists; credits exits 1 with a hint when not built)
```
- [ ] **Step 2: Run to verify failure:** `cd pipeline && uv run pytest tests/test_refs_viewsets.py tests/test_refs_credits.py -q`; expected: collection errors `ModuleNotFoundError: m3_pipeline.refs.viewsets`.
- [ ] **Step 3: Implement**
  - `score_image` (labels required): `quality*20 + min(min(width, height), 2000)/2000*20 - {none: 0, minor: 10, major: 40}[occlusion] - (5 if stock is None else 0) + (5 if market == policy.prefer_market else 0)`.
  - `build_viewset` (does not filter by `record.subject`; callers pass the subject's records): `FilterTarget.from_subject`; `evaluate` every record and count rejection reasons; rank accepted records per slot by `(score, open license, lower id)` descending.
    - Exterior and product: one entry per slot of `EXTERIOR_PRIORITY` / `PRODUCT_ORDER`, up to `max_views`. An exterior slot with no direct image and a `MIRROR_OF` partner takes the best partner image with `mirrored=True` (no text-risk flag); otherwise it goes to `missing`.
    - Interior: per component in `INTERIOR_ORDER`, `pick_spread(ranked, max_views, min_distance=policy.spread_bits)`. A component with no entries is absent from `components`; every component with fewer than `min_views` entries goes to `missing`.
    - Per-entry rules: steering, gauges, console and seats entries come from any drive side, are never mirrored (`NEVER_MIRRORED` is asserted), and seats entries record `labels.seat`. In `DRIVE_DEPENDENT` components the ranking is tiered: `lhd` candidates first, unmirrored, then `rhd` candidates with `mirrored=True` and `contains_text_risk=True`; each tier goes through `pick_spread` with the earlier picks as `taken`, so an RHD entry appears only when fewer than `max_views` LHD ones exist. An `unknown` drive side is skipped and counted in `rejected["drive_side_unknown"]`.
    - `pick_spread` compares stored pHashes with `hamming`. `licenses` is the sorted unique `license_short` over `entries()`; `all_cc_or_pd = bool(entries) and all(is_cc_or_pd(...))`.
  - `is_cc_or_pd`: true for `^CC0`, `^CC BY(-SA)? \d`, `^(Public domain|PD)\b`, `^No restrictions`; everything else false (NC, ND, GFDL, unknown). Design section 3 ties the published model license to this flag.
  - `write_viewset` writes `model_dump_json(indent=2)` atomically. `render_credits`: Markdown list of Commons entries (from `entries()`) deduplicated by `image_id`: `- <author or "Author unknown (see file page)"> - <license short> (<license url or "no license URL">) - <page url>`, then `Not credited: N non-Commons images in this set.` when N > 0.
  - CLI: `viewsets build` prints each entry (grouped by component for interior sets) with score, `mirrored`, `contains_text_risk`, license, then `missing=`, `all_cc_or_pd=` and rejection counts; `credits` reads the stored JSON and prints Markdown.
- [ ] **Step 4: Run to verify pass:** the Step 2 command; expected: all pass. Then `pnpm check:pipeline` exits 0.
- [ ] **Step 5: Commit and land:** `git add pipeline && git commit -m "feat(refs): add view-set selection, license flag and credits output"`, then push and open the PR per Landing.

### Task 9: Description builder and the `refs` stage
**Files** (branch `feat/refs-description`):
- Create: `pipeline/src/m3_pipeline/refs/description.py`, `pipeline/src/m3_pipeline/stages/refs.py`, `pipeline/descriptions/.gitkeep`, `pipeline/tests/{test_refs_description.py,test_refs_stage.py}`, `pipeline/tests/fixtures/refs/data/{generations/e46.yaml,parts/e46/wheel-a.yaml}` (synthetic values: length 4500, width 1800, height 1350, wheelbase 2700, tracks 1500/1520; not authoritative)
- Modify: the place where 0A imports `stages/validate.py` (add the same import for `stages/refs.py`)

**Interfaces:**
- Consumes: `AssetSpec`, `Settings`, `StageResult`, `register`, `REGISTRY` (0A); `write_viewset`, `ViewsetPolicy`, `INTERIOR_ORDER`, `ViewSet.entries()` (Task 8); `parse_subject` (Task 1).
- Produces:
```python
class DescriptionError(ValueError)
def build_description(spec: AssetSpec, settings: Settings) -> str   # Markdown
@register("refs") def refs_stage(spec: AssetSpec, settings: Settings) -> StageResult
```
`build_description` reads `<repo_root>/data/generations/<spec.generation>.yaml` (`id, name, chassis, years, engines[{code,...}], bodies, dimensions`) or, for products, `<repo_root>/data/parts/<spec.generation>/<part_id>.yaml` (`id, name, brand?, category, attributes?, options?[{id,label,attributes}]`), plus optional `<repo_root>/pipeline/descriptions/<subject>.md`. The stage writes `<work_dir>/assets/<asset_id>/refs/viewset.json` and `description.md` and lists both in `outputs`, even when `ok` is false. Test fixture `repo` = `Settings` over a tmp copy of `tests/fixtures/refs`.
- [ ] **Step 1: Write the failing tests**

```python
def test_base_car_description_has_prompt_dimensions_and_checklist(repo):
    d = build_description(AssetSpec("e46-coupe-body", "base-car", "e46", "e46-coupe"), repo)
    assert "## Generator prompt" in d and "## Critic checklist" in d and "E46 M3" in d and "coupe" in d and "2001" in d and "S54" in d
    assert "4500 mm" in d and "4.500 m" in d and "2700 mm" in d and "1500 mm" in d
    assert "- [ ] No manufacturer badges, logos or roundels" in d and "left-hand drive" in d
# Also, one test each: `test_interior_description_lists_components_and_left_hand_drive` (dash with gauge cluster, steering wheel, seats, door cards, center console; "no roundel on the steering wheel or gauges"); `test_product_description_comes_from_part_yaml` (name, category, attributes as "key: value", each option label in the checklist); `test_hand_written_notes_are_appended_verbatim` (pipeline/descriptions/e46-coupe.md under "## Notes (hand-written)"; no file, no section)
def test_missing_generation_body_or_part_raises_description_error_naming_the_file(repo):
    with pytest.raises(DescriptionError, match="convertible"): build_description(AssetSpec("x", "base-car", "e46", "e46-convertible"), repo)  # fixture bodies list only coupe
# Also, one test each: `test_engine_extras_render_as_sorted_key_value_pairs` ({code: S54, displacement: "3.2 L"} -> "S54 (displacement 3.2 L)")
# test_refs_stage.py
def test_refs_is_registered_through_the_cli_import(): import m3_pipeline.cli; assert "refs" in REGISTRY
# Also, one test each: `test_refs_stage_writes_viewset_and_description` (3+ accepted labeled images -> ok True; both files exist; viewset.json parses as ViewSet; outputs lists both); `test_refs_stage_is_not_ok_below_min_views_but_still_writes_outputs` (exterior with 2 views -> ok False, messages name the missing views); `test_refs_stage_interior_needs_every_component_at_min_views` (five components at 3 entries and one at 2 -> ok False and the message names the short one; all six at 3 -> ok True); `test_refs_stage_reports_description_error_as_not_ok` (unknown part id -> ok False, message names the YAML path); `test_refs_stage_flags_subject_kind_mismatch` (kind "interior" with subject "e46-coupe" -> ok False); `test_refs_stage_messages_flag_text_risk_views` (a mirrored RHD dash adds a message line)
```
- [ ] **Step 2: Run to verify failure:** `cd pipeline && uv run pytest tests/test_refs_description.py tests/test_refs_stage.py -q`; expected: collection errors `ModuleNotFoundError: m3_pipeline.refs.description`.
- [ ] **Step 3: Implement**
  - `build_description` layout: `# <subject> reference description`; `## Generator prompt` (one paragraph from the data); `## Critic checklist` (`- [ ]` lines: body style, each dimension in mm "within 1%", stock appearance, wheels are placeholders the pipeline replaces, the no-badges line); `## Notes (hand-written)` only when the notes file exists. Dimensions print as `<n> mm` and metres to three decimals; engines as `code` plus other scalar fields as `key value` sorted by key. Base car prompt: generation `name`, body, years, "US-spec, left-hand drive". Interior: left-hand-drive cabin and the component list from design section 9.2. Products: part YAML only. `yaml.safe_load`; a missing file or key raises `DescriptionError` naming it, never a guessed value.
  - `refs_stage`: `parse_subject(spec.subject)`; a kind that differs from `spec.kind` -> not ok. `write_viewset` to `<work_dir>/assets/<id>/refs/viewset.json`; description to `description.md` (both written even when the set is short). `ok` needs the description built and a complete enough set: exterior or product `len(views) >= policy.min_views`; interior every component in `INTERIOR_ORDER` with at least `min_views` entries, the short ones listed in the messages (`vs.missing`). Messages also list rejection counts and one line per `contains_text_risk` entry in `entries()` (`interior_dash: mirrored RHD image, text may be reversed`).
- [ ] **Step 4: Run to verify pass:** the Step 2 command; expected: all pass. Then `pnpm check:pipeline` exits 0.
- [ ] **Step 5: Commit and land:** `git add pipeline && git commit -m "feat(refs): add description builder and refs stage"`, then push and open the PR per Landing.

### Task 10: R2 sync, end-to-end smoke test and runbook
**Files** (branch `feat/refs-sync-runbook`):
- Modify: `pipeline/pyproject.toml` (`uv add boto3==1.44.9`), `pipeline/src/m3_pipeline/refs/cli.py` (sub-app `sync`)
- Create: `pipeline/src/m3_pipeline/refs/sync.py`, `docs/runbooks/refs-collection.md`, `pipeline/tests/{test_refs_sync.py,test_refs_e2e.py,test_refs_runbook.py}`

**Interfaces:**
- Consumes: `RefStore`, `Manifest`, `ImageRecord` (Task 1) and every earlier command through its library function.
- Produces:
```python
MANIFEST_KEY = "manifest.jsonl"; BUCKET = "m3-tool-refs"
class SyncError(Exception)
class ObjectStore(Protocol): def list_keys(self, prefix: str = "") -> set[str]; def put_file(self, key: str, path: Path) -> None; def get_file(self, key: str, dest: Path) -> None
class R2Store: def __init__(self, client: Any, bucket: str = BUCKET) -> None   # boto3 façade
def make_r2_client(env: Mapping[str, str]) -> Any   # endpoint https://<M3_R2_ACCOUNT_ID>.r2.cloudflarestorage.com, region "auto"; SyncError names missing variables only
def remote_key(record: ImageRecord) -> str   # "images/<sha[:2]>/<sha>.<ext>"
def merge_manifests(local: Sequence[ImageRecord], remote: Sequence[ImageRecord]) -> list[ImageRecord]   # union by id; local wins unless only the remote one is labeled
@dataclass(frozen=True) class SyncReport: uploaded: int; downloaded: int; skipped: int
def push(store: RefStore, remote: ObjectStore, *, force: bool = False) -> SyncReport
def pull(store: RefStore, remote: ObjectStore) -> SyncReport
# tests/refs_fakes.py
class FakeObjectStore: ...   # dict-backed ObjectStore; .put_order: list[str]; .fail_after_puts: int | None makes that put raise OSError
```
CLI: `pipeline refs sync push [--force]`, `pipeline refs sync pull`.
- [ ] **Step 1: Write the failing tests**

```python
def test_push_uploads_only_missing_hashes_and_the_manifest_last(store):
    for i in range(3): ingest(store, make_image_bytes(i))
    remote = FakeObjectStore(); rep = push(store, remote)
    assert rep.uploaded == 3 and remote.put_order[-1] == MANIFEST_KEY and set(remote.list_keys()) == {remote_key(r) for r in store.records()} | {MANIFEST_KEY}
    assert push(store, remote).uploaded == 0
def test_interrupted_push_never_leaves_a_manifest_that_references_missing_objects(store):
    for i in range(3): ingest(store, make_image_bytes(i))
    remote = FakeObjectStore(fail_after_puts=2)
    with pytest.raises(OSError): push(store, remote)
    assert MANIFEST_KEY not in remote.list_keys(); remote.fail_after_puts = None; assert push(store, remote).uploaded == 1
# Also, one test each: `test_push_refuses_to_overwrite_a_remote_manifest_with_unknown_records` (remote ids missing locally -> SyncError "pull" hint; force=True proceeds); `test_pull_downloads_missing_images_then_merges_the_manifest` (fresh store ends with the remote's ids and files); `test_pull_rejects_an_object_whose_hash_does_not_match_its_key` (tampered bytes -> SyncError, nothing placed in the store); `test_merge_manifests_unions_and_prefers_remote_only_when_it_alone_is_labeled`
def test_make_r2_client_names_missing_variables_only():
    with pytest.raises(SyncError) as e: make_r2_client({"M3_R2_ACCESS_KEY_ID": "test-key"})
    assert "M3_R2_ACCOUNT_ID" in str(e.value) and "M3_R2_SECRET_ACCESS_KEY" in str(e.value) and "test-key" not in str(e.value)
# Also, one test each: `test_make_r2_client_targets_the_account_endpoint` (client.meta.endpoint_url == "https://acct.r2.cloudflarestorage.com")
# test_refs_e2e.py: the whole flow on generated images, no network
def test_full_flow_from_collection_to_refs_stage_and_back_through_sync(repo, store, tmp_path):
    ...  # FakeWikimedia (one CC BY-SA image with author, one with no extmetadata) -> collect; import_directory adds 4 more views (unknown license); apply_dedupe; export_batches; labels from the batch files; import_labels
    ...  # REGISTRY["refs"](spec, repo): ok; viewset.json lists the CC BY-SA image with mirrored False; all_cc_or_pd False; render_credits names the author; push, then pull into a fresh store: records equal
# test_refs_runbook.py
def test_every_command_in_the_runbook_exists():
    text = (load_settings().repo_root / "docs/runbooks/refs-collection.md").read_text()
    cmds = re.findall(r"^uv run pipeline (refs(?: [a-z]+){1,2})", text, re.M)
    assert cmds and all(CliRunner().invoke(app, [*c.split(), "--help"]).exit_code == 0 for c in cmds)
def test_runbook_states_the_hard_rules_and_the_blocked_site_fallback():
    t = (load_settings().repo_root / "docs/runbooks/refs-collection.md").read_text().lower()
    assert all(s in t for s in ("robots.txt", "captcha", "proxy", "user-agent", "never commit", "m3-tool-refs", "unknown", "normal browser", "refs import", "e46/2s", "drive_side"))
```
- [ ] **Step 2: Run to verify failure:** `cd pipeline && uv run pytest tests/test_refs_sync.py tests/test_refs_e2e.py tests/test_refs_runbook.py -q`; expected: collection errors `ModuleNotFoundError: m3_pipeline.refs.sync`.
- [ ] **Step 3: Implement `sync.py`**
  - `push`: upload every local image whose `remote_key` is absent from `remote.list_keys("images/")` (duplicates included; the manifest references them). Then, if `MANIFEST_KEY` exists remotely and `force` is false, read it and raise `SyncError("remote manifest has N records missing locally; run `pipeline refs sync pull` first or pass --force")` when it holds unknown ids. Upload the local manifest last.
  - `pull`: download missing images to a temp file, verify `sha256` equals the hash in the key, then move into `refs/images/`; download the manifest to a temp file, `merge_manifests`, `store.update`. Remote images without a manifest record are ignored.
  - `R2Store` wraps `list_objects_v2` pagination, `upload_file`, `download_file`; CLI builds `R2Store(make_r2_client(os.environ))`, prints `SyncError` and exits 1.
- [ ] **Step 4: Write `docs/runbooks/refs-collection.md`.** Sections in this order; each command in a fenced block starts with `uv run pipeline refs ...` run from `pipeline/`:
  1. **What this stores.** A private local store under `M3_WORK_DIR`; images and the manifest are never committed.
  2. **Setup.** `uv sync`; `uv run playwright install chromium`; optional `uv sync --group bg` (the first cutout run downloads a large model into `<work_dir>/refs/models`); env var names from `~/.config/secrets.env`; `uv run pipeline refs stats`.
  3. **Commons.** Edit `pipeline/refs-sources.toml`; show the example config (`Category:BMW M3 (E46/2S)` coupe, 369 files; `Category:BMW M3 (E46/2CS)` convertible, 144 files, useful for front-interior shots; `Category:BMW M3 CSL (E46)`, 74 files, can go into the same subject because the classifier labels its trim and the filter drops it; `search_terms` such as "E46 M3 interior" for thin interior coverage). Run `refs commons --subject e46-coupe`. At the 3 s default a full category takes about 20 minutes. Commons answers 429 to fast clients: the tool backs off by `Retry-After` and stops with a message after 3 retries; rerun later and it resumes. Thumbnails: the default `thumb_width` is 1920, a standard Wikimedia step (2560 is not one); if a run stops on "thumbnail width rejected", set it to 1920 or 3840.
  4. **Your own photos.** `refs import <dir> --subject <id> --source-note "..."` with `--license` only when you can assert one (default `unknown`); convert HEIC first (`sips -s format jpeg`); JPEG, PNG, WebP and AVIF work. **Product photos from sites behind bot checkpoints** (for example apexwheels.com answers 429 with a Vercel Security Checkpoint) come in this way: save the images in a normal browser, then import them with `--subject product-<part-id>`.
  5. **Crawler.** Seed URLs in the toml or `--url`; it visits only those URLs; `--backend local` or `browserbase`; log Browserbase use in `docs/spend-ledger.md`; a "blocked" line means drop that source or import by hand, never work around it.
  6. **Curation.** `refs dedupe`; classification with another model (`refs classify export`, point the other harness at `CLASSIFY.md`, `refs classify import`); `refs cutouts`; `refs viewsets build`; `refs credits`; how to read `missing` views; interior sets collect up to 5 views for each of the six components and a component with fewer than 3 is reported missing; nothing is edited by hand, rerun instead. Many Commons interior photos are UK right-hand-drive cars (the Flickr "The Car Spy" sets): label `drive_side` honestly. RHD steering, gauge-cluster, console and seat photos are used as-is; an RHD whole dash or door is used only mirrored and flagged `contains_text_risk`; steering and gauge images are never mirrored.
  7. **Sync.** `refs sync push` and `pull`; manifest uploaded last; the "pull first" guard.
  8. **Brief for another model or harness.** A paste-ready block: working directory, allowed commands, env var names, the hard rules, and "report the numbers; do not fix blocked sources".
  9. **What the tool deliberately won't do.** No stealth, proxy rotation, captcha solving or browser UA spoofing; no link-following; no license guessing; no images or manifest in the repo; no HEIC; robots.txt and the host delay are not switches.
- [ ] **Step 5: Run to verify pass:** the Step 2 command; expected: all pass. Then `pnpm check:pipeline` exits 0 and `gitleaks git --redact` reports no leaks.
- [ ] **Step 6: Commit and land:** `git add pipeline docs/runbooks/refs-collection.md && git commit -m "feat(refs): add r2 sync, end-to-end smoke test and collection runbook"`, then push and open the PR per Landing.
