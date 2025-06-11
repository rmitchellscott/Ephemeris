FROM python:3.13-alpine

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
