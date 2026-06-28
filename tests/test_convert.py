import csv as _csv
from pathlib import Path

import pytest

from pdf_granite import convert


def test_parser_defaults():
    ns = convert.build_parser().parse_args([])
    assert ns.paths == []
    assert ns.input_dir == "input"
    assert ns.output_dir == "output"
    assert ns.format == "md"
    assert ns.device == "cuda"
    assert ns.no_charts is False
    assert ns.no_ocr is False
    assert ns.quiet is False


def test_parser_overrides():
    ns = convert.build_parser().parse_args(
        ["a.pdf", "b.pdf", "--format", "both", "--device", "cpu", "--no-charts", "--quiet"]
    )
    assert ns.paths == ["a.pdf", "b.pdf"]
    assert ns.format == "both"
    assert ns.device == "cpu"
    assert ns.no_charts is True
    assert ns.quiet is True


def test_resolve_inputs_globs_dir(tmp_path):
    (tmp_path / "b.pdf").write_bytes(b"%PDF-1.4")
    (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4")
    (tmp_path / "note.txt").write_text("x")
    out = convert.resolve_inputs([], tmp_path)
    assert [p.name for p in out] == ["a.pdf", "b.pdf"]  # sorted, txt excluded


def test_resolve_inputs_empty_dir_exits(tmp_path):
    with pytest.raises(SystemExit) as e:
        convert.resolve_inputs([], tmp_path)
    assert e.value.code == 2


def test_resolve_inputs_explicit_nonpdf_exits(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x")
    with pytest.raises(SystemExit) as e:
        convert.resolve_inputs([str(f)], tmp_path)
    assert e.value.code == 2


def test_resolve_inputs_explicit_ok(tmp_path):
    f = tmp_path / "a.pdf"
    f.write_bytes(b"%PDF-1.4")
    out = convert.resolve_inputs([str(f)], tmp_path)
    assert out == [f]


def test_resolve_device_cuda_missing_exits(monkeypatch):
    monkeypatch.setattr(convert, "cuda_available", lambda: False)
    with pytest.raises(SystemExit) as e:
        convert.resolve_device("cuda")
    assert e.value.code == 1


def test_resolve_device_cuda_ok(monkeypatch):
    monkeypatch.setattr(convert, "cuda_available", lambda: True)
    dev = convert.resolve_device("cuda")
    from docling.datamodel.accelerator_options import AcceleratorDevice
    assert dev == AcceleratorDevice.CUDA


def test_resolve_device_cpu(monkeypatch):
    from docling.datamodel.accelerator_options import AcceleratorDevice
    assert convert.resolve_device("cpu") == AcceleratorDevice.CPU
    assert convert.resolve_device("auto") == AcceleratorDevice.AUTO


class _Pred:
    class_name = "bar chart"


class _Classif:
    def get_main_prediction(self):
        return _Pred()


class _Cell:
    def __init__(self, r, c, t):
        self.start_row_offset_idx, self.start_col_offset_idx, self.text = r, c, t


class _ChartData:
    num_rows, num_cols = 2, 2
    table_cells = [_Cell(0, 0, "Q1"), _Cell(0, 1, "10"), _Cell(1, 0, "Q2"), _Cell(1, 1, "20")]


class _Tabular:
    chart_data = _ChartData()


class _Meta:
    classification = _Classif()
    tabular_chart = _Tabular()


class _PicWithChart:
    meta = _Meta()


class _PicNoChart:
    meta = None


def test_chart_from_item_extracts_grid():
    out = convert.chart_from_item(_PicWithChart())
    assert out == ("bar chart", [["Q1", "10"], ["Q2", "20"]])


def test_chart_from_item_none_when_no_meta():
    assert convert.chart_from_item(_PicNoChart()) is None


def test_write_charts_csv(tmp_path):
    path = tmp_path / "out_charts.csv"
    convert.write_charts_csv([("bar chart", [["Q1", "10"], ["Q2", "20"]])], path)
    rows = list(_csv.reader(path.open(newline="")))
    assert rows[0] == ["# chart 1: bar chart"]
    assert ["Q1", "10"] in rows


def test_main_runs_with_fakes(tmp_path, monkeypatch, capsys):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    monkeypatch.setattr(convert, "resolve_device", lambda choice: "FAKE_DEVICE")
    monkeypatch.setattr(convert, "build_converter", lambda device, **kw: object())

    def fake_convert_one(converter, pdf_path, out_dir, formats):
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        target = Path(out_dir) / (Path(pdf_path).stem + ".md")
        target.write_text("# hi", encoding="utf-8")
        return {"pdf": Path(pdf_path).name, "outputs": [target], "charts": 0, "elapsed": 0.1}

    monkeypatch.setattr(convert, "convert_one", fake_convert_one)

    code = convert.main([str(pdf), "--output-dir", str(tmp_path / "out"), "--device", "cpu"])
    assert code == 0
    assert (tmp_path / "out" / "doc.md").read_text() == "# hi"


def test_main_returns_1_when_all_fail(tmp_path, monkeypatch):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(convert, "resolve_device", lambda choice: "FAKE_DEVICE")
    monkeypatch.setattr(convert, "build_converter", lambda device, **kw: object())

    def boom(*a, **k):
        raise RuntimeError("nope")

    monkeypatch.setattr(convert, "convert_one", boom)
    code = convert.main([str(pdf), "--output-dir", str(tmp_path / "out"), "--device", "cpu"])
    assert code == 1


def test_smoke_converts_sample(tmp_path):
    if not convert.cuda_available():
        pytest.skip("no CUDA GPU; smoke test requires GPU + Docling models")
    samples = sorted((Path(__file__).resolve().parents[1] / "input").glob("*.pdf"))
    if not samples:
        pytest.skip("no sample PDF present in input/")
    sample = samples[0]
    code = convert.main([str(sample), "--output-dir", str(tmp_path), "--format", "md"])
    assert code == 0
    md = tmp_path / f"{sample.stem}.md"
    assert md.is_file() and md.stat().st_size > 0
