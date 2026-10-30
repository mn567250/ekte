# ekte web UI in a container.
#
#   docker build -t ekte .
#   docker run --rm -p 127.0.0.1:8000:8000 -v ekte-data:/data ekte
#
# Always publish to the host's loopback (127.0.0.1:…): the UI has no login and
# is meant for this machine only. Inside the container it has to listen on all
# of the container's interfaces for the published port to reach it; that is
# what EKTE_CONTAINER=1 allows (ekte refuses a non-loopback bind otherwise).
# See docs/DOCKER.md.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    EKTE_CONTAINER=1 \
    EKTE_HOST=0.0.0.0 \
    EKTE_PORT=8000 \
    EKTE_DATA_DIR=/data

WORKDIR /src
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY ekte ./ekte
RUN pip install '.[web]' && rm -rf /src

RUN useradd --create-home --uid 10001 ekte \
    && mkdir -p /data && chown ekte:ekte /data && chmod 700 /data
USER ekte
WORKDIR /home/ekte
VOLUME ["/data"]
EXPOSE 8000

CMD ["ekte", "serve", "--no-open"]
