#!/usr/bin/env python3
"""Advance one canonical schema 1.4 workflow state after fail-closed gates."""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
import os
import re
import stat
import sys
import struct
import zlib
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from review_core import (  # noqa: E402
    CANONICAL_WORKFLOW_STATES,
    COMBINED_APPROVAL_SCOPE,
    InterprocessLock,
    LockUnavailableError,
    atomic_write_json,
    sha256_json,
    strict_json_loads,
    valid_sha256,
    validate_canonical_workflow_transition,
    validate_workflow_receipts,
)
from manifest_contract import validated_revision  # noqa: E402
from review_server import (  # noqa: E402
    RENDER_CONTRACT,
    absolute_input_path,
    manifest_model,
    read_private_json,
    reject_symlink_path,
    validate_state_manifest,
)


QA_REQUIRED_CHECKS = frozenset(
    {
        "manifest_content_match",
        "slide_count_order",
        "dimensions",
        "files_open",
        "preview_production_parity",
        "no_incomplete_outputs",
        "automated_all_slides",
    }
)
QA_ADVISORY_CHECKS = frozenset({"fonts", "human_sample_review"})
ARTIFACT_KIND_RE = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
EXPORT_RESULT_SCHEMA = "carousel-builder-export-v1"
QA_REPORT_SCHEMA = "carousel-builder-qa-v1"

# The export is intentionally decoded here, so keep every allocation bounded.
# These are generous for the local renderer while preventing malformed inputs
# from turning the workflow gate into an unbounded parser/decompressor.
MAX_PDF_BYTES = 768 * 1024 * 1024
MAX_PDF_BASE_BYTES = 16 * 1024 * 1024
MAX_PDF_BYTES_PER_PAGE = 16 * 1024 * 1024
MAX_PDF_OBJECTS = 10_000
MAX_PDF_OBJECT_BYTES = 8 * 1024 * 1024
MAX_PDF_PAGES = 2_000
MAX_PDF_PARSE_DEPTH = 64
MAX_PNG_BYTES = 64 * 1024 * 1024
MAX_PNG_IDAT_BYTES = 48 * 1024 * 1024
MAX_PNG_RAW_BYTES = 128 * 1024 * 1024
MAX_PNG_CHUNKS = 100_000
PDF_POINT_SCALE = 9 / 16


class _PdfRef(tuple):
    """Small immutable marker for an indirect PDF object reference."""

    __slots__ = ()

    def __new__(cls, object_number: int, generation: int) -> "_PdfRef":
        return tuple.__new__(cls, (object_number, generation))


class _PdfParser:
    """Bounded enough PDF token parser for the structural delivery contract."""

    _WHITESPACE = b" \t\r\n\f\x00"
    _DELIMITERS = b"()<>[]{}/%"

    def __init__(self, data: bytes, *, max_depth: int = MAX_PDF_PARSE_DEPTH) -> None:
        self.data = data
        self.length = len(data)
        self.max_depth = max_depth

    def _skip(self, index: int) -> int:
        while index < self.length:
            byte = self.data[index]
            if byte in self._WHITESPACE:
                index += 1
                continue
            if byte == ord("%"):
                newline = self.data.find(b"\n", index)
                index = self.length if newline < 0 else newline + 1
                continue
            break
        return index

    def _token(self, index: int) -> tuple[bytes, int]:
        start = index
        while index < self.length:
            byte = self.data[index]
            if byte in self._WHITESPACE or byte in self._DELIMITERS:
                break
            index += 1
        if index == start:
            raise ValueError("token PDF vuoto")
        return self.data[start:index], index

    def value(self, index: int = 0, *, depth: int = 0) -> tuple[object, int]:
        if depth > self.max_depth:
            raise ValueError("profondità PDF eccessiva")
        index = self._skip(index)
        if index >= self.length:
            raise ValueError("valore PDF troncato")
        if self.data.startswith(b"<<", index):
            return self.dictionary(index, depth=depth + 1)
        if self.data[index] == ord("["):
            values: list[object] = []
            index += 1
            while True:
                index = self._skip(index)
                if index >= self.length:
                    raise ValueError("array PDF troncato")
                if self.data[index] == ord("]"):
                    return values, index + 1
                value, index = self.value(index, depth=depth + 1)
                # Resolve the common `number number R` form as one value.
                if (
                    isinstance(value, (int, float))
                    and index < self.length
                ):
                    second_index = self._skip(index)
                    try:
                        second, after_second = self.value(second_index)
                    except ValueError:
                        second = None
                    if isinstance(second, (int, float)) and float(second).is_integer():
                        after_ref = self._skip(after_second)
                        if self.data.startswith(b"R", after_ref):
                            value = _PdfRef(int(value), int(second))
                            index = after_ref + 1
                values.append(value)
        if self.data[index] == ord("("):
            depth = 1
            index += 1
            while index < self.length and depth:
                byte = self.data[index]
                if byte == ord("\\"):
                    index += 2
                    continue
                if byte == ord("("):
                    depth += 1
                elif byte == ord(")"):
                    depth -= 1
                index += 1
            if depth:
                raise ValueError("stringa PDF troncata")
            return "", index
        if self.data[index] == ord("<"):
            end = self.data.find(b">", index + 1)
            if end < 0:
                raise ValueError("stringa esadecimale PDF troncata")
            return "", end + 1
        if self.data[index] == ord("/"):
            token, index = self._token(index + 1)
            return token.decode("latin1"), index
        token, index = self._token(index)
        try:
            text = token.decode("ascii")
            if re.fullmatch(r"[+-]?\d+", text):
                return int(text), index
            if re.fullmatch(r"[+-]?(?:\d+\.\d*|\.\d+)", text):
                return float(text), index
        except UnicodeDecodeError:
            pass
        return token, index

    def dictionary(self, index: int = 0, *, depth: int = 0) -> tuple[dict[str, object], int]:
        if depth > self.max_depth:
            raise ValueError("profondità PDF eccessiva")
        if not self.data.startswith(b"<<", index):
            raise ValueError("dizionario PDF atteso")
        values: dict[str, object] = {}
        index += 2
        while True:
            index = self._skip(index)
            if self.data.startswith(b">>", index):
                return values, index + 2
            if index >= self.length or self.data[index] != ord("/"):
                raise ValueError("chiave PDF non valida")
            key, index = self._token(index + 1)
            value, index = self.value(index, depth=depth + 1)
            # Indirect references in dictionaries are common for /Pages and
            # are not represented by the generic scalar parser above.
            if isinstance(value, (int, float)):
                second_index = self._skip(index)
                try:
                    second, after_second = self.value(second_index)
                except ValueError:
                    second = None
                if isinstance(second, (int, float)) and float(second).is_integer():
                    after_ref = self._skip(after_second)
                    if self.data.startswith(b"R", after_ref):
                        value = _PdfRef(int(value), int(second))
                        index = after_ref + 1
            values[key.decode("latin1")] = value


def _pdf_skip(data: bytes, index: int) -> int:
    while index < len(data) and data[index] in _PdfParser._WHITESPACE:
        index += 1
    return index


def _parse_pdf_xref(data: bytes) -> tuple[dict[_PdfRef, int], _PdfRef]:
    """Read the authoritative classic xref chain and trailer Root."""
    candidates = list(re.finditer(rb"startxref\s+(\d+)", data))
    if not candidates:
        raise ValueError("PDF non parsabile: senza startxref")
    xref: dict[_PdfRef, int] = {}
    root: _PdfRef | None = None
    visited_offsets: set[int] = set()
    last_error: ValueError | None = None
    # The last valid marker is the normal PDF case.  Trying preceding markers
    # also prevents a marker-like byte sequence in a trailing stream from
    # masking the real one.
    for candidate in reversed(candidates):
        try:
            offset = int(candidate.group(1))
            xref.clear()
            root = None
            visited_offsets.clear()
            sections = 0
            while True:
                if offset in visited_offsets:
                    raise ValueError("catena xref ciclica")
                visited_offsets.add(offset)
                sections += 1
                if sections > 32 or offset < 0 or offset >= len(data):
                    raise ValueError("offset xref non valido")
                index = _pdf_skip(data, offset)
                if not data.startswith(b"xref", index):
                    raise ValueError("tabella xref mancante")
                index = _pdf_skip(data, index + 4)
                while True:
                    line_end = data.find(b"\n", index)
                    if line_end < 0:
                        raise ValueError("xref troncato")
                    line = data[index:line_end].strip().rstrip(b"\r")
                    index = line_end + 1
                    if line == b"trailer":
                        break
                    header = re.fullmatch(rb"(\d+)\s+(\d+)", line)
                    if not header:
                        raise ValueError("sottosezione xref non valida")
                    first = int(header.group(1))
                    count = int(header.group(2))
                    if (
                        count < 0
                        or count > MAX_PDF_OBJECTS
                        or first > MAX_PDF_OBJECTS
                        or first + count > MAX_PDF_OBJECTS + 1
                    ):
                        raise ValueError("limite oggetti PDF superato")
                    for number in range(first, first + count):
                        line_end = data.find(b"\n", index)
                        if line_end < 0:
                            raise ValueError("xref troncato")
                        entry = data[index:line_end].strip().rstrip(b"\r")
                        index = line_end + 1
                        parsed = re.fullmatch(rb"(\d{1,12})\s+(\d{1,8})\s+([nf])", entry)
                        if not parsed:
                            raise ValueError("voce xref non valida")
                        entry_offset = int(parsed.group(1))
                        generation = int(parsed.group(2))
                        if parsed.group(3) == b"n":
                            if entry_offset >= len(data):
                                raise ValueError("offset oggetto PDF non valido")
                            if len(xref) >= MAX_PDF_OBJECTS:
                                raise ValueError("limite oggetti PDF superato")
                            xref.setdefault(_PdfRef(number, generation), entry_offset)
                trailer_value, index = _PdfParser(data).dictionary(_pdf_skip(data, index))
                candidate_root = trailer_value.get("Root")
                if candidate_root is not None and root is None:
                    if not isinstance(candidate_root, _PdfRef):
                        raise ValueError("trailer Root non è un riferimento PDF")
                    root = candidate_root
                previous = trailer_value.get("Prev")
                if previous is None:
                    break
                if not isinstance(previous, int) or isinstance(previous, bool):
                    raise ValueError("trailer Prev non valido")
                offset = previous
            if root is None:
                raise ValueError("trailer Root mancante")
            if root not in xref:
                raise ValueError("trailer Root non presente nello xref")
            return xref, root
        except ValueError as exc:
            last_error = exc
            continue
    if last_error is not None:
        raise ValueError(f"PDF xref non valido: {last_error}") from last_error
    raise ValueError("PDF xref non valido")


def _parse_pdf_objects(data: bytes) -> tuple[dict[_PdfRef, object], _PdfRef]:
    xref, root = _parse_pdf_xref(data)
    objects: dict[_PdfRef, object] = {}
    offsets = sorted(set(xref.values()))
    for ref, offset in xref.items():
        next_index = bisect.bisect_right(offsets, offset)
        next_offset = offsets[next_index] if next_index < len(offsets) else len(data)
        end = min(next_offset, offset + MAX_PDF_OBJECT_BYTES)
        if end <= offset:
            raise ValueError("oggetto PDF troncato")
        match = re.match(rb"(\d+)\s+(\d+)\s+obj\b", data[offset:end])
        if not match or int(match.group(1)) != ref[0] or int(match.group(2)) != ref[1]:
            raise ValueError(f"offset xref non coincide con oggetto PDF {ref[0]}")
        parser = _PdfParser(data[offset:end])
        try:
            value, _ = parser.value(match.end())
        except (IndexError, ValueError) as exc:
            raise ValueError(f"oggetto PDF non parsabile {ref[0]}") from exc
        objects[ref] = value
    if not objects:
        raise ValueError("PDF senza oggetti indiretti")
    return objects, root


def _read_bounded_file(path: Path, *, label: str, limit: int) -> bytes:
    try:
        size = path.stat().st_size
        if size > limit:
            raise ValueError(f"{label} oltre il limite di {limit} byte: {path}")
        with path.open("rb") as stream:
            return stream.read(limit + 1)
    except ValueError:
        raise
    except (OSError, MemoryError) as exc:
        raise ValueError(f"{label} non leggibile: {path}") from exc


def _pdf_byte_limit(expected_pages: int) -> int:
    return min(
        MAX_PDF_BYTES,
        MAX_PDF_BASE_BYTES + expected_pages * MAX_PDF_BYTES_PER_PAGE,
    )


def _pdf_resolve(value: object, objects: dict[_PdfRef, object], *, label: str) -> object:
    if isinstance(value, _PdfRef):
        if value not in objects:
            raise ValueError(f"{label}: riferimento PDF mancante {value[0]} {value[1]} R")
        return objects[value]
    return value


def validate_pdf_artifact(
    path: Path,
    *,
    expected_width: int,
    expected_height: int,
    expected_pages: int,
) -> None:
    """Require a structurally parseable PDF with the contract page geometry."""
    if not isinstance(expected_pages, int) or isinstance(expected_pages, bool) or not (
        1 <= expected_pages <= MAX_PDF_PAGES
    ):
        raise ValueError("numero pagine PDF fuori limite")
    try:
        byte_limit = _pdf_byte_limit(expected_pages)
        data = _read_bounded_file(path, label="PDF", limit=byte_limit)
    except (MemoryError, RecursionError) as exc:
        raise ValueError(f"PDF non validabile: {path}") from exc
    if len(data) > byte_limit:
        raise ValueError(f"PDF oltre il limite di {byte_limit} byte: {path}")
    if not data.startswith(b"%PDF-") or not data[-64:].rstrip().endswith(b"%%EOF"):
        raise ValueError(f"PDF non parsabile o troncato: {path}")
    try:
        objects, root = _parse_pdf_objects(data)
        catalog = _pdf_resolve(root, objects, label="trailer.Root")
        if not isinstance(catalog, dict) or catalog.get("Type") != "Catalog":
            raise ValueError("trailer.Root non punta a un Catalog PDF")
        pages_ref = catalog.get("Pages")
        pages_value = _pdf_resolve(pages_ref, objects, label="Catalog.Pages")
        if not isinstance(pages_value, dict) or pages_value.get("Type") != "Pages":
            raise ValueError("Catalog.Pages non è un nodo Pages")

        seen: set[_PdfRef] = set()

        def walk(
            value: object,
            inherited_media_box: object = None,
            depth: int = 0,
        ) -> list[list[object]]:
            if depth > MAX_PDF_PARSE_DEPTH:
                raise ValueError("profondità albero Pages eccessiva")
            if not isinstance(value, dict):
                raise ValueError("nodo PDF pagina non è un dizionario")
            node_type = value.get("Type")
            media_box = value.get("MediaBox", inherited_media_box)
            if node_type == "Page":
                resolved = _pdf_resolve(media_box, objects, label="Page.MediaBox")
                if not isinstance(resolved, list) or len(resolved) != 4:
                    raise ValueError("Page.MediaBox non valido")
                try:
                    coords = [float(item) for item in resolved]
                except (TypeError, ValueError) as exc:
                    raise ValueError("Page.MediaBox non numerico") from exc
                width = coords[2] - coords[0]
                height = coords[3] - coords[1]
                expected_pdf_width = expected_width * PDF_POINT_SCALE
                expected_pdf_height = expected_height * PDF_POINT_SCALE
                if not (
                    math.isclose(width, expected_pdf_width, rel_tol=0, abs_tol=1e-6)
                    and math.isclose(height, expected_pdf_height, rel_tol=0, abs_tol=1e-6)
                ):
                    raise ValueError(
                        f"Page.MediaBox {width:g}x{height:g}, atteso "
                        f"{expected_pdf_width:g}x{expected_pdf_height:g} pt"
                    )
                return [resolved]
            if node_type != "Pages":
                raise ValueError("albero Pages contiene un nodo sconosciuto")
            kids = value.get("Kids")
            if not isinstance(kids, list) or not kids:
                raise ValueError("Pages.Kids mancante o vuoto")
            pages: list[list[object]] = []
            if len(kids) > MAX_PDF_PAGES:
                raise ValueError("limite pagine PDF superato")
            for kid in kids:
                if not isinstance(kid, _PdfRef):
                    raise ValueError("Pages.Kids contiene un riferimento non valido")
                if kid in seen:
                    raise ValueError("albero Pages ciclico o duplicato")
                seen.add(kid)
                pages.extend(
                    walk(_pdf_resolve(kid, objects, label="Pages.Kids"), media_box, depth + 1)
                )
                if len(pages) > MAX_PDF_PAGES:
                    raise ValueError("limite pagine PDF superato")
            count = value.get("Count")
            if not isinstance(count, int) or isinstance(count, bool) or count != len(pages):
                raise ValueError("Pages.Count non coincide con le pagine effettive")
            return pages

        pages = walk(pages_value)
        if len(pages) != expected_pages:
            raise ValueError(
                f"PDF con {len(pages)} pagine, attese {expected_pages}"
            )
    except (MemoryError, RecursionError) as exc:
        raise ValueError(f"PDF non validabile ({path}): limiti risorsa superati") from exc
    except ValueError as exc:
        raise ValueError(f"PDF non valido ({path}): {exc}") from exc


def validate_png_artifact(
    path: Path,
    *,
    expected_width: int,
    expected_height: int,
) -> None:
    """Decode all PNG scanlines and enforce the rendered slide geometry."""
    try:
        data = _read_bounded_file(path, label="PNG", limit=MAX_PNG_BYTES)
    except (MemoryError, RecursionError) as exc:
        raise ValueError(f"PNG non validabile: {path}") from exc
    if len(data) > MAX_PNG_BYTES:
        raise ValueError(f"PNG oltre il limite di {MAX_PNG_BYTES} byte: {path}")
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"PNG non decodificabile: {path}")
    position = 8
    ihdr = None
    idat = bytearray()
    seen_idat = False
    closed_idat = False
    seen_iend = False
    palette = False
    chunk_count = 0
    while position < len(data):
        chunk_count += 1
        if chunk_count > MAX_PNG_CHUNKS:
            raise ValueError(f"PNG oltre il limite di {MAX_PNG_CHUNKS} chunk: {path}")
        if position + 12 > len(data):
            raise ValueError(f"PNG troncato: {path}")
        length = struct.unpack(">I", data[position:position + 4])[0]
        chunk_start = position + 8
        chunk_end = chunk_start + length
        if chunk_end + 4 > len(data):
            raise ValueError(f"PNG troncato: {path}")
        chunk_type = data[position + 4:position + 8]
        payload = data[chunk_start:chunk_end]
        crc_expected = struct.unpack(">I", data[chunk_end:chunk_end + 4])[0]
        if (zlib.crc32(chunk_type + payload) & 0xFFFFFFFF) != crc_expected:
            raise ValueError(f"PNG CRC non valido: {path}")
        position = chunk_end + 4
        if chunk_type == b"IHDR":
            if ihdr is not None or len(payload) != 13 or position != 8 + 12 + 13:
                raise ValueError(f"PNG IHDR non valido: {path}")
            ihdr = payload
            width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(">IIBBBBB", payload)
            if (width, height) != (expected_width, expected_height):
                raise ValueError(
                    f"PNG dimensioni {width}x{height}, attese "
                    f"{expected_width}x{expected_height}: {path}"
                )
            valid_depths = {
                0: {1, 2, 4, 8, 16}, 2: {8, 16}, 3: {1, 2, 4, 8},
                4: {8, 16}, 6: {8, 16},
            }
            if color_type not in valid_depths or bit_depth not in valid_depths[color_type]:
                raise ValueError(f"PNG combinazione colore non valida: {path}")
            if compression != 0 or filtering != 0 or interlace != 0:
                raise ValueError(f"PNG usa un metodo non supportato: {path}")
        elif chunk_type == b"PLTE":
            if len(payload) == 0 or len(payload) % 3 or len(payload) > 768:
                raise ValueError(f"PNG PLTE non valido: {path}")
            palette = True
        elif chunk_type == b"IDAT":
            if ihdr is None or closed_idat:
                raise ValueError(f"PNG IDAT fuori sequenza: {path}")
            seen_idat = True
            if len(idat) + len(payload) > MAX_PNG_IDAT_BYTES:
                raise ValueError(
                    f"PNG IDAT oltre il limite di {MAX_PNG_IDAT_BYTES} byte: {path}"
                )
            idat.extend(payload)
        elif chunk_type == b"IEND":
            if len(payload) != 0 or not seen_idat or position != len(data):
                raise ValueError(f"PNG IEND non valido: {path}")
            seen_iend = True
        elif chunk_type[0] & 0x20 == 0 and chunk_type not in {b"tEXt", b"cHRM", b"gAMA", b"sRGB", b"pHYs", b"tIME", b"tRNS"}:
            raise ValueError(f"PNG chunk critico sconosciuto: {path}")
        if seen_idat and chunk_type != b"IDAT" and chunk_type != b"IEND":
            closed_idat = True
    if ihdr is None or not seen_iend or not seen_idat:
        raise ValueError(f"PNG incompleto: {path}")
    width, height, bit_depth, color_type, *_ = struct.unpack(">IIBBBBB", ihdr)
    if color_type == 3 and not palette:
        raise ValueError(f"PNG indicizzato senza palette: {path}")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]
    row_bytes = (width * channels * bit_depth + 7) // 8
    bytes_per_pixel = max(1, (channels * bit_depth + 7) // 8)
    expected_raw = (row_bytes + 1) * height
    if expected_raw > MAX_PNG_RAW_BYTES:
        raise ValueError(f"PNG decompressione oltre il limite di {MAX_PNG_RAW_BYTES} byte: {path}")
    try:
        decompressor = zlib.decompressobj()
        raw = decompressor.decompress(bytes(idat), expected_raw + 1)
        if len(raw) > expected_raw or decompressor.unconsumed_tail:
            raise ValueError("PNG decompressione oltre la dimensione attesa")
    except (zlib.error, MemoryError, ValueError) as exc:
        raise ValueError(f"PNG dati immagine non validi: {path}") from exc
    if (
        not decompressor.eof
        or decompressor.unused_data
        or decompressor.unconsumed_tail
        or len(raw) != expected_raw
    ):
        raise ValueError(f"PNG dati immagine troncati o extra: {path}")
    try:
        previous = bytearray(row_bytes)
        cursor = 0
        for _ in range(height):
            filter_type = raw[cursor]
            cursor += 1
            scanline = raw[cursor:cursor + row_bytes]
            cursor += row_bytes
            if filter_type > 4:
                raise ValueError(f"PNG filtro scanline non valido: {path}")
            # The normal renderer emits filter 0, so retain a fast path for the
            # large common case while still fully reversing every non-zero filter.
            if filter_type == 0:
                previous[:] = scanline
                continue
            reconstructed = bytearray(row_bytes)
            for index, value in enumerate(scanline):
                left = reconstructed[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
                up = previous[index]
                upper_left = previous[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
                if filter_type == 1:
                    predictor = left
                elif filter_type == 2:
                    predictor = up
                elif filter_type == 3:
                    predictor = (left + up) // 2
                else:
                    estimate = left + up - upper_left
                    distances = (
                        abs(estimate - left), abs(estimate - up), abs(estimate - upper_left)
                    )
                    predictor = (left, up, upper_left)[distances.index(min(distances))]
                reconstructed[index] = (value + predictor) & 0xFF
            previous = reconstructed
    except (MemoryError, RecursionError) as exc:
        raise ValueError(f"PNG non validabile: limiti risorsa superati: {path}") from exc


def read_json_object(path: Path, *, label: str) -> dict:
    if path.is_symlink():
        raise ValueError(f"{label} non può essere un collegamento simbolico")
    try:
        value = strict_json_loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"{label} non trovato: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} non è JSON valido: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} deve contenere un oggetto JSON")
    return value


def require_review_approval(manifest: dict, *, stage: str, revision: int) -> None:
    review = manifest.get("review")
    if not isinstance(review, dict):
        raise ValueError(f"Manca la ricevuta di approvazione {stage}")
    stage_matches = review.get("approval_stage") == stage or (
        review.get("approval_scope") == COMBINED_APPROVAL_SCOPE
        and review.get("approval_stage") == "profile_text"
        and stage in {"profile_text", "visual_proof"}
    )
    if (
        review.get("last_action") != "approve"
        or review.get("approval_requested") is not True
        or not stage_matches
        or review.get("applied_manifest_revision") != revision
        or review.get("comments_pending") != 0
        or valid_sha256(review.get("last_feedback_sha256")) is None
        or not isinstance(review.get("last_feedback_id"), str)
        or not review["last_feedback_id"]
    ):
        raise ValueError(
            f"La ricevuta di approvazione {stage} non è completa o non appartiene "
            f"alla revisione {revision}"
        )


def require_no_pending_comments(manifest: dict) -> None:
    review = manifest.get("review")
    pending = review.get("comments_pending") if isinstance(review, dict) else None
    if not isinstance(pending, int) or isinstance(pending, bool) or pending != 0:
        raise ValueError(
            "La transizione è bloccata finché review.comments_pending non è zero"
        )


def require_applied_review_binding(
    state: dict,
    manifest: dict,
    *,
    revision: int,
    receipts: list[dict],
) -> None:
    """Bind the workflow gate to the exact review batch applied to the manifest.

    Advancing the workflow intentionally changes only ``workflow_state`` and the
    bounded receipt ledger, so the session's applied-manifest hash becomes a
    historical hash after the first transition.  Reconstruct only canonical
    ledger prefixes to verify that hash without weakening later transitions.
    """
    review = manifest.get("review")
    if not isinstance(review, dict):
        raise ValueError("Manca la ricevuta review applicata al manifest")

    feedback_id = state.get("applied_feedback_id")
    action = state.get("applied_feedback_action")
    feedback_sha256 = valid_sha256(state.get("applied_feedback_sha256"))
    applied_revision = state.get("applied_manifest_revision")
    applied_manifest_sha256 = valid_sha256(state.get("applied_manifest_sha256"))
    if (
        not isinstance(feedback_id, str)
        or not feedback_id
        or state.get("last_feedback_id") != feedback_id
        or review.get("last_feedback_id") != feedback_id
    ):
        raise ValueError("La ricevuta di sessione non coincide con il feedback applicato")
    if (
        action not in {"feedback", "approve"}
        or state.get("last_action") != action
        or review.get("last_action") != action
    ):
        raise ValueError("L'azione applicata non coincide tra sessione e manifest")
    if (
        feedback_sha256 is None
        or valid_sha256(review.get("last_feedback_sha256")) != feedback_sha256
    ):
        raise ValueError("Il digest del feedback applicato non coincide")
    if (
        not isinstance(applied_revision, int)
        or isinstance(applied_revision, bool)
        or applied_revision != revision
        or review.get("applied_manifest_revision") != revision
    ):
        raise ValueError("La revisione applicata non coincide tra sessione e manifest")
    if applied_manifest_sha256 is None:
        raise ValueError("Manca l'hash del manifest applicato nella sessione")

    current_state = manifest.get("workflow_state")
    current_index = CANONICAL_WORKFLOW_STATES.index(current_state)
    candidates: list[dict] = []
    for origin_index in range(current_index + 1):
        candidate = dict(manifest)
        candidate["workflow_state"] = CANONICAL_WORKFLOW_STATES[origin_index]
        if origin_index == 0:
            candidate.pop("workflow_receipts", None)
            candidates.append(candidate)
            explicit_empty = dict(candidate)
            explicit_empty["workflow_receipts"] = []
            candidates.append(explicit_empty)
        else:
            candidate["workflow_receipts"] = receipts[:origin_index]
            candidates.append(candidate)
    if not any(
        sha256_json(candidate) == applied_manifest_sha256 for candidate in candidates
    ):
        raise ValueError(
            "Il manifest corrente non deriva dall'hash del manifest applicato"
        )


def require_current_visual_proof(model: dict) -> None:
    proof = model.get("proof")
    production = model.get("production")
    if (
        not isinstance(production, dict)
        or production.get("mode") != "renderer"
        or production.get("producer") != RENDER_CONTRACT
    ):
        raise ValueError(
            "La CLI local-editor richiede una prova corrente con production.mode=renderer "
            "e il producer locale"
        )
    if model.get("proof_approved") is not True:
        raise ValueError(
            "La prova visuale non è approvata o non coincide con manifest, asset e renderer correnti"
        )
    if (
        not isinstance(proof, dict)
        or valid_sha256(model.get("render_fingerprint")) is None
        or proof.get("browser") is None
    ):
        raise ValueError("Il contratto della prova visuale corrente è incompleto")


def expected_output_kinds(manifest: dict) -> list[str]:
    production = manifest.get("production")
    values = production.get("expected_outputs") if isinstance(production, dict) else None
    if not isinstance(values, list) or not values:
        raise ValueError("production.expected_outputs deve dichiarare almeno un output")
    normalized: list[str] = []
    aliases = {"contact-sheet": "contact_sheet"}
    for value in values:
        if not isinstance(value, str) or not value:
            raise ValueError("production.expected_outputs contiene un output non valido")
        kind = aliases.get(value, value)
        if kind not in {"pdf", "png", "contact_sheet"}:
            raise ValueError(f"Output atteso non verificabile dalla CLI: {value!r}")
        if kind not in normalized:
            normalized.append(kind)
    if "pdf" not in normalized:
        raise ValueError("Il contratto renderer locale richiede pdf negli output attesi")
    return normalized


def _absolute_regular_file(value: object, *, field: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} deve essere un percorso assoluto")
    path = Path(value)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ValueError(f"{field} non è un file regolare assoluto esistente")
    return path


def _absolute_directory(value: object, *, field: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} deve essere un percorso assoluto")
    path = Path(value)
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        raise ValueError(f"{field} non è una directory assoluta esistente")
    return path


def validated_artifact_records(
    value: object,
    *,
    field: str,
    expected: list[str],
    slide_count: int,
) -> dict[str, list[Path]]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} deve contenere gli artefatti e i relativi SHA-256")
    allowed = set(expected)
    grouped: dict[str, list[Path]] = {}
    seen_paths: set[Path] = set()
    seen_files: set[tuple[int, int]] = set()
    for index, artifact in enumerate(value):
        if not isinstance(artifact, dict) or set(artifact) != {"kind", "path", "sha256"}:
            raise ValueError(f"{field}[{index}] deve contenere kind, path e sha256")
        kind = artifact.get("kind")
        if (
            not isinstance(kind, str)
            or not ARTIFACT_KIND_RE.fullmatch(kind)
            or kind not in allowed
        ):
            raise ValueError(f"{field}[{index}].kind non atteso: {kind!r}")
        path = _absolute_regular_file(
            artifact.get("path"), field=f"{field}[{index}].path"
        ).resolve()
        metadata = path.stat()
        identity = (
            (metadata.st_dev, metadata.st_ino) if metadata.st_ino else None
        )
        if path in seen_paths or (identity is not None and identity in seen_files):
            raise ValueError(f"{field} contiene artefatti duplicati")
        seen_paths.add(path)
        if identity is not None:
            seen_files.add(identity)
        suffix = path.suffix.lower()
        if (kind == "pdf" and suffix != ".pdf") or (
            kind in {"png", "contact_sheet"} and suffix != ".png"
        ):
            raise ValueError(f"{field}[{index}] non ha l'estensione prevista per {kind}")
        expected_digest = valid_sha256(artifact.get("sha256"))
        if expected_digest is None or sha256_regular_file(path) != expected_digest:
            raise ValueError(f"Digest artefatto non valido o non coincidente: {path}")
        grouped.setdefault(kind, []).append(path)

    required_counts = {
        "pdf": 1,
        "png": slide_count,
        "contact_sheet": 1,
    }
    if set(grouped) != allowed:
        raise ValueError(f"{field} non copre esattamente gli output attesi")
    for kind in expected:
        if len(grouped[kind]) != required_counts[kind]:
            raise ValueError(
                f"{field} contiene {len(grouped[kind])} artefatti {kind}; "
                f"attesi {required_counts[kind]}"
            )
    return grouped


def validate_render_result(
    result: dict,
    *,
    manifest: dict,
    model: dict,
    revision: int,
) -> None:
    if (
        result.get("result_schema") != EXPORT_RESULT_SCHEMA
        or result.get("status") != "ok"
        or result.get("revision") != revision
        or result.get("workflow_state") != "rendering"
        or result.get("render_fingerprint") != model.get("render_fingerprint")
        or result.get("contract") != RENDER_CONTRACT
        or result.get("proof_browser") != model["proof"].get("browser")
        or result.get("preview_production_parity") != "exact"
        or result.get("live_session_verified") is not True
        or result.get("approval_verified") is not True
        or result.get("slides") != len(model.get("slides", []))
        or result.get("width") != model.get("format", {}).get("width")
        or result.get("height") != model.get("format", {}).get("height")
    ):
        raise ValueError(
            "Il render-result non attesta stato, revisione, contratto, browser e parità correnti"
        )

    expected = expected_output_kinds(manifest)
    artifacts = validated_artifact_records(
        result.get("artifact_sha256"),
        field="render-result.artifact_sha256",
        expected=expected,
        slide_count=len(model.get("slides", [])),
    )
    pdf = _absolute_regular_file(result.get("output"), field="render-result.output").resolve()
    if pdf.suffix.lower() != ".pdf":
        raise ValueError("render-result.output deve essere un PDF")
    if "pdf" not in expected:
        raise ValueError("Il renderer ha prodotto un PDF non dichiarato negli output attesi")
    if artifacts["pdf"] != [pdf]:
        raise ValueError("render-result.output non coincide con l'artefatto PDF attestato")

    expected_width = model.get("format", {}).get("width")
    expected_height = model.get("format", {}).get("height")
    if not isinstance(expected_width, int) or not isinstance(expected_height, int):
        raise ValueError("Il contratto render non dichiara dimensioni intere verificabili")
    validate_pdf_artifact(
        pdf,
        expected_width=expected_width,
        expected_height=expected_height,
        expected_pages=len(model.get("slides", [])),
    )

    if "png" in expected:
        png_dir = _absolute_directory(result.get("png_dir"), field="render-result.png_dir")
        png_entries = list(png_dir.iterdir())
        try:
            png_metadata = [(path, path.lstat()) for path in png_entries]
        except OSError as exc:
            raise ValueError(f"Impossibile verificare la directory PNG: {exc}") from exc
        if any(
            path.suffix.lower() != ".png" or not stat.S_ISREG(metadata.st_mode)
            for path, metadata in png_metadata
        ):
            raise ValueError(
                "La directory PNG deve contenere esclusivamente file regolari .png"
            )
        png_files = sorted(path.resolve() for path in png_entries)
        if (
            result.get("png_files") != len(model.get("slides", []))
            or len(png_files) != result.get("png_files")
            or set(png_files) != set(artifacts["png"])
        ):
            raise ValueError("Il set PNG prodotto non coincide con le slide correnti")
        for png in artifacts["png"]:
            validate_png_artifact(
                png,
                expected_width=expected_width,
                expected_height=expected_height,
            )
    elif "png_dir" in result or "png_files" in result:
        raise ValueError("Il render-result contiene PNG non dichiarati negli output attesi")

    if "contact_sheet" in expected:
        contact = _absolute_regular_file(
            result.get("contact_sheet"), field="render-result.contact_sheet"
        )
        if contact.suffix.lower() != ".png":
            raise ValueError("render-result.contact_sheet deve essere un PNG")
        if artifacts["contact_sheet"] != [contact.resolve()]:
            raise ValueError("render-result.contact_sheet non coincide con l'artefatto attestato")
        columns = min(4, len(model.get("slides", [])))
        rows = (len(model.get("slides", [])) + columns - 1) // columns
        validate_png_artifact(
            contact,
            expected_width=48 + columns * 360 + (columns - 1) * 24,
            expected_height=48 + rows * 450 + (rows - 1) * 24,
        )
    elif "contact_sheet" in result:
        raise ValueError("Il render-result contiene una contact sheet non dichiarata")


def sha256_regular_file(path: Path) -> str:
    """Hash one stable, singly linked regular file without following symlinks."""
    if path.is_symlink():
        raise ValueError(f"L'artefatto non può essere un collegamento simbolico: {path}")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError(f"Impossibile aprire l'artefatto {path}: {exc}") from exc
    try:
        before = os.fstat(descriptor)
        try:
            current = path.lstat()
        except OSError as exc:
            raise ValueError(f"Artefatto sostituito prima della verifica: {path}") from exc
        stable_fields = (
            "st_mode",
            "st_dev",
            "st_ino",
            "st_nlink",
            "st_size",
            "st_mtime_ns",
        )
        if os.name != "nt":
            stable_fields += ("st_ctime_ns",)
        if (
            not stat.S_ISREG(before.st_mode)
            or not stat.S_ISREG(current.st_mode)
            or before.st_nlink != 1
            or current.st_nlink != 1
            or (before.st_dev, before.st_ino) != (current.st_dev, current.st_ino)
            or any(
                getattr(before, field) != getattr(current, field)
                for field in stable_fields
            )
        ):
            raise ValueError(f"Artefatto non regolare o sostituito: {path}")
        digest = hashlib.sha256()
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        after = os.fstat(descriptor)
        try:
            latest = path.lstat()
        except OSError as exc:
            raise ValueError(f"Artefatto sostituito durante la verifica: {path}") from exc
        if (
            not stat.S_ISREG(after.st_mode)
            or not stat.S_ISREG(latest.st_mode)
            or after.st_nlink != 1
            or latest.st_nlink != 1
            or (after.st_dev, after.st_ino) != (latest.st_dev, latest.st_ino)
            or any(
                getattr(before, field) != getattr(after, field)
                for field in stable_fields
            )
            or any(
                getattr(current, field) != getattr(latest, field)
                for field in stable_fields
            )
        ):
            raise ValueError(f"Artefatto modificato durante la verifica: {path}")
        return digest.hexdigest()
    finally:
        os.close(descriptor)


def validate_qa_report(
    report: dict,
    *,
    manifest: dict,
    model: dict,
    revision: int,
    render_evidence_sha256: str,
    render_result: dict,
) -> None:
    if (
        report.get("report_schema") != QA_REPORT_SCHEMA
        or report.get("status") != "pass"
        or report.get("revision") != revision
        or report.get("workflow_state") != "qa"
        or report.get("render_fingerprint") != model.get("render_fingerprint")
        or report.get("proof_browser") != model.get("proof", {}).get("browser")
        or report.get("render_evidence_sha256") != render_evidence_sha256
    ):
        raise ValueError(
            "Il qa-report non è pass o non è legato a stato, revisione, fingerprint e browser correnti"
        )
    checks = report.get("checks")
    allowed_checks = QA_REQUIRED_CHECKS | QA_ADVISORY_CHECKS
    if (
        not isinstance(checks, dict)
        or not QA_REQUIRED_CHECKS.issubset(checks)
        or not set(checks).issubset(allowed_checks)
        or any(checks.get(key) is not True for key in QA_REQUIRED_CHECKS)
        or any(key in checks and not isinstance(checks[key], bool) for key in QA_ADVISORY_CHECKS)
    ):
        missing = sorted(QA_REQUIRED_CHECKS - set(checks or {}))
        suffix = f"; mancanti: {', '.join(missing)}" if missing else ""
        raise ValueError(f"Il qa-report non supera tutti i controlli obbligatori{suffix}")

    known_slide_ids = {
        slide.get("id") for slide in model.get("slides", []) if isinstance(slide, dict)
    }
    sample_ids = report.get("human_sample_slide_ids", [])
    flagged_ids = report.get("flagged_slide_ids", [])
    if (
        not isinstance(sample_ids, list)
        or len(sample_ids) != len(set(sample_ids))
        or any(not isinstance(value, str) or value not in known_slide_ids for value in sample_ids)
        or not isinstance(flagged_ids, list)
        or len(flagged_ids) != len(set(flagged_ids))
        or any(not isinstance(value, str) or value not in known_slide_ids for value in flagged_ids)
    ):
        raise ValueError("Il campione umano del qa-report non contiene ID slide validi")

    expected = expected_output_kinds(manifest)
    report_artifacts = validated_artifact_records(
        report.get("artifacts"),
        field="qa-report.artifacts",
        expected=expected,
        slide_count=len(model.get("slides", [])),
    )
    render_artifacts = validated_artifact_records(
        render_result.get("artifact_sha256"),
        field="render-result.artifact_sha256",
        expected=expected,
        slide_count=len(model.get("slides", [])),
    )
    if report.get("artifacts") != render_result.get("artifact_sha256"):
        raise ValueError(
            "Il qa-report non attesta esattamente gli stessi artefatti del render-result"
        )
    if report_artifacts != render_artifacts:
        raise ValueError(
            "Gli artefatti QA non coincidono con quelli verificati durante il render"
        )


def advance_workflow(
    manifest_path: Path,
    *,
    session_dir_path: Path,
    expected_state: str,
    expected_revision: int,
    target: str,
    render_result_path: Path | None = None,
    qa_report_path: Path | None = None,
) -> dict:
    manifest_input = absolute_input_path(manifest_path)
    reject_symlink_path(manifest_input, field="Il manifest")
    session_dir_input = absolute_input_path(session_dir_path)
    reject_symlink_path(session_dir_input, field="La cartella di sessione")
    if not session_dir_input.is_dir():
        raise ValueError(
            f"La cartella di sessione non esiste: {session_dir_input}"
        )
    render_result_input = None
    if render_result_path is not None:
        render_result_input = absolute_input_path(render_result_path)
        reject_symlink_path(render_result_input, field="Il render-result")
    qa_report_input = None
    if qa_report_path is not None:
        qa_report_input = absolute_input_path(qa_report_path)
        reject_symlink_path(qa_report_input, field="Il qa-report")
    manifest_path = manifest_input.resolve()
    session_dir = session_dir_input.resolve()
    lock_path = manifest_path.with_name(f".{manifest_path.name}.review.lock")
    transaction_lock_path = session_dir / ".review-transaction.lock"
    with InterprocessLock(lock_path), InterprocessLock(transaction_lock_path):
        state = read_private_json(session_dir / "session-state.json")
        validate_state_manifest(state, manifest_path)
        last_feedback_id = state.get("last_feedback_id")
        applied_feedback_id = state.get("applied_feedback_id")
        if last_feedback_id and last_feedback_id != applied_feedback_id:
            raise ValueError(
                "La transizione è bloccata: un feedback durevole attende ancora di essere applicato"
            )
        manifest = read_json_object(manifest_path, label="Manifest")
        if manifest.get("schema_version") != "1.4":
            raise ValueError("La CLI avanza soltanto manifest schema 1.4")
        revision = validated_revision(manifest)
        current = manifest.get("workflow_state")
        if current != expected_state:
            raise ValueError(
                f"workflow_state corrente {current!r} non coincide con --expected-state {expected_state!r}"
            )
        if revision != expected_revision:
            raise ValueError(
                f"revision corrente {revision} non coincide con --expected-revision {expected_revision}"
            )
        validate_canonical_workflow_transition(current, target)
        receipts = validate_workflow_receipts(
            manifest.get("workflow_receipts", []),
            current_state=current,
            require_complete=True,
        )
        require_applied_review_binding(
            state,
            manifest,
            revision=revision,
            receipts=receipts,
        )
        model = manifest_model(manifest_path, manifest=manifest)
        evidence: dict

        if render_result_path is not None and target not in {"qa", "consegnato"}:
            raise ValueError(
                "--render-result è consentito soltanto per rendering -> qa o qa -> consegnato"
            )
        if qa_report_path is not None and target != "consegnato":
            raise ValueError("--qa-report è consentito soltanto per qa -> consegnato")

        if current == "bozza":
            require_review_approval(manifest, stage="profile_text", revision=revision)
            evidence = {"kind": "profile_text_approval", "review": manifest["review"]}
        elif current == "testi_approvati":
            require_no_pending_comments(manifest)
            require_review_approval(manifest, stage="visual_proof", revision=revision)
            require_current_visual_proof(model)
            evidence = {
                "kind": "visual_proof_approval",
                "review": manifest["review"],
                "proof": manifest.get("proof"),
            }
        elif current == "prova_visuale_approvata":
            require_no_pending_comments(manifest)
            require_review_approval(manifest, stage="visual_proof", revision=revision)
            require_current_visual_proof(model)
            expected_output_kinds(manifest)
            evidence = {
                "kind": "production_start",
                "proof": manifest.get("proof"),
                "production": manifest.get("production"),
            }
        elif current == "rendering":
            require_no_pending_comments(manifest)
            require_review_approval(manifest, stage="visual_proof", revision=revision)
            require_current_visual_proof(model)
            if render_result_path is None:
                raise ValueError("rendering -> qa richiede --render-result")
            result = read_json_object(render_result_input, label="render-result")
            validate_render_result(result, manifest=manifest, model=model, revision=revision)
            evidence = result
        elif current == "qa":
            require_no_pending_comments(manifest)
            require_review_approval(manifest, stage="visual_proof", revision=revision)
            require_current_visual_proof(model)
            if qa_report_path is None:
                raise ValueError("qa -> consegnato richiede --qa-report")
            if render_result_path is None:
                raise ValueError("qa -> consegnato richiede anche --render-result")
            if not receipts or receipts[-1]["from"] != "rendering":
                raise ValueError(
                    "qa -> consegnato richiede la ricevuta durevole rendering -> qa"
                )
            report = read_json_object(qa_report_input, label="qa-report")
            render_result = read_json_object(render_result_input, label="render-result")
            if sha256_json(render_result) != receipts[-1]["evidence_sha256"]:
                raise ValueError(
                    "Il render-result non coincide con l'evidenza durevole rendering -> qa"
                )
            validate_render_result(
                render_result, manifest=manifest, model=model, revision=revision
            )
            validate_qa_report(
                report,
                manifest=manifest,
                model=model,
                revision=revision,
                render_evidence_sha256=receipts[-1]["evidence_sha256"],
                render_result=render_result,
            )
            evidence = report

        updated = dict(manifest)
        updated["workflow_state"] = target
        receipts.append(
            {
                "from": current,
                "to": target,
                "revision": revision,
                "render_fingerprint": model["render_fingerprint"],
                "evidence_sha256": sha256_json(evidence),
                "advanced_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        updated["workflow_receipts"] = receipts
        atomic_write_json(manifest_path, updated, private_parent=False)
        return {
            "status": "advanced",
            "manifest": str(manifest_path),
            "revision": revision,
            "from": current,
            "to": target,
            "render_fingerprint": model.get("render_fingerprint"),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--session-dir", type=Path, required=True)
    parser.add_argument(
        "--expected-state", required=True, choices=CANONICAL_WORKFLOW_STATES
    )
    parser.add_argument("--expected-revision", required=True, type=int)
    parser.add_argument("--to", required=True, choices=CANONICAL_WORKFLOW_STATES)
    parser.add_argument("--render-result", type=Path)
    parser.add_argument("--qa-report", type=Path)
    args = parser.parse_args()
    try:
        result = advance_workflow(
            args.manifest,
            session_dir_path=args.session_dir,
            expected_state=args.expected_state,
            expected_revision=args.expected_revision,
            target=args.to,
            render_result_path=args.render_result,
            qa_report_path=args.qa_report,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (LockUnavailableError, OSError, TypeError, ValueError) as exc:
        print(
            json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
