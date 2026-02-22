# Photo Upscale App

Internal batch JPEG upscaler with progress UI, ZIP export, and TSV report. Designed for batches up to 200 JPEGs with minimum 4x upscale and minimum 20MB output per file.

Default engine is now an AI upscaler (OpenCV FSRCNN x4), with Topaz kept as optional future adapter.

## Features
- Batch upload up to 200 JPEGs
- Enforced minimum 4x upscale and minimum 20MB target size per output
- Progress/status page with summary counts
- Auto Telegram notification when a batch completes
- ZIP output with a `_report.tsv` file containing dimensions, quality, size, and notes
- Preserves EXIF/ICC metadata where possible (orientation normalized)
- AI upscaler engine (FSRCNN x4) for unattended batch runs
- Adapter structure for optional future Topaz/Gigapixel CLI integration

## Quick start (local)
1. Create a virtual environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

2. Configure environment (optional):

```bash
cp .env.example .env
```

3. Run the app:

```bash
python app.py
```

Open `http://127.0.0.1:5050`.

## Production run
Use Gunicorn for production:

```bash
gunicorn -w 2 -b 0.0.0.0:5050 app:app
```

## Configuration
Environment variables (see `.env.example`):
- `MAX_FILES` (default 200)
- `MIN_SCALE` (default 4.0)
- `MIN_TARGET_MB` (default 20)
- `MAX_TARGET_MB` (default 100)
- `MAX_UPLOAD_MB` (default 3000)
- `MAX_IMAGE_PIXELS` / `MAX_OUTPUT_PIXELS` for memory safety
- `UPSCALE_ADAPTER` (`ai`, `pillow`, or `topaz`)
- `AI_MODEL_PATH` (optional local path for FSRCNN_x4.pb; auto-downloads if empty)
- `TOPAZ_CLI_PATH` (path to Topaz CLI binary)
- `NOTIFY_ON_DONE` (`true`/`false`)
- `NOTIFY_CHANNEL` (default `telegram`)
- `NOTIFY_TARGET` (your Telegram user id)

### Engine behavior
- `UPSCALE_ADAPTER=ai` (default): uses FSRCNN x4 AI upscaling (fully automatable)
- `UPSCALE_ADAPTER=pillow`: high-quality Lanczos fallback
- `UPSCALE_ADAPTER=topaz`: reserved for future CLI integration; if CLI is unavailable it falls back to `ai`

## Report format
`_report.tsv` columns:

```
source_name	output_name	status	src_w	src_h	out_w	out_h	quality	size_mb	notes
```

## Smoke test
Start the server, then run:

```bash
scripts/smoke_test.sh
```

It will generate sample JPEGs, upload them, and verify a ZIP response.

## Tests
```bash
python -m pytest
```
