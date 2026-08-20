#!/usr/bin/env bash
set -euo pipefail
if ! command -v docker >/dev/null 2>&1; then
  echo "Docker was not found. Install Docker Desktop/Engine, then run this script again."
  exit 1
fi
docker compose up -d --build
echo "AnimationVideoTool is running at http://127.0.0.1:7860"
if command -v open >/dev/null 2>&1; then open http://127.0.0.1:7860 >/dev/null 2>&1 || true
elif command -v xdg-open >/dev/null 2>&1; then xdg-open http://127.0.0.1:7860 >/dev/null 2>&1 || true
fi
echo "To stop: ./stop_docker_mac_linux.sh"
