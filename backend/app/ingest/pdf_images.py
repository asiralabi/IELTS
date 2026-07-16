"""Extract raster images from a Cambridge IELTS PDF into the assets dir.

The parser uses these to attach visuals (maps, diagrams, charts) to the
question payload. We filter aggressively so boilerplate (logos, page-header
icons) does not leak into practice sets:

- Reject images below ``min_dim`` on either side (icons, bullet marks).
- Reject any xref that appears on more than ``max_reuse`` pages across the
  whole PDF — those are template assets, not question figures.

Images are rendered via ``page.get_pixmap(clip=bbox)`` rather than
``doc.extract_image()`` so that page rotation and per-image CTM are honoured
— many Cambridge pages have ``/Rotate 180`` and raw bytes come out upside
down otherwise.

Returned URLs are relative paths under ``/assets/<book_id>/`` so the FastAPI
StaticFiles mount at ``/assets`` can serve them directly.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fitz


@dataclass
class ExtractedImage:
    page: int
    url: str
    path: Path
    width: int
    height: int

    def to_visual(self, alt: str) -> dict[str, Any]:
        return {"kind": "image", "url": self.url, "alt": alt}


def _xref_page_counts(doc: fitz.Document) -> Counter[int]:
    counts: Counter[int] = Counter()
    for page in doc:
        seen_on_page: set[int] = set()
        for info in page.get_images(full=True):
            xref = info[0]
            if xref in seen_on_page:
                continue
            seen_on_page.add(xref)
            counts[xref] += 1
    return counts


def extract_book_images(
    pdf_path: Path,
    out_dir: Path,
    url_prefix: str,
    min_dim: int = 100,
    max_reuse: int = 3,
    render_dpi: int = 200,
) -> dict[int, list[ExtractedImage]]:
    """Extract question-figure images from a PDF into ``out_dir``.

    Returns a ``{page_number: [ExtractedImage, ...]}`` map, page numbers 1-based.
    ``url_prefix`` is prepended to each saved filename (e.g. ``/assets/cambridge-18``).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    result: dict[int, list[ExtractedImage]] = {}

    with fitz.open(pdf_path) as doc:
        xref_counts = _xref_page_counts(doc)
        saved_xrefs: dict[int, ExtractedImage] = {}

        for page in doc:
            page_num = page.number + 1  # fitz is 0-based
            page_images: list[ExtractedImage] = []
            seen_on_page: set[int] = set()

            for idx, info in enumerate(page.get_images(full=True)):
                xref = info[0]
                if xref in seen_on_page:
                    continue
                seen_on_page.add(xref)

                if xref_counts[xref] > max_reuse:
                    continue

                if xref in saved_xrefs:
                    # Reuse previously extracted asset but tag it to this page.
                    prev = saved_xrefs[xref]
                    page_images.append(
                        ExtractedImage(
                            page=page_num,
                            url=prev.url,
                            path=prev.path,
                            width=prev.width,
                            height=prev.height,
                        )
                    )
                    continue

                try:
                    meta = doc.extract_image(xref)
                except Exception:
                    continue

                orig_w = int(meta.get("width") or 0)
                orig_h = int(meta.get("height") or 0)
                if orig_w < min_dim or orig_h < min_dim:
                    continue

                filename = f"p{page_num:03d}_i{idx}.png"
                path = out_dir / filename

                bbox = None
                try:
                    bbox = page.get_image_bbox(info)
                except Exception:
                    bbox = None

                rendered = False
                if bbox is not None and not bbox.is_empty and not bbox.is_infinite:
                    try:
                        pix = page.get_pixmap(clip=bbox, dpi=render_dpi, alpha=False)
                        pix.save(path)
                        width, height = pix.width, pix.height
                        rendered = True
                    except Exception:
                        rendered = False

                if not rendered:
                    # Fallback to raw bytes when the bbox is missing/degenerate.
                    ext = str(meta.get("ext") or "png").lower()
                    filename = f"p{page_num:03d}_i{idx}.{ext}"
                    path = out_dir / filename
                    path.write_bytes(meta["image"])
                    width, height = orig_w, orig_h

                url = f"{url_prefix.rstrip('/')}/{filename}"
                extracted = ExtractedImage(
                    page=page_num,
                    url=url,
                    path=path,
                    width=width,
                    height=height,
                )
                saved_xrefs[xref] = extracted
                page_images.append(extracted)

            if page_images:
                result[page_num] = page_images

    return result
