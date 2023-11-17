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
RUN apt-get update \
    && apt-get install -y libcurl4-openssl-dev libssl-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && pipenv install --system --deploy --skip-lock

# Copy the chrome.deb file into the image
COPY /poshbot_api/chrome_clients/chrome.deb /poshbot_api/chrome_clients/

# Install chrome
RUN apt-get update \
    && apt-get install -y /poshbot_api/chrome_clients/chrome.deb

# Copy the project files into working directory
COPY . .

# Run web server through custom manager
ENTRYPOINT ["python3", "manage.py"]
CMD ["start"]