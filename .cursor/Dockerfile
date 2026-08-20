FROM python:3.12-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# git and curl are required for repository checkout and general tooling; the
# python:3.12-slim base already provides a working python3 + pip + venv.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Match the Cloud Agent runtime user so checked-out files and the project
# virtualenv are owned by a non-root user.
RUN useradd --create-home --shell /bin/bash ubuntu

USER ubuntu
WORKDIR /home/ubuntu
