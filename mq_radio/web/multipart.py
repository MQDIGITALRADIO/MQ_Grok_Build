"""Minimal multipart/form-data parser for stdlib HTTP handler (no cgi)."""

from __future__ import annotations

from typing import Any


def parse_multipart(content_type: str, body: bytes) -> dict[str, Any]:
    """Return {field_name: str|dict} where file fields are {filename, content_type, data}."""
    result: dict[str, Any] = {}
    if not content_type or "multipart/form-data" not in content_type.lower():
        return result
    boundary = None
    for part in content_type.split(";"):
        part = part.strip()
        if part.lower().startswith("boundary="):
            boundary = part.split("=", 1)[1].strip().strip('"')
            break
    if not boundary:
        return result
    delim = b"--" + boundary.encode("ascii", errors="ignore")
    sections = body.split(delim)
    for section in sections:
        if section in (b"", b"--", b"--\r\n", b"\r\n"):
            continue
        if section.startswith(b"--"):
            continue
        if section.startswith(b"\r\n"):
            section = section[2:]
        if section.endswith(b"\r\n"):
            section = section[:-2]
        if b"\r\n\r\n" not in section:
            continue
        header_blob, data = section.split(b"\r\n\r\n", 1)
        if data.endswith(b"\r\n"):
            data = data[:-2]
        headers: dict[str, str] = {}
        for line in header_blob.split(b"\r\n"):
            if b":" in line:
                k, v = line.split(b":", 1)
                headers[k.decode("latin-1").strip().lower()] = v.decode("latin-1").strip()
        disp = headers.get("content-disposition", "")
        name = None
        filename = None
        for token in disp.split(";"):
            token = token.strip()
            if token.lower().startswith("name="):
                name = token.split("=", 1)[1].strip().strip('"')
            elif token.lower().startswith("filename="):
                filename = token.split("=", 1)[1].strip().strip('"')
        if not name:
            continue
        if filename is not None:
            result[name] = {
                "filename": filename,
                "content_type": headers.get("content-type", "application/octet-stream"),
                "data": data,
            }
        else:
            try:
                result[name] = data.decode("utf-8")
            except UnicodeDecodeError:
                result[name] = data.decode("latin-1")
    return result
