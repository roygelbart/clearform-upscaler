# Changelog

## 2026-02-21
- Added job-based processing with progress/status UI and ZIP download flow.
- Enforced minimum 4x upscale and minimum 20MB target size with robust size targeting.
- Added AI upscaler adapter (OpenCV FSRCNN x4) as default unattended engine.
- Kept Topaz/Gigapixel adapter scaffold; if Topaz CLI is unavailable it now falls back to AI adapter.
- Preserved EXIF orientation and metadata where possible.
- Added TSV report with source/output dimensions, size, quality, and notes.
- Added production readiness artifacts: pinned requirements, .env.example, smoke-test script, and basic tests.
