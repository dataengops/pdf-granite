# Textract comparison parser — design

**Date:** 2026-06-28
**Status:** Approved

## Goal

Add a standalone script that parses the project's input PDF(s) with **Amazon
Textract** and writes Markdown to `output/textract/<name>.md`, parallel to the
existing comparison outputs (MarkItDown, liteparse, MinerU). The raw Textract
response is saved alongside as `output/textract/<name>.json`.

This is a comparison/evaluation tool. It is **not** wired into the `pdf-granite`
(Docling) CLI — it is a separate entry point sharing the same input/output
conventions.

## Context

- The PDF is multi-page (`input/SMR-1Q26-Presentation.pdf`). Multi-page PDFs
  require Textract's **asynchronous** API (`StartDocumentAnalysis` /
  `GetDocumentAnalysis`), which requires the document to live in S3. The
  synchronous API only accepts single-page input.
- AWS credentials are already configured via the standard chain (env vars or
  `~/.aws`). The user provides an **existing** S3 bucket for scratch uploads.

## Placement & dependencies

- New module: `src/pdf_granite/textract.py`.
- New console script `pdf-textract` in `pyproject.toml`
  (`[project.scripts]`), mirroring how `pdf-granite` is exposed. Runnable via
  `uv run pdf-textract ...`.
- New optional dependency group `textract` in `pyproject.toml`
  (`[dependency-groups]` or `[project.optional-dependencies]`), containing
  `amazon-textract-textractor` (which pulls in `boto3`). Kept out of the core
  install so the AWS stack is not forced on the Docling-only path.

## Flow

1. **Resolve inputs** — sources may be **local PDF paths** or **`s3://` URIs**.
   Positional args, else all `*.pdf` in `--input-dir` (default `input`). Local
   paths must be an existing `.pdf` (same validation as `convert.py`); `s3://`
   URIs must end in `.pdf` and are not stat-checked locally. The known input
   for this project already lives at `s3://input1972/SMR-1Q26-Presentation.pdf`.
2. **Per PDF — run Textract** via Textractor's async
   `start_document_analysis`:
   - features: `LAYOUT` + `TABLES`
   - **Local source:** `s3_upload_path` set to `--bucket` + `--s3-prefix`;
     Textractor uploads the PDF, starts the async job, polls to completion, and
     returns a `Document`.
   - **`s3://` source:** point Textract directly at the existing object — no
     upload. (`--bucket` is then optional / unused.)
3. **Save raw JSON** — write the underlying Textract API response to
   `output/textract/<stem>.json` (pretty-printed). This is the raw block data,
   useful for debugging the comparison.
4. **Build markdown** — linearize the `Document` to markdown using Textractor's
   markdown linearization (reading order, headings, paragraphs, tables rendered
   as markdown tables). The exact API (`Document.to_markdown()` vs
   `get_text(config=TextLinearizationConfig(...))`) is verified against current
   Textractor docs during implementation; it does not change this design.
5. **Write markdown** — `output/textract/<stem>.md`.
6. **Summary** — per-file line (pages, elapsed) and a final
   `Done: N converted, M failed`, matching `convert.py`'s batch +
   continue-on-error style.

## Configuration (CLI args)

| Arg | Required | Default | Purpose |
|-----|----------|---------|---------|
| `paths` (positional) | no | — | PDF files; if omitted, scan `--input-dir`. |
| `--bucket` | for local sources | — | Existing S3 bucket used as scratch for uploads. Not needed when all sources are `s3://` URIs. |
| `--region` | no | auto-detected from the bucket via `GetBucketLocation`; falls back to `us-east-1` | AWS region. Must match the bucket's region (Textract requirement). |
| `--s3-prefix` | no | `textract-scratch/` | Key prefix for uploaded local PDFs. |
| `--input-dir` | no | `input` | Folder scanned when no paths given. |
| `--output-dir` | no | `output` | Base output dir; files go to `<output-dir>/textract/`. |
| `--quiet` | no | off | Suppress per-step logging; keep final summary. |

Credentials come from the standard AWS chain (env vars / `~/.aws`), never from
flags.

## Error handling

- Per-file `try/except` that continues across the batch (same as `convert.py`).
- A clear `error: ...` message + non-zero exit for: a local source given with
  no `--bucket`, missing/invalid bucket, AWS auth failure, Textract job failure.
- Reuse the `_die(msg, code)` pattern from `convert.py` for fatal
  pre-flight errors (e.g. no input PDFs, local source without `--bucket`).
- **Region note:** auto-detection reads the region of the relevant bucket — the
  source object's bucket for `s3://` sources, or `--bucket` for local sources.

## Testing

Unit tests, no live AWS calls (Textract is mocked):

- **Input resolution** — positional paths and `--input-dir` glob, including the
  error cases (non-pdf path, empty dir). Can share/mirror `test_convert.py`.
- **Markdown + JSON writing** — given a fake `Document` (stub with the
  linearization method and raw-response attribute), assert that
  `<stem>.md` and `<stem>.json` are written to `<output-dir>/textract/` with the
  expected contents.
- **Argument parsing** — `--bucket` required only when a local source is given;
  `s3://` sources work without it; defaults for region/prefix.
- **Source classification** — local path vs `s3://` URI routing (upload vs
  direct), with the local-source-without-bucket error case.

## Out of scope

- Wiring Textract into the `pdf-granite` CLI.
- Bucket creation / lifecycle management (user supplies an existing bucket).
- FORMS / signatures / queries features (LAYOUT + TABLES only).
- HTML output (markdown only, to match the comparison set).
