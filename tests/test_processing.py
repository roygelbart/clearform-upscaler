import io
import os
from pathlib import Path

from PIL import Image

from upscale.adapters import PillowAdapter
from upscale.processing import process_image, safe_name, validate_settings


def _make_jpeg(path: Path, size=(64, 64), color=(120, 120, 120)) -> None:
    img = Image.new("RGB", size, color)
    img.save(path, format="JPEG", quality=90)


def test_safe_name():
    assert safe_name("../bad/name.jpg") == "name"
    assert safe_name("   ") == "image"


def test_validate_settings_rejects_low_values():
    try:
        validate_settings(3.0, 10.0, 4.0, 20.0, 100.0)
    except ValueError:
        pass
    else:
        raise AssertionError("Expected ValueError")


def test_process_image_ok(tmp_path: Path):
    img_path = tmp_path / "sample.jpg"
    _make_jpeg(img_path)

    adapter = PillowAdapter()
    result = process_image(
        path=str(img_path),
        source_name="sample.jpg",
        output_name="sample_upscaled.jpg",
        adapter=adapter,
        scale=4.0,
        target_mb=0.1,
        max_size_passes=3,
        max_output_pixels=4096 * 4096,
    )

    assert result.output_bytes is not None
    assert result.report.status in {"ok", "target_not_met"}
    assert result.report.out_w is not None


def test_process_image_invalid(tmp_path: Path):
    bad_path = tmp_path / "bad.txt"
    bad_path.write_text("not an image")

    adapter = PillowAdapter()
    result = process_image(
        path=str(bad_path),
        source_name="bad.txt",
        output_name="bad_upscaled.jpg",
        adapter=adapter,
        scale=4.0,
        target_mb=0.1,
        max_size_passes=1,
        max_output_pixels=1024 * 1024,
    )

    assert result.output_bytes is None
    assert result.report.status == "failed_invalid"
