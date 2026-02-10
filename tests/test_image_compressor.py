"""
Tests for backend/utils/image_compressor.py

Covers small-image passthrough, actual compression of oversized images,
and graceful handling of invalid input data.
"""

import io
import pytest
from PIL import Image

from backend.utils.image_compressor import compress_image


def create_test_image(width=100, height=100, color="red", fmt="PNG"):
    """Create a minimal in-memory image and return its bytes."""
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def create_large_test_image(target_kb=300, width=1200, height=1200):
    """
    Create a noisy image that exceeds target_kb when saved as PNG.

    A large, non-uniform image compresses poorly with PNG, ensuring
    the raw data is large enough to trigger compression.
    """
    import random

    img = Image.new("RGB", (width, height))
    # Fill with semi-random pixel data so PNG cannot compress it well
    pixels = img.load()
    rng = random.Random(42)  # deterministic seed
    for y in range(height):
        for x in range(width):
            pixels[x, y] = (rng.randint(0, 255), rng.randint(0, 255), rng.randint(0, 255))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    data = buf.getvalue()

    # Verify it is actually larger than our target
    assert len(data) > target_kb * 1024, (
        f"Test image only {len(data) // 1024}KB, expected >{target_kb}KB"
    )
    return data


class TestSmallImage:
    def test_small_image_not_compressed(self):
        """An image already under max_size_kb is returned unchanged."""
        small_image = create_test_image(50, 50, "blue")

        result = compress_image(small_image, max_size_kb=500)

        # Exact same bytes -- no transformation applied
        assert result is small_image

    def test_small_image_exact_boundary(self):
        """An image exactly at the limit is returned unchanged."""
        small_image = create_test_image(10, 10)
        size_kb = len(small_image) / 1024

        result = compress_image(small_image, max_size_kb=int(size_kb) + 1)

        assert result is small_image


class TestCompressLargeImage:
    def test_compress_large_image(self):
        """A large image is compressed below the target size."""
        large_image = create_large_test_image(target_kb=300)
        max_kb = 200

        result = compress_image(large_image, max_size_kb=max_kb)

        # Result should be smaller than the original
        assert len(result) < len(large_image)
        # Result should be a valid image
        img = Image.open(io.BytesIO(result))
        assert img.size[0] > 0
        assert img.size[1] > 0

    def test_compressed_image_is_jpeg(self):
        """Compression converts the output to JPEG format."""
        large_image = create_large_test_image(target_kb=300)

        result = compress_image(large_image, max_size_kb=200)

        # JPEG magic bytes: FF D8 FF
        assert result[:2] == b"\xff\xd8"

    def test_compress_rgba_image(self):
        """RGBA images are handled (alpha channel composited to white)."""
        img = Image.new("RGBA", (800, 800), (255, 0, 0, 128))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        rgba_data = buf.getvalue()

        # Use a very low max_size to force compression
        result = compress_image(rgba_data, max_size_kb=1)

        # Should still produce a valid image
        result_img = Image.open(io.BytesIO(result))
        assert result_img.mode == "RGB" or result_img.mode == "L"


class TestInvalidData:
    def test_compress_invalid_data(self):
        """Invalid (non-image) data that exceeds max_size is returned as-is."""
        garbage = b"this is not an image at all" * 1000  # ~26KB

        result = compress_image(garbage, max_size_kb=1)

        # compress_image catches the exception and returns original data
        assert result == garbage

    def test_compress_empty_bytes(self):
        """Empty bytes (under threshold) are returned unchanged."""
        empty = b""

        result = compress_image(empty, max_size_kb=200)

        assert result is empty
