FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends libsndfile1 libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY requirements.txt requirements-ml.txt requirements-optional.txt ./
ARG WITH_ML=false
RUN if [ "$WITH_ML" = "true" ]; then pip install --no-cache-dir -r requirements-ml.txt redis==5.2.1 channels-redis==4.2.1; else pip install --no-cache-dir -r requirements.txt; fi
COPY manage.py ./
COPY satyapan ./satyapan
COPY apps ./apps
COPY scripts ./scripts
RUN useradd -m app && mkdir /data && chown -R app /srv /data
USER app
EXPOSE 8000
# Migration files are generated on first start (commit them once you are happy with the schema).
CMD ["sh", "-c", "python manage.py setup_db && daphne -b 0.0.0.0 -p 8000 satyapan.asgi:application"]
