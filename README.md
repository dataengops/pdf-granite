# pdf-granite

Standalone CLI that converts PDFs to **Markdown and/or HTML** using
[Docling](https://github.com/docling-project/docling), with Granite Vision chart
extraction, image extraction, and optional OCR. **CUDA by default.**

## Setup

Requires Python 3.13 and [uv](https://docs.astral.sh/uv/).

```bash
cd c:/ai/code/pdf_granit
uv sync                 # installs docling + a CPU torch and all other deps
```

### CPU setup

`uv sync` already installs a CPU-only `torch`, so no extra steps are needed. Just
run with `--device cpu` (about 10x slower than CUDA):

```bash
uv run --no-sync pdf-granite --device cpu
```

`--no-sync` is optional on a clean CPU install, but using it consistently avoids
surprises if you later add a CUDA build (see below).

### GPU / CUDA setup

The base install is CPU-only. For ~10x faster conversion, install a CUDA `torch`
build matching your driver over the synced venv (`nvidia-smi` shows your CUDA
version; Blackwell / RTX 50-series needs CUDA 12.8+):

```bash
# cu130 shown; cu129 / cu128 also valid depending on driver
uv pip install --force-reinstall \
  --index-url https://download.pytorch.org/whl/cu130 torch==2.12.1 torchvision==0.27.1
```

Verify the GPU is visible:

```bash
uv run --no-sync python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

**Always run with `--no-sync`** afterwards — a plain `uv run` / `uv sync` restores
the venv from the lockfile and silently reverts torch to the CPU build.

## Run

```bash
# All *.pdf in ./input -> Markdown in ./output (GPU)
uv run --no-sync pdf-granite

# One file, both formats
uv run --no-sync pdf-granite "input/My File.pdf" --format both

# No GPU? (about 10x slower)
uv run --no-sync pdf-granite --device cpu

# Scanned / image-based PDFs? Enable OCR (off by default)
uv run --no-sync pdf-granite --ocr
```

With the default `--device cuda`, the tool hard-fails if no GPU is visible and
prints how to install a CUDA torch build.

OCR is **off by default** — born-text PDFs already carry an extractable text layer,
so OCR adds time without improving output. Add `--ocr` only for scanned or
image-based PDFs where the text is baked into pixels.

## Options

| Flag | Default | Meaning |
|---|---|---|
| `paths` | all `*.pdf` in `--input-dir` | Specific PDFs to convert |
| `--input-dir` | `input` | Folder scanned when no paths given |
| `--output-dir` | `output` | Output folder |
| `--format md\|html\|both` | `md` | Output format(s) |
| `--device cuda\|cpu\|auto` | `cuda` | `cuda` hard-fails without a GPU |
| `--no-charts` | off | Disable chart extraction (faster) |
| `--ocr` | off | Enable OCR for scanned/image-based PDFs (off by default) |
| `--embed-images` | off | Inline images as base64 instead of linking external files |
| `--quiet` | off | Only print the final summary |

Outputs per `<name>.pdf`: `<name>.md` and/or `<name>.html`, plus `<name>_charts.csv`
when charts are detected.

By default images are written as separate PNGs into a `<name>_artifacts/` folder
next to the output and linked from it — keep that folder alongside the `.md`/`.html`
when moving or sharing. Pass `--embed-images` to inline them as base64 for a single
self-contained file instead.

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
S3_BUCKET=input
```

Install the optional AWS dependency group and run it. Sources may be local
files or `s3://` URIs (multi-page PDFs are processed via Textract's async API,
which needs the document in S3 — local files are uploaded to the `S3_BUCKET`
scratch bucket, overridable with `--bucket`):

```bash
uv sync --group textract

# PDF already in S3 (region auto-detected from the bucket):
uv run --no-sync pdf-textract s3://input/SMR-1Q26-Presentation.pdf

# Local file (uploaded to the S3_BUCKET scratch bucket from .env first):
uv run --no-sync pdf-textract input/SMR-1Q26-Presentation.pdf
```

## Tests

```bash
uv run --no-sync pytest -q
```

Offline unit tests run anywhere; the live smoke test converts the first PDF in
`input/` and is skipped when no CUDA GPU is present.
