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
