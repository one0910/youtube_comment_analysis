FROM node:22-alpine AS frontend-builder

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run css:build


FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

RUN addgroup --system tubesense \
    && adduser --system --ingroup tubesense tubesense

COPY --chown=tubesense:tubesense . .
COPY --from=frontend-builder --chown=tubesense:tubesense /app/static/css/app.css /app/static/css/app.css
RUN mkdir -p /app/staticfiles \
    && chown tubesense:tubesense /app/staticfiles

USER tubesense

EXPOSE 8000

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "120"]
