"""pdf-granite — CUDA-accelerated PDF -> Markdown/HTML converter (Docling).

Run from the project root so ./input and ./output resolve as expected:

    uv run --no-sync pdf-granite
    uv run --no-sync pdf-granite "input/My File.pdf" --format both

`--no-sync` is required: it stops `uv` from reverting the locally installed CUDA
torch build back to the CPU build (see README, "GPU / CUDA setup").
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pdf-granite",
        description="Convert PDFs to Markdown and/or HTML with Docling (CUDA by default).",
    )
    p.add_argument("paths", nargs="*", help="PDF files to convert (default: all *.pdf in --input-dir).")
    p.add_argument("--input-dir", default="input", help="Folder scanned when no paths are given.")
    p.add_argument("--output-dir", default="output", help="Where outputs are written.")
    p.add_argument("--format", choices=["md", "html", "both"], default="md", help="Output format(s).")
    p.add_argument(
        "--device",
        choices=["cuda", "cpu", "auto"],
        default="cuda",
        help="cuda = require GPU (hard-fail if absent); auto = Docling chooses; cpu = force CPU.",
    )
    p.add_argument("--no-charts", action="store_true", help="Disable Granite Vision chart extraction.")
    p.add_argument(
        "--ocr",
        action="store_true",
        help="Enable OCR for scanned/image-based PDFs. Off by default (born-text "
        "PDFs already have an extractable text layer).",
    )
    p.add_argument(
        "--embed-images",
        action="store_true",
        help="Inline images as base64 in the output. Default: write images to a "
        "sibling '<name>_artifacts' folder and link them.",
    )
    p.add_argument("--quiet", action="store_true", help="Suppress per-step logging; keep final summary.")
    return p


def _die(msg: str, code: int) -> None:
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(code)


def resolve_inputs(paths: list[str], input_dir: Path) -> list[Path]:
    if paths:
        resolved: list[Path] = []
        for raw in paths:
            p = Path(raw)
            if not p.is_file() or p.suffix.lower() != ".pdf":
                _die(f"not an existing .pdf file: {raw}", 2)
            resolved.append(p)
        return resolved
    if not input_dir.is_dir():
        _die(f"input directory not found: {input_dir}", 2)
    pdfs = sorted(input_dir.glob("*.pdf"))
    if not pdfs:
        _die(f"no *.pdf files in {input_dir}", 2)
    return pdfs


_CUDA_REMEDIATION = (
    "No CUDA GPU is visible to torch.\n"
    "Install a CUDA torch build matching your driver (see README), e.g.:\n"
    "  uv pip install --force-reinstall \\\n"
    "    --index-url https://download.pytorch.org/whl/cu130 torch==2.12.1 torchvision==0.27.1\n"
    "Then ALWAYS run this with `uv run --no-sync ...` so the CUDA build is not reverted.\n"
    "Or re-run with `--device cpu` (about 10x slower) / `--device auto`."
)


def cuda_available() -> bool:
    try:
        import torch
    except Exception:
        return False
    return bool(torch.cuda.is_available())


def cuda_device_name() -> str:
    import torch
    return torch.cuda.get_device_name(0)


def resolve_device(choice: str):
    from docling.datamodel.accelerator_options import AcceleratorDevice

    if choice == "cpu":
        return AcceleratorDevice.CPU
    if choice == "auto":
        return AcceleratorDevice.AUTO
    # choice == "cuda"
    if not cuda_available():
        _die(_CUDA_REMEDIATION, 1)
    return AcceleratorDevice.CUDA


def chart_from_item(item):
    meta = getattr(item, "meta", None)
    if meta is None:
        return None
    classification = getattr(meta, "classification", None)
    tabular = getattr(meta, "tabular_chart", None)
    if classification is None or tabular is None:
        return None
    chart_type = classification.get_main_prediction().class_name
    data = tabular.chart_data
    grid = [["" for _ in range(data.num_cols)] for _ in range(data.num_rows)]
    for cell in data.table_cells:
        grid[cell.start_row_offset_idx][cell.start_col_offset_idx] = cell.text
    return chart_type, grid


def write_charts_csv(charts, path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        for i, (chart_type, grid) in enumerate(charts, start=1):
            writer.writerow([f"# chart {i}: {chart_type}"])
            writer.writerows(grid)
            writer.writerow([])


def build_converter(device, *, do_charts: bool, do_ocr: bool):
    from docling.datamodel.accelerator_options import AcceleratorOptions
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    if do_charts:
        # Chart model JIT-compiles via torch.compile; abort-proof it on machines w/o a C++ compiler.
        os.environ.setdefault("TORCHDYNAMO_DISABLE", "1")

    opts = PdfPipelineOptions()
    opts.accelerator_options = AcceleratorOptions(device=device)
    opts.do_ocr = do_ocr
    opts.do_table_structure = True
    opts.do_chart_extraction = do_charts
    opts.generate_page_images = True
    opts.generate_picture_images = True
    return DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
    )


def convert_one(converter, pdf: Path, out_dir: Path, formats: set[str], *, embed_images: bool = False) -> dict:
    from docling_core.types.doc import ImageRefMode

    image_mode = ImageRefMode.EMBEDDED if embed_images else ImageRefMode.REFERENCED

    start = time.time()
    out_dir.mkdir(parents=True, exist_ok=True)
    result = converter.convert(str(pdf))
    doc = result.document
    stem = pdf.stem
    outputs: list[Path] = []

    if "md" in formats:
        md_path = out_dir / f"{stem}.md"
        doc.save_as_markdown(md_path, image_mode=image_mode)
        outputs.append(md_path)

    if "html" in formats:
        from docling_core.transforms.serializer.html import (
            HTMLDocSerializer,
            HTMLOutputStyle,
            HTMLParams,
        )
        from docling_core.transforms.visualizer.layout_visualizer import LayoutVisualizer

        html_path = out_dir / f"{stem}.html"
        ser = HTMLDocSerializer(
            doc=doc,
            params=HTMLParams(
                image_mode=image_mode,
                output_style=HTMLOutputStyle.SPLIT_PAGE,
            ),
        )
        viz = LayoutVisualizer()
        viz.params.show_label = False
        html_path.write_text(ser.serialize(visualizer=viz).text, encoding="utf-8")
        outputs.append(html_path)

    charts = [c for item, _ in doc.iterate_items() if (c := chart_from_item(item))]
    if charts:
        csv_path = out_dir / f"{stem}_charts.csv"
        write_charts_csv(charts, csv_path)
        outputs.append(csv_path)

    return {"pdf": pdf.name, "outputs": outputs, "charts": len(charts), "elapsed": time.time() - start}


def _formats_for(choice: str) -> set[str]:
    return {"md", "html"} if choice == "both" else {choice}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    log = (lambda *a: None) if args.quiet else (lambda *a: print(*a))

    pdfs = resolve_inputs(args.paths, Path(args.input_dir))
    device = resolve_device(args.device)
    if args.device == "cuda":
        log(f"Using CUDA: {cuda_device_name()}")
    elif args.device == "cpu":
        log("Using CPU (about 10x slower than CUDA).")
    else:
        log("Using device: auto (Docling chooses).")

    converter = build_converter(device, do_charts=not args.no_charts, do_ocr=args.ocr)
    formats = _formats_for(args.format)
    out_dir = Path(args.output_dir)

    done, failed = 0, 0
    for pdf in pdfs:
        log(f"Converting {pdf.name} ...")
        try:
            summary = convert_one(converter, pdf, out_dir, formats, embed_images=args.embed_images)
        except Exception as exc:  # continue-on-error across the batch
            failed += 1
            print(f"  FAILED {pdf.name}: {exc}", file=sys.stderr)
            continue
        done += 1
        names = ", ".join(p.name for p in summary["outputs"])
        log(f"  {pdf.name}: {summary['elapsed']:.1f}s, charts={summary['charts']}, wrote {names}")

    print(f"Done: {done} converted, {failed} failed.")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
