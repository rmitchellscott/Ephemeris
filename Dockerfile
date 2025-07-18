
ARG RMAPI_VERSION=0.0.31

FROM python:3.13-alpine AS ephemeris

RUN apk add --no-cache \
      freetype libjpeg-turbo libpng poppler-utils

WORKDIR /app

COPY fonts /app/fonts
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY assets/cover.svg /app/assets/cover.svg
COPY ephemeris /app/ephemeris
COPY ephemeris.py .

CMD ["python", "ephemeris.py"]

# Rmapi stage
FROM ghcr.io/ddvk/rmapi:v${RMAPI_VERSION} AS rmapi-binary

# Ephemeris with rmapi
FROM ephemeris AS ephemeris-rmapi
COPY --from=rmapi-binary /usr/local/bin/rmapi /usr/local/bin/
