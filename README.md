# Arabic OCR · Searchable PDF

Upload a scanned PDF → each page is OCR'd with **dots.ocr** → get back a fully
**searchable & selectable** PDF (original scan + an invisible text layer).
Arabic renders RTL, English/Latin renders LTR, so copy/select works for both.

## Run locally

```bash
pip install -r requirements.txt
# create a .env file with:
#   DOTS_URL=https://<pod>-8000.proxy.runpod.net/v1
uvicorn main:app --reload
```

Open http://localhost:8000

## Deploy (Koyeb, free)

1. Push this repo to GitHub.
2. Koyeb → **Create Web Service** → connect the GitHub repo, branch `main`.
3. **Builder:** Buildpack (auto-detects Python via `requirements.txt` + `Procfile`).
4. **Exposed port:** `8000`.
5. **Environment variables:**
   - `DOTS_URL` = your dots.ocr endpoint
   - `OCR_WORKERS` = `2`
6. Deploy.

> The dots.ocr GPU backend (e.g. on RunPod) must be running for OCR to work.

## Notes

- Generated PDFs in `outputs/` are ephemeral (wiped on restart) — download promptly.
- `Procfile` defines the start command; `requirements.txt` pins dependencies.
