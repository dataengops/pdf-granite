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
import json
import sys
from pathlib import Path


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
        "Not needed when all sources are s3:// URIs. Defaults to the S3_BUCKET env var.",
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


def is_s3_uri(s: str) -> bool:
    return s.startswith("s3://")


def stem_for(source: str) -> str:
    # Works for both local paths and s3:// URIs; s3 uses forward slashes,
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
