"""
Tests for file ingestion and format extraction service.
"""

from __future__ import annotations

import io
import zipfile
import pytest
from app.services.ingestion import _detect_language, _extract_from_zip


class TestIngestionService:
    def test_detect_language(self) -> None:
        assert _detect_language("script.py") == "python"
        assert _detect_language("app.ts") == "typescript"
        assert _detect_language("index.jsx") == "javascript"
        assert _detect_language("unknown.xyz") == "python"

    def test_extract_from_zip_valid(self) -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("test.py", "x = 42\n")
            zf.writestr("notes.txt", "ignore me")
        content = buf.getvalue()

        source_code, member, language = _extract_from_zip(content)
        assert member == "test.py"
        assert language == "python"
        assert "x = 42" in source_code

    def test_extract_from_zip_no_supported_files_raises(self) -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("notes.txt", "ignore me")
        content = buf.getvalue()

        with pytest.raises(ValueError, match="ZIP archive contains no supported"):
            _extract_from_zip(content)
