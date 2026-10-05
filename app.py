from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import threading
import urllib.error
import urllib.request
import uuid
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, quote, urlparse

from studio.openai_api import ModelError
from studio.pdf_source import PdfError, extract_pages
from studio.pipeline import build_outline, build_screenplay
from studio.local_pipeline import build_local_outline, build_local_screenplay
from studio.renpy_export import export_game


ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "web"
DATA_ROOT = ROOT / ".studio-data"
BOOK_ROOT = DATA_ROOT / "books"
MAX_PDF_BYTES = 80 * 1024 * 1024
MAX_JSON_BYTES = 12 * 1024 * 1024
ENGINE_VERSION = "8.5.3"
ENGINE_NAME = f"renpy-{ENGINE_VERSION}-sdk"
ENGINE_ARCHIVE = f"{ENGINE_NAME}.tar.bz2"
ENGINE_URL = f"https://www.renpy.org/dl/{ENGINE_VERSION}/{ENGINE_ARCHIVE}"
ENGINE_SHA256 = "eb0a9be7f0fb13632fe25ceade9a8bed5a1b4d6b6e83bd19eeeb29e1a1bb4a45"
PORT = int(os.environ.get("PDF_STORY_PORT", "8765"))
APP_VERSION = "0.2-local-debug"

BOOKS: dict[str, dict] = {}
JOBS: dict[str, dict] = {}
LOCK = threading.RLock()


def _file_hash(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _inside_root(member_name: str) -> bool:
    path = PurePosixPath(member_name)
    return not path.is_absolute() and ".." not in path.parts


def _renpy_sdk(progress=lambda _message: None) -> Path:
    candidates = [
        Path(os.environ["RENPY_SDK"]).expanduser() if os.environ.get("RENPY_SDK") else None,
        ROOT.parent / ".sincity-emulator" / ENGINE_NAME,
        DATA_ROOT / "engine" / ENGINE_NAME,
    ]
    for candidate in candidates:
        if candidate and (candidate / "renpy.sh").is_file():
            return candidate

    cache = DATA_ROOT / "engine"
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / ENGINE_ARCHIVE
    partial = cache / f"{ENGINE_ARCHIVE}.part"
    if not archive.exists():
        progress("Downloading the Ren'Py preview engine…")
        try:
            with urllib.request.urlopen(ENGINE_URL, timeout=60) as response, partial.open("wb") as output:
                total = int(response.headers.get("Content-Length", "0") or 0)
                done = 0
                while block := response.read(1024 * 1024):
                    output.write(block)
                    done += len(block)
                    if total:
                        progress(f"Downloading Ren'Py: {done * 100 // total}%")
            partial.replace(archive)
        except (OSError, urllib.error.URLError) as exc:
            partial.unlink(missing_ok=True)
            raise RuntimeError(f"Could not download Ren'Py: {exc}") from exc

    if _file_hash(archive) != ENGINE_SHA256:
        archive.unlink(missing_ok=True)
        raise RuntimeError("The Ren'Py download failed its SHA-256 checksum check.")

    progress("Installing the Ren'Py preview engine…")
    staging = Path(tempfile.mkdtemp(prefix="renpy-", dir=cache))
    try:
        with tarfile.open(archive, "r:bz2") as bundle:
            members = bundle.getmembers()
            for member in members:
                if not _inside_root(member.name) or member.issym() or member.islnk():
                    raise RuntimeError("The Ren'Py archive contains an unexpected path.")
            bundle.extractall(staging, members=members)
        unpacked = staging / ENGINE_NAME
        if not (unpacked / "renpy.sh").is_file():
            raise RuntimeError("The Ren'Py archive did not include its Linux launcher.")
        target = cache / ENGINE_NAME
        if target.exists():
            shutil.rmtree(target)
        unpacked.replace(target)
        return target
    except (OSError, tarfile.TarError) as exc:
        raise RuntimeError(f"Could not unpack Ren'Py: {exc}") from exc
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _job(task) -> str:
    job_id = uuid.uuid4().hex
    with LOCK:
        JOBS[job_id] = {"id": job_id, "status": "running", "progress": "Starting…"}

    def progress(message: str) -> None:
        with LOCK:
            if job_id in JOBS:
                JOBS[job_id]["progress"] = message

    def work() -> None:
        try:
            result = task(progress)
            with LOCK:
                JOBS[job_id].update({"status": "complete", "progress": "Done", "result": result})
        except Exception as exc:
            with LOCK:
                JOBS[job_id].update({"status": "error", "progress": "Stopped", "error": str(exc)})

    threading.Thread(target=work, name=f"pdf-story-{job_id[:8]}", daemon=True).start()
    return job_id


class Handler(BaseHTTPRequestHandler):
    server_version = "PDFStoryStudio/0.1"

    def log_message(self, format: str, *args) -> None:
        # Do not log request bodies, which can contain an API key.
        super().log_message(format, *args)

    def _send(self, status: int, body: bytes, content_type: str, extra_headers: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'")
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, value: dict) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length > MAX_JSON_BYTES:
            raise ValueError("Request is too large.")
        value = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("Expected a JSON object.")
        return value

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._static("index.html")
            return
        if parsed.path == "/api/diagnostics":
            self._json(200, {"version": APP_VERSION, "local_generation": True, "debug_console": True})
            return
        if parsed.path.startswith("/web/"):
            self._static(parsed.path.removeprefix("/web/"))
            return
        if parsed.path.startswith("/api/jobs/"):
            job_id = parsed.path.rsplit("/", 1)[-1]
            with LOCK:
                job = JOBS.get(job_id)
            if job:
                self._json(200, job)
            else:
                self._json(404, {"error": "Job not found."})
            return
        if parsed.path == "/api/download":
            book_id = parse_qs(parsed.query).get("id", [""])[0]
            with LOCK:
                book = BOOKS.get(book_id)
            if not book or not book.get("zip_path") or not Path(book["zip_path"]).is_file():
                self._json(404, {"error": "No playable export is available."})
                return
            path = Path(book["zip_path"])
            safe_title = re.sub(r"[^a-zA-Z0-9_-]+", "_", book.get("title", "story"))[:60]
            self._send(
                200,
                path.read_bytes(),
                "application/zip",
                {"Content-Disposition": f'attachment; filename="{safe_title or "story"}.zip"'},
            )
            return
        self._json(404, {"error": "Not found."})

    def _static(self, relative: str) -> None:
        path = (WEB_ROOT / relative).resolve()
        if WEB_ROOT.resolve() not in path.parents or not path.is_file():
            self._json(404, {"error": "Not found."})
            return
        content_type = "text/html; charset=utf-8" if path.suffix == ".html" else "text/plain; charset=utf-8"
        if path.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        elif path.suffix == ".js":
            content_type = "text/javascript; charset=utf-8"
        self._send(200, path.read_bytes(), content_type)

    def do_POST(self) -> None:
        try:
            if self.path.startswith("/api/upload"):
                self._upload()
            elif self.path == "/api/outline":
                self._outline()
            elif self.path == "/api/story":
                self._story()
            elif self.path == "/api/play":
                self._play()
            else:
                self._json(404, {"error": "Not found."})
        except (ValueError, json.JSONDecodeError) as exc:
            self._json(400, {"error": str(exc)})
        except (PdfError, ModelError) as exc:
            self._json(422, {"error": str(exc)})
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _upload(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > MAX_PDF_BYTES:
            raise ValueError("Choose a PDF smaller than 80 MB.")
        content = self.rfile.read(length)
        if b"%PDF" not in content[:1024]:
            raise ValueError("The selected file does not look like a PDF.")

        raw_name = parse_qs(urlparse(self.path).query).get("name", ["book.pdf"])[0]
        filename = Path(raw_name.replace("\\", "/")).name
        if not filename.lower().endswith(".pdf"):
            filename += ".pdf"

        book_id = uuid.uuid4().hex
        project = BOOK_ROOT / book_id
        project.mkdir(parents=True, exist_ok=False)
        pdf_path = project / "source.pdf"
        pdf_path.write_bytes(content)
        pages = extract_pages(pdf_path)
        page_data = [{"page": number, "text": text} for number, text in enumerate(pages, start=1)]
        (project / "pages.json").write_text(json.dumps(page_data, ensure_ascii=False, indent=2), encoding="utf-8")
        with LOCK:
            BOOKS[book_id] = {"id": book_id, "project": project, "pages": pages, "filename": filename}

        preview = []
        for page in page_data[:3]:
            preview.append({"page": page["page"], "text": page["text"][:3500]})
        self._json(
            200,
            {
                "id": book_id,
                "filename": filename,
                "page_count": len(pages),
                "word_count": sum(len(page.split()) for page in pages),
                "empty_pages": [page["page"] for page in page_data if not page["text"]],
                "preview": preview,
            },
        )

    def _credentials(self, body: dict) -> tuple[str, str]:
        api_key = str(body.get("api_key") or os.environ.get("OPENAI_API_KEY", "")).strip()
        model = str(body.get("model") or os.environ.get("OPENAI_MODEL") or "gpt-6-astra").strip()
        if not api_key:
            raise ValueError("Enter an API key or set OPENAI_API_KEY in the environment.")
        if not model:
            raise ValueError("Enter a model name.")
        return api_key, model

    def _outline(self) -> None:
        body = self._json_body()
        book_id = str(body.get("id", ""))
        with LOCK:
            book = BOOKS.get(book_id)
        if not book:
            raise ValueError("Upload the PDF again; this browser session no longer has it loaded.")
        generation_mode = body.get("generation_mode", "local")
        if generation_mode not in {"local", "openai"}:
            raise ValueError("Choose a valid generation method.")
        if generation_mode == "openai":
            api_key, model = self._credentials(body)
        mode = body.get("mode", "inspired")
        if mode not in {"faithful", "inspired"}:
            raise ValueError("Choose a valid adaptation mode.")
        scene_count = max(3, min(8, int(body.get("scene_count", 5))))

        def task(progress):
            if generation_mode == "local":
                outline = build_local_outline(book["pages"], mode, scene_count, progress)
            else:
                outline = build_outline(book["pages"], api_key, model, mode, scene_count, progress)
                outline["generation_mode"] = "openai"
            output = book["project"] / "outline.json"
            output.write_text(json.dumps(outline, ensure_ascii=False, indent=2), encoding="utf-8")
            return {"book_id": book_id, "outline": outline}

        self._json(202, {"job_id": _job(task)})

    def _story(self) -> None:
        body = self._json_body()
        book_id = str(body.get("id", ""))
        with LOCK:
            book = BOOKS.get(book_id)
        if not book:
            raise ValueError("Upload the PDF again; this browser session no longer has it loaded.")
        outline = body.get("outline")
        if not isinstance(outline, dict):
            raise ValueError("The edited outline must be a JSON object.")
        generation_mode = body.get("generation_mode", outline.get("generation_mode", "local"))
        if generation_mode not in {"local", "openai"}:
            raise ValueError("Choose a valid generation method.")
        api_key, model = ("", "")
        if generation_mode == "openai":
            api_key, model = self._credentials(body)
        scene_count = max(3, min(8, int(body.get("scene_count", 5))))

        def task(progress):
            if generation_mode == "local":
                screenplay = build_local_screenplay(outline, scene_count, progress)
            else:
                screenplay = build_screenplay(outline, api_key, model, scene_count, progress)
            (book["project"] / "screenplay.json").write_text(
                json.dumps(screenplay, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            game_dir = book["project"] / "playable_game"
            export_game(screenplay, game_dir)
            archive_path = book["project"] / "playable_game.zip"
            with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for path in sorted(game_dir.rglob("*")):
                    if path.is_file():
                        archive.write(path, path.relative_to(game_dir.parent))
            with LOCK:
                BOOKS[book_id].update(
                    {"title": screenplay.get("title", "story"), "game_dir": game_dir, "zip_path": archive_path}
                )
            return {
                "book_id": book_id,
                "title": screenplay.get("title", "Untitled Story"),
                "scene_count": len(screenplay["scenes"]),
                "scenes": screenplay["scenes"],
                "download_url": f"/api/download?id={quote(book_id)}",
            }

        self._json(202, {"job_id": _job(task)})

    def _play(self) -> None:
        body = self._json_body()
        book_id = str(body.get("id", ""))
        with LOCK:
            book = BOOKS.get(book_id)
        if not book or not book.get("game_dir"):
            raise ValueError("Generate the screenplay before previewing it.")

        def task(progress):
            sdk = _renpy_sdk(progress)
            progress("Opening the playable preview…")
            log_path = book["project"] / "preview.log"
            log = log_path.open("ab")
            try:
                process = subprocess.Popen(
                    [str(sdk / "renpy.sh"), str(book["game_dir"]), "run"],
                    cwd=sdk,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            finally:
                log.close()
            if process.poll() is not None:
                raise RuntimeError(f"Ren'Py closed immediately. See {log_path} for details.")
            return {"message": "The game preview is open."}

        self._json(202, {"job_id": _job(task)})


def main() -> None:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    BOOK_ROOT.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}/"
    print(f"PDF Story Studio is running at {url}")
    print("Press Ctrl+C to stop it.")
    threading.Thread(target=lambda: webbrowser.open(url), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping PDF Story Studio.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
