FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MPLBACKEND=Agg \
    MPLCONFIGDIR=/tmp/matplotlib

RUN groupadd --system app && useradd --system --gid app --home-dir /app --no-create-home app

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY --chown=app:app . .
# collectstatic only needs a key to import settings; this one is discarded.
RUN DJANGO_SECRET_KEY=collectstatic-only python manage.py collectstatic --noinput -v 0

USER app
EXPOSE 8000
CMD ["gunicorn", "incentive_site.wsgi", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "30", "--access-logfile", "-"]
