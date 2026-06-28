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
