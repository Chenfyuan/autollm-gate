"""本地告警 Webhook 接收器（验收用）：把收到的每条告警追加写入 JSONL 文件。python scripts/alert_receiver.py 9100 /tmp/alerts.jsonl"""
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT, OUT = int(sys.argv[1]), sys.argv[2]


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("content-length", 0)))
        with open(OUT, "a") as f:
            f.write(json.dumps({"path": self.path, "body": json.loads(body or b"{}")}, ensure_ascii=False) + "\n")
        self.send_response(200); self.end_headers(); self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


HTTPServer(("127.0.0.1", PORT), H).serve_forever()
