FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    gdal-bin \
    libgdal-dev \
    libgeos-dev \
    libproj-dev \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt

COPY . .

# Collect static files for WhiteNoise. SECRET_KEY is a throwaway so settings load without .env.
RUN SECRET_KEY=build-only python manage.py collectstatic --noinput

EXPOSE 8000

# Production default; docker-compose.yml overrides this with runserver for local development.
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]
