#!/bin/bash
set -e

echo "$DOCKER_PASSWORD" | docker login -u "$DOCKER_USERNAME" --password-stdin
docker tag kompos adobe/kompos:0.3.6
docker push adobe/kompos:0.3.6
