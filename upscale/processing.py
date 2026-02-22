from __future__ import annotations

import io
import logging
import os
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from PIL import Image, ImageOps, UnidentifiedImageError

from .adapters import UpscaleAdapter

logger = logging.getLogger(__name__)


def safe_name(name: str) -> str:
    base = os.path.basename(name)
    root, _ = os.path.splitext(base)
    cleaned = "".join(c for c in root if c.isalnum() or c in ("-", "_", " ")).strip()
    return cleaned or "image"


@dataclass
class ProcessReport:
    source_name: str
    output_name: str
    status: str
    src_w: Optional[int]
    src_h: Optional[int]
    out_w: Optional[int]
    out_h: Optional[int]
    quality: Optional[int]
    size_mb: Optional[float]
    notes: str

    def as_tsv(self) -> str:
        return "\t".join(
            [
                self.source_name,
                self.output_name,
                self.status,
                str(self.src_w or ""),
                str(self.src_h or ""),
                str(self.out_w or ""),
                str(self.out_h or ""),
                str(self.quality or ""),
                str(self.size_mb or ""),
                self.notes,
            ]
        )


@dataclass
class ProcessResult:
    report: ProcessReport
    output_bytes: Optional[bytes]


def validate_settings(scale: float, target_mb: float, min_scale: float, min_target_mb: float, max_target_mb: float) -> None:
    if scale < min_scale:
        raise ValueError("Scale must be at least the minimum.")
    if target_mb < min_target_mb or target_mb > max_target_mb:
        raise ValueError("Target size must be within the allowed range.")


def _encode_jpeg_target_bytes(
    img: Image.Image,
    target_bytes: int,
    tolerance: float,
    exif_bytes: Optional[bytes],
    icc_profile: Optional[bytes],
) -> Tuple[bytes, int]:
    low, high = 70, 98
    best_data: Optional[bytes] = None
    best_q = 92
    best_gap = float("inf")

    while low <= high:
        q = (low + high) // 2
        buf = io.BytesIO()
        save_kwargs = {
            "format": "JPEG",
            "quality": q,
            "optimize": True,
            "progressive": True,
        }
        if exif_bytes:
            save_kwargs["exif"] = exif_bytes
        if icc_profile:
            save_kwargs["icc_profile"] = icc_profile
        img.save(buf, **save_kwargs)
        data = buf.getvalue()
        size = len(data)

        gap = abs(size - target_bytes)
        if gap < best_gap:
            best_gap = gap
            best_data = data
            best_q = q

        if size < target_bytes * (1 - tolerance):
            low = q + 1
        elif size > target_bytes * (1 + tolerance):
            high = q - 1
        else:
            return data, q

    if best_data is None:
        raise RuntimeError("Failed to encode JPEG.")
    return best_data, best_q


def _load_image(path: str) -> Image.Image:
    with Image.open(path) as img:
        img.verify()
    img = Image.open(path)
    if img.format != "JPEG":
        raise ValueError("Not a JPEG file.")
    return img


def process_image(
    path: str,
    source_name: str,
    output_name: str,
    adapter: UpscaleAdapter,
    scale: float,
    target_mb: float,
    max_size_passes: int,
    max_output_pixels: int,
) -> ProcessResult:
    try:
        img = _load_image(path)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        logger.info("Invalid image %s: %s", source_name, exc)
        return ProcessResult(
            report=ProcessReport(
                source_name=source_name,
                output_name=output_name,
                status="failed_invalid",
                src_w=None,
                src_h=None,
                out_w=None,
                out_h=None,
                quality=None,
                size_mb=None,
                notes="Invalid or unsupported image.",
            ),
            output_bytes=None,
        )

    try:
        exif = img.getexif()
        if 0x0112 in exif:
            exif[0x0112] = 1
        exif_bytes = exif.tobytes() if exif else None
        icc_profile = img.info.get("icc_profile")

        src = ImageOps.exif_transpose(img).convert("RGB")
        src_w, src_h = src.size
    finally:
        img.close()
    target_bytes = int(target_mb * 1024 * 1024)

    best_bytes: Optional[bytes] = None
    best_quality: Optional[int] = None
    best_w: Optional[int] = None
    best_h: Optional[int] = None
    notes = []

    current_scale = scale

    try:
        for _ in range(max_size_passes):
            out = adapter.upscale(src, current_scale)
            out_w, out_h = out.size
            if out_w * out_h > max_output_pixels:
                notes.append("Output exceeded max pixel limit.")
                break

            data, quality = _encode_jpeg_target_bytes(
                out,
                target_bytes=target_bytes,
                tolerance=0.12,
                exif_bytes=exif_bytes,
                icc_profile=icc_profile,
            )

            best_bytes = data
            best_quality = quality
            best_w = out_w
            best_h = out_h

            if len(data) >= target_bytes:
                size_mb = round(len(data) / (1024 * 1024), 2)
                return ProcessResult(
                    report=ProcessReport(
                        source_name=source_name,
                        output_name=output_name,
                        status="ok",
                        src_w=src_w,
                        src_h=src_h,
                        out_w=out_w,
                        out_h=out_h,
                        quality=quality,
                        size_mb=size_mb,
                        notes="OK",
                    ),
                    output_bytes=data,
                )

            current_scale *= 1.15
    except MemoryError:
        return ProcessResult(
            report=ProcessReport(
                source_name=source_name,
                output_name=output_name,
                status="failed_processing",
                src_w=src_w,
                src_h=src_h,
                out_w=None,
                out_h=None,
                quality=None,
                size_mb=None,
                notes="Insufficient memory to process this file.",
            ),
            output_bytes=None,
        )

    if best_bytes is None or best_quality is None or best_w is None or best_h is None:
        return ProcessResult(
        report=ProcessReport(
            source_name=source_name,
            output_name=output_name,
            status="failed_processing",
            src_w=src_w,
            src_h=src_h,
            out_w=None,
            out_h=None,
            quality=None,
            size_mb=None,
            notes="Processing failed.",
        ),
            output_bytes=None,
        )

    size_mb = round(len(best_bytes) / (1024 * 1024), 2)
    notes.append("Upscaled and exported, but minimum target size was not reached.")
    return ProcessResult(
        report=ProcessReport(
            source_name=source_name,
            output_name=output_name,
            status="target_not_met",
            src_w=src_w,
            src_h=src_h,
            out_w=best_w,
            out_h=best_h,
            quality=best_quality,
            size_mb=size_mb,
            notes=" ".join(notes),
        ),
        output_bytes=best_bytes,
    )
