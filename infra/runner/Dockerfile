FROM python:3.12-slim

LABEL com.lasme.runner.version="2"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLBACKEND=Agg

RUN python -m pip install --no-cache-dir \
    matplotlib==3.10.8 \
    numpy==2.4.1 \
    openpyxl==3.1.5 \
    pandas==2.3.3 \
    pillow==12.1.1

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin runner

WORKDIR /workspace
USER runner
