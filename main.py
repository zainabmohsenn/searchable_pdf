import base64, json, re, tempfile, time, traceback, unicodedata, uuid, os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fpdf import FPDF
from fpdf.enums import TextMode
import fitz
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
dots = OpenAI(base_url=os.environ["DOTS_URL"], api_key="x")

app = FastAPI(title="Arabic OCR - dots.ocr")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

BASE = Path(__file__).resolve().parent
OUT = BASE / "outputs"; OUT.mkdir(exist_ok=True)
FONT = BASE / "fonts" / "Amiri-Regular.ttf"
INDEX = BASE / "index.html"
DPI = max(72, int(os.environ.get("OCR_DPI", "200")))          # render resolution (lower = less GPU memory + faster)
OCR_WORKERS = max(1, int(os.environ.get("OCR_WORKERS", "2")))  # parallel OCR calls (too many => OCR GPU out-of-memory)
JPEG_QUALITY = max(40, min(100, int(os.environ.get("JPEG_QUALITY", "85"))))  # page image encoding

PROMPT = """Please output the layout information from the image, including each layout element's bbox, its category, and the corresponding text content within the bbox.
1. Bbox format: [x1, y1, x2, y2]
2. Layout Categories: ['Caption','Footnote','Formula','List-item','Page-footer','Page-header','Picture','Section-header','Table','Text','Title'].
3. Output original text, no translation, in reading order.
4. Output a single JSON object."""

def clean(t):
    t = unicodedata.normalize("NFKC", str(t)).replace("ـ", "")
    return re.sub(r"\s+", " ", t).strip()

# Arabic (+ presentation forms) letter ranges
AR_RE = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")

def script_of(t):
    """Return 'ar' if the region is predominantly Arabic, else 'en' (Latin/other)."""
    ar = len(AR_RE.findall(t))
    la = sum(1 for c in t if "a" <= c.lower() <= "z")
    return "ar" if ar > la else "en"

def parse_regions(raw):
    try:
        d = json.loads(raw)
        return d if isinstance(d, list) else (d.get("elements") or d.get("layout") or [d])
    except Exception:
        out = []
        for o in re.findall(r'\{[^{}]*"bbox"\s*:\s*\[[^\]]*\][^{}]*\}', raw):
            b = re.search(r'"bbox"\s*:\s*\[([^\]]*)\]', o)
            t = re.search(r'"text"\s*:\s*"((?:[^"\\]|\\.)*)"', o)
            if b:
                try:
                    n = [float(x) for x in b.group(1).split(",")]
                    if len(n) == 4:
                        out.append({"bbox": n, "text": t.group(1) if t else ""})
                except Exception: pass
        return out

def ocr_page(png_bytes):
    b64 = base64.b64encode(png_bytes).decode()
    resp = dots.chat.completions.create(
        model="model",
        messages=[{"role":"user","content":[
            {"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}},
            {"type":"text","text":PROMPT},
        ]}],
        temperature=0.0, max_tokens=16000,
    )
    return parse_regions(resp.choices[0].message.content)

def build_pdf(pages, output):
    pdf = FPDF(unit="pt")
    pdf.set_text_shaping(True)
    pdf.add_font("Amiri", "", str(FONT))
    # Latin/other-script font: used for English regions AND as glyph fallback for Arabic ones.
    # Prefer the bundled DejaVuSans (works on Linux/Render); fall back to local Windows fonts.
    latin = "Amiri"
    for fb in (BASE / "fonts" / "DejaVuSans.ttf",
               Path(r"C:\Windows\Fonts\arial.ttf"),
               Path(r"C:\Windows\Fonts\tahoma.ttf")):
        if fb.exists():
            pdf.add_font("Latin", "", str(fb))
            pdf.set_fallback_fonts(["Latin"])
            latin = "Latin"
            break
    s = 72.0 / DPI  # convert image pixels -> PDF points
    attempted = embedded = 0
    for png, regions, (W, H) in pages:
        pw, ph = W * s, H * s
        pdf.add_page(format=(pw, ph))
        pdf.set_auto_page_break(False)
        # 1) draw the scan as the visible background
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp.write(png); tmp.flush(); tmp.close()
            pdf.image(tmp.name, x=0, y=0, w=pw, h=ph)
            Path(tmp.name).unlink(missing_ok=True)
        # 2) overlay an invisible text layer -> selectable & searchable
        pdf.text_mode = TextMode.INVISIBLE
        fallback_y = 2.0  # cursor for regions whose bbox is missing/unusable
        for r in regions:
            txt = clean(r.get("text", ""))
            if not txt: continue  # only skip when there is genuinely no text
            attempted += 1
            bb = r.get("bbox")
            if bb and len(bb) == 4:
                x1, y1, x2, y2 = [v * s for v in bb]
            else:
                x1 = y1 = x2 = y2 = 0
            # clamp onto the page instead of dropping — every word must stay searchable
            x1 = min(max(x1, 0), pw - 8)
            y1 = min(max(y1, 0), ph - 4)
            x2 = min(max(x2, x1 + 8), pw)
            bh = y2 - y1
            if bh < 4 or bh > ph:  # bbox missing or nonsensical -> stack at a safe fallback spot
                x1, x2 = 2, pw
                y1 = min(fallback_y, ph - 6); fallback_y += 9
                bh = 8
            ar = script_of(txt) == "ar"
            font = "Amiri" if ar else latin
            align = "R" if ar else "L"
            w_avail = max(x2 - x1, 8)
            pdf.set_text_shaping(True, direction="rtl" if ar else "ltr")
            size = min(max(4, bh*0.85), 200)
            pdf.set_font(font, size=size)
            # shrink font so the line fits the box width — otherwise long lines overflow the
            # page and their tail gets clipped away on extraction (whole sentences went missing)
            try:
                sw = pdf.get_string_width(txt)
                if sw > w_avail and sw > 0:
                    size = max(2, size * w_avail / sw * 0.97)
                    pdf.set_font(font, size=size)
            except Exception: pass
            def place():
                pdf.set_xy(x1, y1)
                pdf.cell(w=w_avail, h=bh, text=txt, align=align)
            try:
                place()
                embedded += 1
            except Exception:
                try:  # last resort: unshaped, so the raw characters still embed & remain searchable
                    pdf.set_text_shaping(False)
                    place()
                    pdf.set_text_shaping(True)
                    embedded += 1
                except Exception: pass
    pdf.output(str(output))
    return embedded, attempted

@app.get("/", response_class=HTMLResponse)
async def home():
    return INDEX.read_text(encoding="utf-8")

@app.post("/process")
async def process(file: UploadFile = File(...)):
    content = await file.read()

    def event(d):
        return json.dumps(d, ensure_ascii=False) + "\n"

    def stream():
        t0 = time.time()
        el = lambda: round(time.time() - t0, 1)
        log = lambda msg, level="info": event({"type": "log", "level": level, "message": msg, "elapsed": el()})
        try:
            yield log(f"Received '{file.filename}' ({len(content):,} bytes)")
            doc = fitz.open(stream=content, filetype="pdf")
            total = doc.page_count
            yield log(f"Opened PDF · {total} page{'s' if total != 1 else ''} · rendering at {DPI} DPI · {OCR_WORKERS} OCR workers")
            yield event({"type": "start", "total": total, "elapsed": el()})
            pages, text_out = [], []
            with ThreadPoolExecutor(max_workers=OCR_WORKERS) as ex:
                # render every page (fast, CPU) and fire all OCR calls concurrently
                imgs, futs = [None] * total, {}
                for i, pg in enumerate(doc):
                    pix = pg.get_pixmap(dpi=DPI)
                    img = pix.tobytes("jpeg", jpg_quality=JPEG_QUALITY)
                    imgs[i] = (img, pix.width, pix.height)
                    futs[i] = ex.submit(ocr_page, img)
                yield log(f"Rendered {total} page{'s' if total != 1 else ''}; OCR running {OCR_WORKERS}-way in parallel")
                # collect results IN ORDER so the UI streams pages 1..N sequentially
                for i in range(total):
                    n = i + 1
                    try:
                        regions = futs[i].result()
                    except Exception as e:
                        regions = []
                        yield log(f"Page {n}/{total}: OCR failed — {e}", "error")
                    png, w, h = imgs[i]
                    pages.append((png, regions, (w, h)))
                    lines = [{"text": clean(r.get("text", ""))} for r in regions if clean(r.get("text", ""))]
                    text_out.append({"page": n, "lines": lines})
                    yield log(f"Page {n}/{total}: {len(regions)} region{'s' if len(regions) != 1 else ''} → {len(lines)} line{'s' if len(lines) != 1 else ''}")
                    yield event({"type": "page", "page": n, "total": total, "lines": lines, "elapsed": el()})
            yield event({"type": "status", "message": "Building searchable PDF", "elapsed": el()})
            yield log("Building searchable PDF (image + invisible text layer)")
            out = OUT / f"{uuid.uuid4().hex}_searchable.pdf"
            embedded, attempted = build_pdf(pages, out)
            panel_lines = sum(len(p["lines"]) for p in text_out)
            lvl = "info" if embedded == attempted == panel_lines else "error"
            yield log(f"Text layer: embedded {embedded}/{attempted} regions (panel shows {panel_lines})", lvl)
            yield log(f"Wrote {out.name} ({out.stat().st_size:,} bytes) in {el()}s")
            yield event({"type": "done", "pages": text_out, "pdf_url": f"/download/{out.name}", "file": out.name, "elapsed": el()})
        except Exception as e:
            yield log(f"Fatal: {e}", "error")
            yield event({"type": "error", "message": str(e), "trace": traceback.format_exc(), "elapsed": el()})

    return StreamingResponse(stream(), media_type="application/x-ndjson")

@app.get("/download/{name}")
async def download(name: str):
    p = OUT / name
    if not p.exists(): raise HTTPException(404)
    return FileResponse(str(p), media_type="application/pdf", filename=name)
