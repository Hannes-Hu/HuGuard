"""
File ingestion service.

Handles the three code-input modes: raw snippet (JSON body), single-file
upload, and ZIP archive. All paths normalise to (source_code, filename,
language) so the graph layer never needs to care about how the code arrived.
"""

from __future__ import annotations

import io
import uuid
import zipfile
from pathlib import Path

import aiofiles
import structlog
from fastapi import UploadFile

from app.core.config import get_settings

log = structlog.get_logger(__name__)

# Languages we can meaningfully analyse with our current tool chain
_SUPPORTED_EXTENSIONS: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".jsx": "javascript",
    ".tsx": "typescript",
}


def _detect_language(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    return _SUPPORTED_EXTENSIONS.get(ext, "python")


async def save_upload(upload: UploadFile) -> Path:
    """Persist an uploaded file to the uploads directory and return its path."""
    settings = get_settings()
    dest_dir = settings.upload_dir_path / str(uuid.uuid4())
    dest_dir.mkdir(parents=True, exist_ok=True)

    safe_name = Path(upload.filename or "upload").name
    dest_path = dest_dir / safe_name

    async with aiofiles.open(dest_path, "wb") as f:
        content = await upload.read()
        if len(content) > settings.max_upload_size_bytes:
            raise ValueError(
                f"Upload exceeds maximum allowed size of {settings.max_upload_size_bytes} bytes"
            )
        await f.write(content)

    log.info("File saved", path=str(dest_path), size=len(content))
    return dest_path


async def extract_source_from_file(upload: UploadFile) -> tuple[str, str, str]:
    """
    Extract (source_code, filename, language) from an uploaded file.

    For ZIPs we pick the first supported source file we find. This is a
    deliberate simplification – a production system would let the user
    select the target file from the archive manifest.
    """
    content = await upload.read()
    if len(content) > get_settings().max_upload_size_bytes:
        raise ValueError("Upload exceeds maximum allowed size")

    filename = upload.filename or "upload.py"

    if filename.endswith(".zip"):
        return _extract_from_zip(content)

    source_code = content.decode("utf-8", errors="replace")
    language = _detect_language(filename)
    return source_code, filename, language


def _extract_from_zip(content: bytes) -> tuple[str, str, str]:
    """Pick the first supported source file from a ZIP archive."""
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        members = zf.namelist()
        for member in members:
            if Path(member).suffix.lower() in _SUPPORTED_EXTENSIONS:
                source_bytes = zf.read(member)
                source_code = source_bytes.decode("utf-8", errors="replace")
                language = _detect_language(member)
                log.info("Extracted from ZIP", file=member, language=language)
                return source_code, member, language

    raise ValueError("ZIP archive contains no supported source files (.py, .js, .ts)")
