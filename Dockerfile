
FROM --platform=$BUILDPLATFORM tonistiigi/xx:1.6.1 AS xx

FROM --platform=$BUILDPLATFORM golang:1.24-alpine AS go-base
WORKDIR /app
COPY --from=xx / /
RUN apk add --no-cache git

# Rmapi build
FROM --platform=$BUILDPLATFORM go-base AS rmapi-source
ARG RMAPI_VERSION=0.0.30
RUN git clone --branch v${RMAPI_VERSION} https://github.com/ddvk/rmapi .

FROM --platform=$BUILDPLATFORM go-base AS rmapi-builder

COPY --from=rmapi-source /app/go.mod /app/go.sum ./
RUN go mod download

COPY --from=rmapi-source /app .
ARG TARGETPLATFORM
RUN --mount=type=cache,target=/root/.cache \
    CGO_ENABLED=0 xx-go build -ldflags='-w -s' -trimpath

FROM python:3.13-alpine AS ephemeris

RUN apk add --no-cache \
      freetype libjpeg-turbo libpng poppler-utils py3-cairosvg

WORKDIR /app

COPY fonts /app/fonts
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY assets/cover.svg /app/assets/cover.svg
COPY ephemeris /app/ephemeris
COPY ephemeris.py .

CMD ["python", "ephemeris.py"]

# Ephemeris with rmapi
FROM ephemeris AS ephemeris-rmapi
COPY --from=rmapi-builder /app/rmapi /usr/local/bin/
