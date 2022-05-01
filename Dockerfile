FROM ghcr.io/mredwin1/chrome:latest

# Copy the project files into working directory
COPY . .

# Install the dependencies
RUN pipenv install --system --deploy

# Run web server through custom manager
ENTRYPOINT ["python3", "manage.py"]
CMD ["start"]