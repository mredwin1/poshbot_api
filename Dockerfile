FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive \
    LANG="C.UTF-8" \
    PIPENV_NOSPIN=1 \
    PIP_NO_CACHE_DIR=false \
    PIPENV_HIDE_EMOJIS=1

# Copy only the Pipfile and Pipfile.lock first
COPY Pipfile* ./

# Install dependencies for pycurl then install modules using pipenv
RUN apt update \
    && apt install -y libcurl4-openssl-dev libssl-dev \
    && apt install -y python3-pip \
    && apt clean \
    && rm -rf /var/lib/apt/lists/* \
    && pip install pipenv \
    && pipenv install --system --deploy

# Copy project files
COPY . .