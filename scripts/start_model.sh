#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
if command -v ollama >/dev/null 2>&1; then
  model_runtime=$(command -v ollama)
elif [ -x .tools/ollama/ollama ]; then
  model_runtime="$PWD/.tools/ollama/ollama"
else
  echo '请先从 https://ollama.com/download 安装 Ollama。'
  exit 1
fi
export OLLAMA_NO_CLOUD=1
export OLLAMA_HOST=127.0.0.1:11434
export OLLAMA_MODELS="$PWD/data/ollama-models"
exec "$model_runtime" serve
