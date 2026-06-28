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


class _FakeDoc:
    def __init__(self):
        self.response = {"DocumentMetadata": {"Pages": 3}, "Blocks": []}

    def to_markdown(self, config=None):
        return "# Title\n\nbody\n"


def test_build_markdown(monkeypatch):
    # build_markdown must not require the real textractor config import path to exist
    monkeypatch.setattr(textract, "_markdown_config", lambda: None)
    assert textract.build_markdown(_FakeDoc()) == "# Title\n\nbody\n"


def test_write_outputs(tmp_path, monkeypatch):
    monkeypatch.setattr(textract, "_markdown_config", lambda: None)
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


def test_main_runs_with_fakes(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(textract, "load_env", lambda: None)
    monkeypatch.setattr(textract, "_markdown_config", lambda: None)
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
    monkeypatch.setattr(textract, "_markdown_config", lambda: None)
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
