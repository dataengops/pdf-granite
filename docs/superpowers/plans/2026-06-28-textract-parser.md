# Amazon Textract Comparison Parser — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a standalone `pdf-textract` script that parses local or `s3://` PDFs with Amazon Textract (LAYOUT + TABLES) and writes `output/textract/<name>.md` plus the raw Textract JSON, parallel to the other comparison outputs.

**Architecture:** A single new module `src/pdf_granite/textract.py` with its own console entry point, mirroring `convert.py`'s structure (argparse `build_parser`, `_die`, batch `main` with continue-on-error). All AWS/Textractor and boto3 imports are **lazy** (inside functions), exactly like `convert.py` imports docling — so the core module imports and unit tests run without the AWS stack installed. Textractor's async `start_document_analysis` runs the job; `document.to_markdown()` builds the markdown; `document.response` is dumped as JSON.

**Tech Stack:** Python 3.13, argparse, `amazon-textract-textractor` (pulls in boto3), pytest. Packaged with hatchling + uv.

## Global Constraints

- Python `>=3.13` (matches existing `requires-python`).
- AWS credentials live in a project `.env` file (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `S3_BUCKET`). `main()` loads `.env` via `python-dotenv` so boto3 picks creds/region up from the environment — never CLI flags. `.env` MUST be gitignored.
- `--bucket` defaults to the `S3_BUCKET` env var (from `.env`) when not passed.
- Textract features are **LAYOUT + TABLES only** (no FORMS/signatures/queries).
- Markdown only (no HTML).
- `amazon-textract-textractor` lives in an **optional** dependency group `textract`, NOT core deps. All its imports (and boto3) are lazy, inside functions.
- Output convention: files go to `<output-dir>/textract/<stem>.md` and `<stem>.json`.
- Follow `convert.py` conventions: `_die(msg, code)` for fatal pre-flight errors; per-file try/except continue-on-error; final `Done: N converted, M failed`; `--quiet` suppresses per-step logs but keeps the final summary.
- The known project input already lives at `s3://input1972/SMR-1Q26-Presentation.pdf`.

---

## File Structure

- **Create** `src/pdf_granite/textract.py` — the entire feature (parser, source resolution, region detection, analysis, output writing, main).
- **Create** `tests/test_textract.py` — unit tests; all AWS calls mocked.
- **Modify** `pyproject.toml` — add `pdf-textract` console script + `textract` optional dependency group.
- **Modify** `README.md` — add a short "Amazon Textract (comparison)" section.

---

### Task 1: Scaffolding — pyproject wiring + parser + gitignore .env

**Files:**
- Create: `src/pdf_granite/textract.py`
- Modify: `pyproject.toml`
- Modify: `.gitignore`
- Test: `tests/test_textract.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `build_parser() -> argparse.ArgumentParser` with attributes: `paths: list[str]`, `bucket: str | None`, `region: str | None`, `s3_prefix: str`, `input_dir: str`, `output_dir: str`, `quiet: bool`.
  - `_die(msg: str, code: int) -> None` (raises `SystemExit(code)`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_textract.py
import json
from pathlib import Path

import pytest

from pdf_granite import textract


def test_parser_defaults():
    ns = textract.build_parser().parse_args([])
    assert ns.paths == []
    assert ns.bucket is None
    assert ns.region is None
    assert ns.s3_prefix == "textract-scratch/"
    assert ns.input_dir == "input"
    assert ns.output_dir == "output"
    assert ns.quiet is False


def test_parser_overrides():
    ns = textract.build_parser().parse_args(
        [
            "s3://b/x.pdf",
            "--bucket", "mybucket",
            "--region", "us-west-2",
            "--s3-prefix", "scratch/",
            "--input-dir", "in",
            "--output-dir", "out",
            "--quiet",
        ]
    )
    assert ns.paths == ["s3://b/x.pdf"]
    assert ns.bucket == "mybucket"
    assert ns.region == "us-west-2"
    assert ns.s3_prefix == "scratch/"
    assert ns.input_dir == "in"
    assert ns.output_dir == "out"
    assert ns.quiet is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/test_textract.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'pdf_granite.textract'` (or AttributeError on `build_parser`).

- [ ] **Step 3: Write minimal implementation**

```python
# src/pdf_granite/textract.py
"""pdf-textract — parse PDFs with Amazon Textract -> Markdown (+ raw JSON).

A standalone comparison parser, separate from the Docling `pdf-granite` CLI.
Sources may be local PDF paths or `s3://` URIs. Multi-page PDFs require
Textract's async API, which needs the document in S3: local files are uploaded
to `--bucket`/`--s3-prefix`; `s3://` sources are read in place.

AWS credentials are loaded from the project `.env` (AWS_ACCESS_KEY_ID,
AWS_SECRET_ACCESS_KEY, AWS_REGION, S3_BUCKET) into the environment for boto3.
All AWS/Textractor imports are lazy (inside functions) so this module imports
without the optional `textract` dependency group installed.
"""

from __future__ import annotations

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pdf-textract",
        description="Parse PDFs with Amazon Textract (LAYOUT + TABLES) to Markdown + raw JSON.",
    )
    p.add_argument(
        "paths",
        nargs="*",
        help="PDF sources: local files or s3:// URIs (default: all *.pdf in --input-dir).",
    )
    p.add_argument(
        "--bucket",
        default=None,
        help="Existing S3 bucket used as scratch for uploading LOCAL sources. "
        "Not needed when all sources are s3:// URIs.",
    )
    p.add_argument(
        "--region",
        default=None,
        help="AWS region. Default: auto-detected from the bucket (GetBucketLocation), "
        "falling back to us-east-1. Must match the bucket's region.",
    )
    p.add_argument(
        "--s3-prefix",
        default="textract-scratch/",
        help="Key prefix for uploaded local PDFs (default: textract-scratch/).",
    )
    p.add_argument("--input-dir", default="input", help="Folder scanned when no paths are given.")
    p.add_argument("--output-dir", default="output", help="Base output dir; files go to <output-dir>/textract/.")
    p.add_argument("--quiet", action="store_true", help="Suppress per-step logging; keep final summary.")
    return p


def _die(msg: str, code: int) -> None:
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(code)
```

Then wire `pyproject.toml`. Add to `[project.scripts]`:

```toml
[project.scripts]
pdf-granite = "pdf_granite.convert:main"
pdf-textract = "pdf_granite.textract:main"
```

Add a new optional dependency group (place after the existing `[dependency-groups]` block, alongside `dev`):

```toml
[dependency-groups]
dev = [
    "pytest>=8.3.0",
]
textract = [
    # High-level Amazon Textract wrapper; pulls in boto3. Optional: only needed
    # to actually run pdf-textract, not to import the module or run unit tests.
    "amazon-textract-textractor>=1.8.0",
    # Loads AWS creds from the project .env into the environment for boto3.
    "python-dotenv>=1.0.0",
]
```

Then secure the secrets — append to `.gitignore` (the `.env` holds live AWS keys and must never be committed):

```gitignore
# Local secrets (AWS credentials etc.)
.env
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --no-sync pytest tests/test_textract.py -q`
Expected: PASS (2 passed). `main` is referenced by the script entry but not yet defined — that's fine; the entry point is only resolved at `pdf-textract` invocation, added in Task 5.

- [ ] **Step 5: Commit**

```bash
git add src/pdf_granite/textract.py tests/test_textract.py pyproject.toml .gitignore
git commit -m "feat(textract): scaffold pdf-textract module, parser, packaging; gitignore .env"
```

---

### Task 2: Source resolution (local + s3://)

**Files:**
- Modify: `src/pdf_granite/textract.py`
- Test: `tests/test_textract.py`

**Interfaces:**
- Consumes: `_die` from Task 1.
- Produces:
  - `is_s3_uri(s: str) -> bool` — True iff `s` starts with `s3://`.
  - `stem_for(source: str) -> str` — filename without `.pdf` suffix, for both local paths and s3 URIs (e.g. `s3://b/dir/My File.pdf` -> `My File`).
  - `resolve_sources(paths: list[str], input_dir: Path) -> list[str]` — returns a list of source strings. Each is either an absolute local path (str) or an `s3://...pdf` URI. Validation: explicit local paths must be existing `.pdf` files (else `_die(..., 2)`); explicit `s3://` URIs must end in `.pdf` (else `_die(..., 2)`); with no paths, glob `input_dir` for `*.pdf` (sorted), `_die(..., 2)` if the dir is missing or empty.

- [ ] **Step 1: Write the failing test**

```python
def test_is_s3_uri():
    assert textract.is_s3_uri("s3://b/x.pdf") is True
    assert textract.is_s3_uri("input/x.pdf") is False


def test_stem_for_local_and_s3():
    assert textract.stem_for("s3://input1972/SMR-1Q26-Presentation.pdf") == "SMR-1Q26-Presentation"
    assert textract.stem_for("/tmp/dir/My File.pdf") == "My File"


def test_resolve_sources_globs_dir(tmp_path):
    (tmp_path / "b.pdf").write_bytes(b"%PDF-1.4")
    (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4")
    (tmp_path / "note.txt").write_text("x")
    out = textract.resolve_sources([], tmp_path)
    assert [textract.stem_for(s) for s in out] == ["a", "b"]  # sorted, txt excluded


def test_resolve_sources_empty_dir_exits(tmp_path):
    with pytest.raises(SystemExit) as e:
        textract.resolve_sources([], tmp_path)
    assert e.value.code == 2


def test_resolve_sources_local_nonpdf_exits(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x")
    with pytest.raises(SystemExit) as e:
        textract.resolve_sources([str(f)], tmp_path)
    assert e.value.code == 2


def test_resolve_sources_s3_uri_kept(tmp_path):
    out = textract.resolve_sources(["s3://input1972/SMR-1Q26-Presentation.pdf"], tmp_path)
    assert out == ["s3://input1972/SMR-1Q26-Presentation.pdf"]


def test_resolve_sources_s3_nonpdf_exits(tmp_path):
    with pytest.raises(SystemExit) as e:
        textract.resolve_sources(["s3://b/notapdf.txt"], tmp_path)
    assert e.value.code == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/test_textract.py -q`
Expected: FAIL — `AttributeError: module 'pdf_granite.textract' has no attribute 'is_s3_uri'`.

- [ ] **Step 3: Write minimal implementation**

Add `from pathlib import Path` to the imports, and append:

```python
def is_s3_uri(s: str) -> bool:
    return s.startswith("s3://")


def stem_for(source: str) -> str:
    # Works for both local paths and s3:// URIs; both use forward slashes in s3,
    # and Path handles OS separators for local paths.
    name = source.rsplit("/", 1)[-1] if is_s3_uri(source) else Path(source).name
    return name[:-4] if name.lower().endswith(".pdf") else name


def resolve_sources(paths: list[str], input_dir: Path) -> list[str]:
    if paths:
        resolved: list[str] = []
        for raw in paths:
            if is_s3_uri(raw):
                if not raw.lower().endswith(".pdf"):
                    _die(f"not a .pdf s3 source: {raw}", 2)
                resolved.append(raw)
            else:
                p = Path(raw)
                if not p.is_file() or p.suffix.lower() != ".pdf":
                    _die(f"not an existing .pdf file: {raw}", 2)
                resolved.append(str(p))
        return resolved
    if not input_dir.is_dir():
        _die(f"input directory not found: {input_dir}", 2)
    pdfs = sorted(input_dir.glob("*.pdf"))
    if not pdfs:
        _die(f"no *.pdf files in {input_dir}", 2)
    return [str(p) for p in pdfs]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --no-sync pytest tests/test_textract.py -q`
Expected: PASS (all source-resolution tests green).

- [ ] **Step 5: Commit**

```bash
git add src/pdf_granite/textract.py tests/test_textract.py
git commit -m "feat(textract): resolve local + s3:// PDF sources"
```

---

### Task 3: Region detection

**Files:**
- Modify: `src/pdf_granite/textract.py`
- Test: `tests/test_textract.py`

**Interfaces:**
- Consumes: `is_s3_uri` from Task 2.
- Produces:
  - `bucket_of(s3_uri: str) -> str` — bucket name from an `s3://bucket/key` URI.
  - `detect_region(bucket: str, region_arg: str | None) -> str` — if `region_arg` is set, return it; else call S3 `GetBucketLocation` for `bucket`; map a `None`/empty `LocationConstraint` to `"us-east-1"`. boto3 imported lazily inside the function.

- [ ] **Step 1: Write the failing test**

```python
def test_bucket_of():
    assert textract.bucket_of("s3://input1972/dir/file.pdf") == "input1972"


def test_detect_region_explicit_wins(monkeypatch):
    # explicit region short-circuits; boto3 must not be called
    def boom(*a, **k):
        raise AssertionError("boto3 should not be called")
    monkeypatch.setattr(textract, "_s3_client", boom)
    assert textract.detect_region("anybucket", "eu-west-1") == "eu-west-1"


def test_detect_region_from_bucket(monkeypatch):
    class FakeS3:
        def get_bucket_location(self, Bucket):
            assert Bucket == "input1972"
            return {"LocationConstraint": "us-west-2"}
    monkeypatch.setattr(textract, "_s3_client", lambda region=None: FakeS3())
    assert textract.detect_region("input1972", None) == "us-west-2"


def test_detect_region_us_east_1_null_constraint(monkeypatch):
    class FakeS3:
        def get_bucket_location(self, Bucket):
            return {"LocationConstraint": None}  # us-east-1 quirk
    monkeypatch.setattr(textract, "_s3_client", lambda region=None: FakeS3())
    assert textract.detect_region("b", None) == "us-east-1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/test_textract.py -q`
Expected: FAIL — `AttributeError: module 'pdf_granite.textract' has no attribute 'bucket_of'`.

- [ ] **Step 3: Write minimal implementation**

```python
def bucket_of(s3_uri: str) -> str:
    # s3://bucket/key... -> bucket
    return s3_uri[len("s3://"):].split("/", 1)[0]


def _s3_client(region: str | None = None):
    import boto3

    return boto3.client("s3", region_name=region) if region else boto3.client("s3")


def detect_region(bucket: str, region_arg: str | None) -> str:
    if region_arg:
        return region_arg
    loc = _s3_client().get_bucket_location(Bucket=bucket).get("LocationConstraint")
    return loc or "us-east-1"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --no-sync pytest tests/test_textract.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pdf_granite/textract.py tests/test_textract.py
git commit -m "feat(textract): auto-detect AWS region from bucket"
```

---

### Task 4: Analysis + output writing

**Files:**
- Modify: `src/pdf_granite/textract.py`
- Test: `tests/test_textract.py`

**Interfaces:**
- Consumes: `is_s3_uri`, `stem_for`, `bucket_of`, `detect_region`, `_die`.
- Produces:
  - `build_markdown(document) -> str` — `document.to_markdown(MarkdownLinearizationConfig())`, imported lazily.
  - `write_outputs(document, out_dir: Path, stem: str) -> list[Path]` — writes `<out_dir>/<stem>.md` (from `build_markdown`) and `<out_dir>/<stem>.json` (pretty `document.response`); creates `out_dir`; returns the two paths.
  - `analyze(source: str, *, bucket: str | None, s3_prefix: str, region: str | None) -> document` — builds a `Textractor(region_name=...)` and calls `start_document_analysis` with `features=[LAYOUT, TABLES]`. For `s3://` sources: pass `file_source=source` directly (region auto-detected from the source's bucket if `region` is None; no upload). For local sources: require `bucket` (`_die(..., 2)` if missing), pass `file_source=source` and `s3_upload_path=f"s3://{bucket}/{s3_prefix}"` (region auto-detected from `bucket`). Textractor and its data constants imported lazily.

- [ ] **Step 1: Write the failing test**

```python
class _FakeDoc:
    def __init__(self):
        self.response = {"DocumentMetadata": {"Pages": 3}, "Blocks": []}
    def to_markdown(self, config=None):
        return "# Title\n\nbody\n"


def test_build_markdown(monkeypatch):
    # build_markdown must not require the real textractor config import path to exist
    monkeypatch.setattr(textract, "_markdown_config", lambda: None)
    assert textract.build_markdown(_FakeDoc()) == "# Title\n\nbody\n"


def test_write_outputs(tmp_path):
    out = tmp_path / "textract"
    paths = textract.write_outputs(_FakeDoc(), out, "doc")
    md = out / "doc.md"
    js = out / "doc.json"
    assert set(paths) == {md, js}
    assert md.read_text(encoding="utf-8") == "# Title\n\nbody\n"
    assert json.loads(js.read_text(encoding="utf-8"))["DocumentMetadata"]["Pages"] == 3


def test_analyze_local_requires_bucket(monkeypatch):
    with pytest.raises(SystemExit) as e:
        textract.analyze("/tmp/doc.pdf", bucket=None, s3_prefix="p/", region="us-east-1")
    assert e.value.code == 2


def test_analyze_s3_source_no_upload(monkeypatch):
    calls = {}
    class FakeExtractor:
        def start_document_analysis(self, **kw):
            calls.update(kw)
            return _FakeDoc()
    monkeypatch.setattr(textract, "_build_extractor", lambda region: FakeExtractor())
    monkeypatch.setattr(textract, "detect_region", lambda bucket, region: "us-west-2")
    monkeypatch.setattr(textract, "_features", lambda: ["LAYOUT", "TABLES"])
    doc = textract.analyze(
        "s3://input1972/SMR-1Q26-Presentation.pdf", bucket=None, s3_prefix="p/", region=None
    )
    assert isinstance(doc, _FakeDoc)
    assert calls["file_source"] == "s3://input1972/SMR-1Q26-Presentation.pdf"
    assert "s3_upload_path" not in calls or calls["s3_upload_path"] is None


def test_analyze_local_source_uploads(monkeypatch):
    calls = {}
    class FakeExtractor:
        def start_document_analysis(self, **kw):
            calls.update(kw)
            return _FakeDoc()
    monkeypatch.setattr(textract, "_build_extractor", lambda region: FakeExtractor())
    monkeypatch.setattr(textract, "detect_region", lambda bucket, region: "us-east-1")
    monkeypatch.setattr(textract, "_features", lambda: ["LAYOUT", "TABLES"])
    textract.analyze("/tmp/doc.pdf", bucket="mybucket", s3_prefix="scratch/", region=None)
    assert calls["file_source"] == "/tmp/doc.pdf"
    assert calls["s3_upload_path"] == "s3://mybucket/scratch/"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/test_textract.py -q`
Expected: FAIL — missing `build_markdown` / `write_outputs` / `analyze` / helper attributes.

- [ ] **Step 3: Write minimal implementation**

Add `import json` to the imports, and append. The small lazy helpers (`_markdown_config`, `_features`, `_build_extractor`) are separate functions so tests can monkeypatch them without importing textractor:

```python
def _markdown_config():
    from textractor.data.markdown_linearization_config import MarkdownLinearizationConfig

    return MarkdownLinearizationConfig(table_linearization_format="markdown")


def _features():
    from textractor.data.constants import TextractFeatures

    return [TextractFeatures.LAYOUT, TextractFeatures.TABLES]


def _build_extractor(region: str):
    from textractor import Textractor

    return Textractor(region_name=region)


def build_markdown(document) -> str:
    return document.to_markdown(_markdown_config())


def write_outputs(document, out_dir: Path, stem: str) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / f"{stem}.md"
    json_path = out_dir / f"{stem}.json"
    md_path.write_text(build_markdown(document), encoding="utf-8")
    json_path.write_text(json.dumps(document.response, indent=2), encoding="utf-8")
    return [md_path, json_path]


def analyze(source: str, *, bucket: str | None, s3_prefix: str, region: str | None):
    if is_s3_uri(source):
        resolved_region = detect_region(bucket_of(source), region)
        extractor = _build_extractor(resolved_region)
        return extractor.start_document_analysis(file_source=source, features=_features())
    # local source -> must upload to a scratch bucket
    if not bucket:
        _die(f"--bucket is required to upload local source: {source}", 2)
    resolved_region = detect_region(bucket, region)
    extractor = _build_extractor(resolved_region)
    upload = f"s3://{bucket}/{s3_prefix}"
    return extractor.start_document_analysis(
        file_source=source, features=_features(), s3_upload_path=upload
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --no-sync pytest tests/test_textract.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pdf_granite/textract.py tests/test_textract.py
git commit -m "feat(textract): run analysis and write markdown + raw json"
```

---

### Task 5: main() orchestration + batch

**Files:**
- Modify: `src/pdf_granite/textract.py`
- Test: `tests/test_textract.py`

**Interfaces:**
- Consumes: `build_parser`, `resolve_sources`, `stem_for`, `analyze`, `write_outputs`.
- Produces:
  - `load_env() -> None` — lazy wrapper over `dotenv.load_dotenv()`; loads `.env` into `os.environ` (monkeypatchable in tests).
  - `main(argv: list[str] | None = None) -> int` — calls `load_env()`, resolves the bucket as `args.bucket or os.environ.get("S3_BUCKET")`, resolves sources, then for each source `analyze` + `write_outputs` under `<output-dir>/textract/`, continue-on-error, prints `Done: N converted, M failed`, returns `0` if no failures else `1`. Module ends with `if __name__ == "__main__": raise SystemExit(main())`.

- [ ] **Step 1: Write the failing test**

```python
def test_main_runs_with_fakes(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(textract, "load_env", lambda: None)
    monkeypatch.setattr(
        textract, "resolve_sources",
        lambda paths, input_dir: ["s3://input1972/SMR-1Q26-Presentation.pdf"],
    )
    monkeypatch.setattr(
        textract, "analyze",
        lambda source, **kw: _FakeDoc(),
    )
    code = textract.main(["--output-dir", str(tmp_path / "out")])
    assert code == 0
    base = tmp_path / "out" / "textract"
    assert (base / "SMR-1Q26-Presentation.md").read_text(encoding="utf-8") == "# Title\n\nbody\n"
    assert (base / "SMR-1Q26-Presentation.json").is_file()


def test_main_returns_1_when_all_fail(tmp_path, monkeypatch):
    monkeypatch.setattr(textract, "load_env", lambda: None)
    monkeypatch.setattr(textract, "resolve_sources", lambda paths, input_dir: ["s3://b/x.pdf"])
    def boom(*a, **k):
        raise RuntimeError("nope")
    monkeypatch.setattr(textract, "analyze", boom)
    code = textract.main(["--output-dir", str(tmp_path / "out")])
    assert code == 1


def test_main_defaults_bucket_from_s3_bucket_env(tmp_path, monkeypatch):
    monkeypatch.setattr(textract, "load_env", lambda: None)
    monkeypatch.setenv("S3_BUCKET", "envbucket")
    monkeypatch.setattr(textract, "resolve_sources", lambda paths, input_dir: ["/tmp/doc.pdf"])
    seen = {}
    def capture(source, **kw):
        seen.update(kw)
        return _FakeDoc()
    monkeypatch.setattr(textract, "analyze", capture)
    code = textract.main(["--output-dir", str(tmp_path / "out")])
    assert code == 0
    assert seen["bucket"] == "envbucket"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/test_textract.py -q`
Expected: FAIL — `AttributeError: module 'pdf_granite.textract' has no attribute 'main'`.

- [ ] **Step 3: Write minimal implementation**

```python
import os    # add to the top-of-file imports
import time  # add to the top-of-file imports


def load_env() -> None:
    from dotenv import load_dotenv

    load_dotenv()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    log = (lambda *a: None) if args.quiet else (lambda *a: print(*a))

    load_env()
    bucket = args.bucket or os.environ.get("S3_BUCKET")

    sources = resolve_sources(args.paths, Path(args.input_dir))
    out_dir = Path(args.output_dir) / "textract"

    done, failed = 0, 0
    for source in sources:
        stem = stem_for(source)
        log(f"Textract: parsing {source} ...")
        start = time.time()
        try:
            document = analyze(
                source, bucket=bucket, s3_prefix=args.s3_prefix, region=args.region
            )
            outputs = write_outputs(document, out_dir, stem)
        except Exception as exc:  # continue-on-error across the batch
            failed += 1
            print(f"  FAILED {source}: {exc}", file=sys.stderr)
            continue
        done += 1
        pages = len(document.response.get("DocumentMetadata", {}).get("Pages", "") and
                    document.response.get("Blocks", [])) if False else None  # see note below
        names = ", ".join(p.name for p in outputs)
        log(f"  {stem}: {time.time() - start:.1f}s, wrote {names}")

    print(f"Done: {done} converted, {failed} failed.")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

Note: drop the throwaway `pages = ...` line — it is shown only to flag that page
count is optional. Use this clean version of the success branch instead:

```python
        done += 1
        names = ", ".join(p.name for p in outputs)
        log(f"  {stem}: {time.time() - start:.1f}s, wrote {names}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --no-sync pytest tests/test_textract.py -q`
Expected: PASS (full file green).

- [ ] **Step 5: Run the full suite and commit**

```bash
uv run --no-sync pytest -q
git add src/pdf_granite/textract.py tests/test_textract.py
git commit -m "feat(textract): batch main with continue-on-error"
```

---

### Task 6: README docs + live run against the real PDF

**Files:**
- Modify: `README.md`
- (Produces, not committed by this task's code) `output/textract/SMR-1Q26-Presentation.md` and `.json`

**Interfaces:**
- Consumes: the finished `pdf-textract` CLI.
- Produces: documentation + the real comparison output.

- [ ] **Step 1: Add a README section**

Append after the existing "Run" section:

````markdown
## Amazon Textract (comparison)

A separate `pdf-textract` script parses PDFs with **Amazon Textract**
(LAYOUT + TABLES) for side-by-side comparison. It writes
`output/textract/<name>.md` plus the raw Textract JSON. It is **not** part of
the Docling pipeline.

Put your AWS credentials in a `.env` file at the project root (gitignored):

```dotenv
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-east-1
S3_BUCKET=input1972
```

Install the optional AWS dependency group and run it. Sources may be local
files or `s3://` URIs (multi-page PDFs are processed via Textract's async API,
which needs the document in S3 — local files are uploaded to the `S3_BUCKET`
scratch bucket, overridable with `--bucket`):

```bash
uv sync --group textract

# PDF already in S3 (region auto-detected from the bucket):
uv run --no-sync pdf-textract s3://input1972/SMR-1Q26-Presentation.pdf

# Local file (uploaded to the S3_BUCKET scratch bucket from .env first):
uv run --no-sync pdf-textract input/SMR-1Q26-Presentation.pdf
```
````

- [ ] **Step 2: Commit the docs**

```bash
git add README.md
git commit -m "docs: document pdf-textract comparison parser"
```

- [ ] **Step 3: Live run (manual verification — requires AWS creds)**

Run:

```bash
uv sync --group textract
uv run --no-sync pdf-textract s3://input1972/SMR-1Q26-Presentation.pdf
```

Expected: exit 0; prints `Done: 1 converted, 0 failed`; creates
`output/textract/SMR-1Q26-Presentation.md` (non-empty markdown with headings
and at least one markdown table) and `output/textract/SMR-1Q26-Presentation.json`
(raw Textract blocks). Eyeball the markdown against
`output/markitdown/smr.md` and `output/liteparse/liteparse_smr.md`.

- [ ] **Step 4: Commit the comparison output**

```bash
git add output/textract/SMR-1Q26-Presentation.md output/textract/SMR-1Q26-Presentation.json
git commit -m "chore: add Amazon Textract comparison output"
```

---

## Self-Review Notes

- **Spec coverage:** standalone module + `pdf-textract` script (Task 1), optional `textract` dep group (Task 1), local + `s3://` resolution (Task 2), region auto-detect + same-region requirement (Task 3), async LAYOUT+TABLES analysis with upload-vs-direct routing (Task 4), markdown + raw JSON outputs to `output/textract/` (Task 4), batch continue-on-error + summary (Task 5), README + live run + committed output (Task 6). All spec sections map to a task.
- **Lazy-import constraint:** textractor/boto3/dotenv imports are confined to `_markdown_config`, `_features`, `_build_extractor`, `_s3_client`, `load_env` — all monkeypatched in tests, so `pytest` runs without the `textract` group installed.
- **Secrets/.env:** `.env` (live AWS keys) is gitignored in Task 1; `main()` loads it via `load_env()` and defaults `--bucket` from `S3_BUCKET` (Task 5).
- **Type consistency:** `analyze(source, *, bucket, s3_prefix, region)`, `write_outputs(document, out_dir, stem)`, `detect_region(bucket, region_arg)`, `stem_for(source)`, `resolve_sources(paths, input_dir)` names/signatures are identical across the tasks that define and call them.
