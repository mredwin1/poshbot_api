FROM ubuntu:22.04

# Allow service to handle stops gracefully
STOPSIGNAL SIGQUIT

# Set pip to have cleaner logs and no saved cache
ENV PIP_NO_CACHE_DIR=false \
    PIPENV_HIDE_EMOJIS=1 \
    PIPENV_NOSPIN=1 \
    DEBIAN_FRONTEND=noninteractive

# Copy only the Pipfile and Pipfile.lock first
COPY Pipfile* ./

# Install dependencies for pycurl then install modules using pipenv
RUN apt update \
    && apt install -y libcurl4-openssl-dev libssl-dev \
    && apt install -y python3-pip \
    && apt clean \
    && rm -rf /var/lib/apt/lists/* \
    && pip install pipenv \
    && pipenv install --system --deploy --skip-lock

# Copy the chrome.deb file into the image
COPY ./chrome_clients/chrome.deb /poshbot_api/chrome_clients/

# Install chrome
RUN apt update \
    && apt install -y /poshbot_api/chrome_clients/chrome.deb

# Copy the project files into working directory
COPY . .

# Run web server through custom manager
ENTRYPOINT ["python3", "manage.py"]
CMD ["start"]