#!/bin/bash

# Start virtual display
Xvfb :1 -ac -screen 0 "1920x1080x24" -nolisten tcp +extension GLX +render -noreset &

# Change ownership
sudo chown -R octo:octo /home/octo

# Run Octo Browser in headless mode in the background
(DISPLAY=:1 OCTO_HEADLESS=1 /home/octo/browser/OctoBrowser.AppImage &)

sleep 10

max_retries=3
retry_count=0
OCTO_EMAIL=$(echo $OCTO_CREDENTIALS | jq -r '.username')
OCTO_PASSWORD=$(echo $OCTO_CREDENTIALS | jq -r '.password')

while [ $retry_count -lt $max_retries ] && \
      { [ -z "$response" ] || [[ $response != *'{"msg":"Logged in successfully"}'* ]] && \
        [[ $response != *'{"error":"Already logged in"}'* ]]; }; do

    # Capture the response of the curl command
    response=$(curl --location http://localhost:58888/api/auth/login --header 'Content-Type: application/json' --data-raw "{\"email\": \"$OCTO_EMAIL\", \"password\": \"$OCTO_PASSWORD\"}")

    echo "Attempt: $((retry_count+1)), Response: $response"

    retry_count=$((retry_count+1))
    sleep 5
done

# Check if max retries reached
if [ $retry_count -eq $max_retries ]; then
    echo "Could not successfully log into Octo. Exiting."
    exit 1
fi

celery -A poshbot_api worker --concurrency=4 -Q "$GENERAL_QUEUE" -l INFO