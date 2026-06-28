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
