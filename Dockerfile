# Hugging Face Spaces (Docker SDK) — also works on Render / Cloud Run / locally.
FROM python:3.11-slim

# fpdf2 + PyMuPDF need no system libs beyond these for fonts/rendering
RUN apt-get update && apt-get install -y --no-install-recommends \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# HF Spaces run containers as non-root uid 1000 — set up a writable home/app dir
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1

WORKDIR /home/user/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY --chown=user . .

# HF Spaces expects 7860; honor $PORT if the host sets one (Render/Cloud Run)
EXPOSE 7860
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-7860}"]
