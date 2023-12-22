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

# Install Octo dependencies
RUN apt update && apt install -y \
	apt-transport-https ca-certificates curl jq \
    gnupg unzip libgles2 libegl1 xvfb --no-install-recommends \
	&& curl -sSL https://dl.google.com/linux/linux_signing_key.pub | apt-key add - \
	&& echo "deb https://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list \
	&& apt update && apt install -y \
	fontconfig fonts-ipafont-gothic fonts-kacst fonts-noto \
	fonts-symbola fonts-thai-tlwg fonts-wqy-zenhei connect-proxy \
    dnsutils fonts-freefont-ttf iproute2 iptables iputils-ping \
    net-tools openvpn procps socat ssh sshpass sudo tcpdump \
    telnet traceroute tzdata vim-nox

# Install chrome
RUN curl https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb --output /tmp/chrome.deb
RUN apt install -y /tmp/chrome.deb


RUN apt update \
    && apt install -y libgl1 libglib2.0-0  zip

# Create
RUN mkdir -p /home/octo/browser

# Create new user
RUN groupadd -r octo && \
    useradd -r -g octo -s /bin/bash -m -G audio,video,sudo -p $(echo 1 | openssl passwd -1 -stdin) octo && \
    mkdir -p /home/octo/ && \
    chown -R octo:octo /home/octo

# Create sudoers.d directory and add sudo permissions for the octo user
RUN mkdir -p /etc/sudoers.d && \
    echo 'octo ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/octo && \
    chmod 0440 /etc/sudoers.d/octo

# Set the working directory to /home/octo
WORKDIR /home/octo

#sudo octo
RUN usermod -a -G sudo octo

# Install Octo browser
RUN curl -o /tmp/octo-browser.tar.gz https://binaries.octobrowser.net/releases/installer/OctoBrowser.linux.tar.gz

# Unzip Octo browser
RUN tar -xzf /tmp/octo-browser.tar.gz -C /home/octo/browser

# Copy project files
COPY . .

# Copy the entrypoint script into the container and make executeable
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

USER octo