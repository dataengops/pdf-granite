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
