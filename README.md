---
title: Arabic OCR Searchable PDF
emoji: 📄
colorFrom: indigo
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
---

# Arabic OCR · Searchable PDF

Upload a scanned PDF → each page is OCR'd with **dots.ocr** → get back a fully
**searchable & selectable** PDF (original scan + an invisible text layer).
Arabic renders RTL, English/Latin renders LTR, so copy/select works for both.

## Deploy on Hugging Face Spaces

1. Create a new **Space** → SDK: **Docker** → push this repo to it.
2. In **Settings → Variables and secrets**, add a **secret**:
   - `DOTS_URL` = your dots.ocr endpoint, e.g. `https://<pod>-8000.proxy.runpod.net/v1`
   - (optional) `OCR_WORKERS` = `2`
3. The Space builds the `Dockerfile` and serves on port `7860` automatically.

> The app requires `DOTS_URL` at startup — without it the container exits.
> Your dots.ocr GPU backend (e.g. on RunPod) must be running for OCR to work.

## Run locally

```bash
pip install -r requirements.txt
# create .env with:  DOTS_URL=https://<pod>-8000.proxy.runpod.net/v1
uvicorn main:app --reload
```

## Notes

- Generated PDFs in `outputs/` are ephemeral (wiped on restart) — download promptly.
- Free CPU Spaces sleep after inactivity and wake on the next visit.
