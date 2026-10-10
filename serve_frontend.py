"""Serve the frontend only, without exposing project files or secrets."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class FrontendHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.split("?", 1)[0] not in ("/", "/index.html"):
            self.send_error(404)
            return
        body = Path(__file__).with_name("index.html").read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    print("Frontend: http://127.0.0.1:5500/", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 5500), FrontendHandler).serve_forever()
