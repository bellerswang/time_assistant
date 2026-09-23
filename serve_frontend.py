"""Serve only public Loomi assets, never the surrounding project files."""

import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parent
PUBLIC_FILES = frozenset({
    "index.html", "firebase-config.js", "manifest.json", "sw.js", "loomi_icon.png",
})


class PublicAssetHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def send_head(self):
        path = unquote(urlsplit(self.path).path)
        name = "index.html" if path == "/" else path.removeprefix("/")
        candidate = ROOT / name
        if name not in PUBLIC_FILES or candidate.resolve().parent != ROOT:
            self.send_error(404)
            return None
        self.path = "/" + name
        return super().send_head()

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--bind", default="127.0.0.1")
    args = parser.parse_args()
    ThreadingHTTPServer((args.bind, args.port), PublicAssetHandler).serve_forever()
