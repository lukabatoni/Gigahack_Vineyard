# Reproducible environment for the Siret3 vineyard pipeline.
# GDAL/GEOS/PROJ system libs are needed by rasterio, fiona, shapely, pyproj.
FROM python:3.9-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        gdal-bin libgdal-dev libgeos-dev libproj-dev proj-data proj-bin \
        libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Code + trained weights (organizer tiles are mounted at runtime, not baked in).
COPY pipeline/ ./pipeline/
COPY weights/ ./weights/
COPY web/ ./web/
COPY 02_route/ ./02_route/

# Mount tiles read-only, e.g.:
#   docker run --rm -v $PWD/01_tiles:/app/01_tiles -v $PWD/out:/app/pipeline/output \
#     vineyard python pipeline/run_pipeline.py --tag all
CMD ["python", "pipeline/run_pipeline.py", "--help"]
