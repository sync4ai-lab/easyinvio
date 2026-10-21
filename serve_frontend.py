"""Serve the frontend only, without exposing project files or secrets."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class FrontendHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        route=self.path.split('?',1)[0]
        assets={'/':'index.html','/index.html':'index.html','/set-password':'index.html','/track':'tracking.html',
                '/tracking-workspace.js':'tracking-workspace.js','/tracking-public.js':'tracking-public.js','/tracking-ui.css':'tracking-ui.css'}
        if route not in assets:
            self.send_error(404)
            return
        filename=assets[route]
        body = Path(__file__).with_name(filename).read_bytes()
        self.send_response(200)
        self.send_header('Content-Type',('text/javascript' if filename.endswith('.js') else 'text/css' if filename.endswith('.css') else 'text/html')+'; charset=utf-8')
        self.send_header('Cache-Control','no-store')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    print("Frontend: http://127.0.0.1:5500/", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 5500), FrontendHandler).serve_forever()
