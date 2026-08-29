#!/usr/bin/env bash
# Wrapper exigido pelo validador de Agent Plugin do Hermes: o campo "command"
# de mcp.json só aceita um executável "bare" (resolvido via PATH) ou um
# caminho começando com "./" (relativo à raiz do plugin) — nunca um caminho
# absoluto com barra. O instalador do Hermes NÃO adiciona `~/.hermes/bin` ao PATH do
# processo, então "uv" bare não resolve — por isso este wrapper resolve o
# `uv` em tempo de execução (PATH primeiro, senão o local padrão de bundle
# do Hermes) em vez de hardcodar um caminho absoluto em mcp.json.
set -euo pipefail

if command -v uv >/dev/null 2>&1; then
    UV_BIN="$(command -v uv)"
elif [ -x "$HOME/.hermes/bin/uv" ]; then
    UV_BIN="$HOME/.hermes/bin/uv"
else
    echo "uv não encontrado (nem no PATH, nem em ~/.hermes/bin/uv)." >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
exec "$UV_BIN" run -m mcp_server.server
