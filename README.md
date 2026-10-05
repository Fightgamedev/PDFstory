# PDF Story Studio

PDF Story Studio is a Linux desktop prototype that turns a text-based PDF into an editable visual-novel outline, a short screenplay, and a playable Ren'Py project. It offers a no-key local mode and an optional OpenAI mode.

## Features

- Extract selectable text from PDFs locally, preserving page numbers.
- Generate a short outline and screenplay with either local templates or the OpenAI Responses API.
- Create original illustrated scene backgrounds locally from shapes, scenery, colors, and story cues. These are programmatically composed images, not AI-generated illustrations.
- Export an editable Ren'Py project, preview it, or download it as a ZIP.
- Use the built-in debug console to copy progress and errors without exposing PDF text or API keys.

Local story generation works offline and does not send PDF text to a service. Its writing uses recurring-word counts, selected excerpts, and reusable dialogue templates, so results are intentionally simple. OpenAI mode sends extracted text and page-aware notes to OpenAI (`store: false`). The key is entered in the browser or provided through the environment; it is not written to generated projects.

Scanned-PDF OCR, AI-generated illustrations, branching stories, and character portrait generation are not implemented. The app supports Linux x86_64; other desktop platforms have not been prepared.

## Requirements

- Linux x86_64
- Python 3.9 or newer
- Poppler's `pdftotext` command (Ubuntu/Debian package: `poppler-utils`)
- Internet access for OpenAI requests, if selected, and for the first Ren'Py preview unless the Ren'Py SDK is already installed

Pillow is installed from `requirements.txt` and is used to draw scene illustrations.

## Install and run

On Ubuntu or Debian, install Poppler if needed:

```sh
sudo apt-get update
sudo apt-get install poppler-utils python3-venv
```

Create a virtual environment and install the Python dependency:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Start the app:

```sh
python app.py
```

It binds only to `127.0.0.1:8765` and opens the browser. If the browser does not open, visit <http://127.0.0.1:8765/>. To stop the app, press **Ctrl+C** in the terminal running it.

## Create a story

1. Select a text-based PDF and click **Read PDF**.
2. Choose **Do it locally** for offline generation without a key, or **Original project** to use OpenAI. Choose an adaptation mode and scene count.
3. Click **Build editable outline**, review or edit the JSON, then click **Write screenplay**.
4. Click **Play preview** or download the Ren'Py project ZIP.

OpenAI mode needs an API key. Enter it in the app or set `OPENAI_API_KEY` before starting the server. `OPENAI_MODEL` can select a model available to your account; otherwise the app's default model is used. Never commit a real key to GitHub.

The app processes PDFs up to 80 MB. Text is extracted locally; pages without selectable text may be scans and are not OCR-processed. Generated projects do not contain the source PDF.

## Local files and privacy

Uploads, extracted page text, outlines, screenplays, Ren'Py exports, and preview logs are stored under `.studio-data/` next to the app. That folder and PDF/ZIP files are ignored by Git. The debug console records progress and errors but does not record API keys or PDF contents. The local server is intended for use on your own computer; do not expose port 8765 to a network.

## Project layout

- `app.py` — local web server, upload handling, background jobs, and preview launch
- `studio/pdf_source.py` — page-preserving PDF text extraction
- `studio/local_pipeline.py` — offline outline and template screenplay generation
- `studio/pipeline.py` and `studio/openai_api.py` — optional OpenAI text generation
- `studio/renpy_export.py` — illustrated scene generation and Ren'Py project export
- `web/` — browser interface, including the generation tabs and debug console
- `BUILD_PLAN.txt` — project plan and future development phases

The Ren'Py preview SDK is downloaded on first use if no local SDK is available. The app verifies the archive's SHA-256 checksum before extracting it.

## License

This project is released under the [MIT License](LICENSE).

## Status

This is an experimental prototype. The local PDF-to-outline-to-screenplay-to-export workflow has been exercised with a short digital PDF. OpenAI mode and the Ren'Py preview path may need additional environment-specific setup.

OpenAI API reference: [Responses API](https://developers.openai.com/api/docs/guides/text).
