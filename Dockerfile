FROM ghcr.io/mredwin1/chrome:latest

# Copy the project files into working directory
COPY . .

# Install dependencies for pycurl
RUN apt install -y libcurl4-openssl-dev libssl-dev

# Install the dependencies
RUN pipenv install --system --deploy --skip-lock

# Run web server through custom manager
ENTRYPOINT ["python3", "manage.py"]
CMD ["start"]