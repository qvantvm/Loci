"""Best-effort PDF parsing with PyMuPDF.

PDFs vary widely. This parser preserves extracted page text exactly as PyMuPDF
returns it and marks figure/equation detections as heuristic metadata rather
than silently treating them as authoritative.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from loci.models.schemas import EquationCandidate, FigureCandidate, ParsedDocument


class PDFService:
    """Parse PDF text, image blocks, crops, captions, and obvious equations."""

    def __init__(self, crops_dir: str | Path) -> None:
        self.crops_dir = Path(crops_dir)
        self.crops_dir.mkdir(parents=True, exist_ok=True)

    def parse(self, path: str | Path) -> ParsedDocument:
        try:
            import fitz  # type: ignore
        except Exception as exc:  # pragma: no cover - environment-dependent
            raise RuntimeError("PDF ingestion requires PyMuPDF (`pip install PyMuPDF`).") from exc

        pdf_path = Path(path)
        doc = fitz.open(pdf_path)
        page_texts: list[str] = []
        page_offsets: list[tuple[int, int, int]] = []
        figures: list[FigureCandidate] = []
        equations: list[EquationCandidate] = []
        cursor = 0

        for page_index, page in enumerate(doc, start=1):
            page_text = page.get_text("text")
            blocks = page.get_text("dict").get("blocks", [])
            header = f"\n\n[Page {page_index}]\n"
            start = cursor + len(header)
            page_texts.append(header + page_text)
            cursor += len(header) + len(page_text)
            page_offsets.append((page_index, start, cursor))

            equations.extend(self._detect_equations(page_text, page_index, start, blocks))
            figures.extend(self._extract_figures(page, pdf_path.stem, page_index, blocks))

        raw_text = "".join(page_texts).strip()
        title = doc.metadata.get("title") or pdf_path.stem
        return ParsedDocument(
            raw_text=raw_text,
            title=title,
            figures=figures,
            equations=equations,
            metadata={"page_count": doc.page_count, "page_offsets": page_offsets, "parser": "pymupdf"},
        )

    def _extract_figures(self, page: Any, stem: str, page_number: int, blocks: list[dict[str, Any]]) -> list[FigureCandidate]:
        figures: list[FigureCandidate] = []
        image_index = 0
        for block_index, block in enumerate(blocks):
            if block.get("type") != 1:
                continue
            bbox_tuple = tuple(float(v) for v in block.get("bbox", (0, 0, 0, 0)))
            rect = page.rect if not any(bbox_tuple) else bbox_tuple
            crop_path = self.crops_dir / f"{stem}_p{page_number}_{image_index}.png"
            try:
                pix = page.get_pixmap(clip=fitz_rect(page, rect), dpi=160)
                pix.save(crop_path)
            except Exception:
                pix = page.get_pixmap(dpi=120)
                pix.save(crop_path)
            figures.append(
                FigureCandidate(
                    page_number=page_number,
                    bbox=bbox_tuple,  # type: ignore[arg-type]
                    crop_path=str(crop_path),
                    caption=self._caption_near(page.get_text("text"), image_index),
                    confidence=0.55,
                    metadata={
                        "page_number": page_number,
                        "block_index": block_index,
                        "order_key": [page_number, block_index, bbox_tuple[1], bbox_tuple[0]],
                        "source": "pdf",
                    },
                )
            )
            image_index += 1
        return figures

    def _caption_near(self, page_text: str, image_index: int) -> str | None:
        captions = [line.strip() for line in page_text.splitlines() if re.match(r"^(Figure|Fig\.)\s+\d+", line.strip(), re.I)]
        return captions[min(image_index, len(captions) - 1)] if captions else None

    def _detect_equations(
        self,
        page_text: str,
        page_number: int,
        page_char_start: int,
        blocks: list[dict[str, Any]],
    ) -> list[EquationCandidate]:
        candidates: list[EquationCandidate] = []
        search_from = 0
        for block_index, block in enumerate(blocks):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                stripped = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
                if not stripped:
                    continue
                char_index = page_text.find(stripped, search_from)
                if char_index >= 0:
                    search_from = char_index + len(stripped)
                bbox_tuple = tuple(float(v) for v in line.get("bbox", block.get("bbox", (0, 0, 0, 0))))
                candidate = self._equation_candidate(
                    stripped,
                    page_number,
                    bbox_tuple,  # type: ignore[arg-type]
                    block_index,
                    page_char_start + char_index if char_index >= 0 else None,
                )
                if candidate:
                    candidates.append(candidate)
        if candidates:
            return candidates

        for line in page_text.splitlines():
            stripped = line.strip()
            if not stripped or len(stripped) > 180:
                continue
            candidate = self._equation_candidate(stripped, page_number, None, len(candidates), None)
            if candidate:
                candidates.append(candidate)
        return candidates

    def _equation_candidate(
        self,
        text: str,
        page_number: int,
        bbox: tuple[float, float, float, float] | None,
        block_index: int,
        source_char_start: int | None,
    ) -> EquationCandidate | None:
        if len(text) > 180:
            return None
        mathy = bool(re.search(r"[=∑∫√≤≥≈±]|\\frac|\\sum|\\int", text))
        has_symbols = len(re.findall(r"[+\-*/^=()]", text)) >= 2
        if not (mathy and has_symbols):
            return None
        metadata: dict[str, Any] = {
            "page_number": page_number,
            "block_index": block_index,
            "source": "pdf",
        }
        if source_char_start is not None:
            metadata["source_char_start"] = source_char_start
            metadata["source_char_end"] = source_char_start + len(text)
        if bbox is not None:
            metadata["order_key"] = [page_number, block_index, bbox[1], bbox[0]]
        return EquationCandidate(
            page_number=page_number,
            bbox=bbox,
            source_text=text,
            mathjax=text.replace("≤", r"\le ").replace("≥", r"\ge ").replace("≈", r"\approx "),
            confidence=0.45,
            metadata=metadata,
        )


def fitz_rect(page: Any, rect_or_tuple: Any) -> Any:
    """Build a fitz.Rect without importing fitz at module import time."""

    import fitz  # type: ignore

    if hasattr(rect_or_tuple, "x0"):
        return rect_or_tuple
    return fitz.Rect(*rect_or_tuple)
