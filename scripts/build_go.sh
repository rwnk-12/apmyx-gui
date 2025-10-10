set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
PROJECT_ROOT="$SCRIPT_DIR/.."
BACKEND_DIR="$PROJECT_ROOT/backend"
OUTPUT_DIR="$PROJECT_ROOT/src/core" 


OS="$(uname -s)"
EXT=""
if [[ "$OS" == "CYGWIN"* || "$OS" == "MINGW"* || "$OS" == "MSYS"* ]]; then
    EXT=".exe"
fi

echo "Building Go backend executable for $OS..."

cd "$BACKEND_DIR"

OUTPUT_PATH="$OUTPUT_DIR/downloader$EXT"
echo "Outputting to: $OUTPUT_PATH"
go build -o "$OUTPUT_PATH" .

echo "Build complete."