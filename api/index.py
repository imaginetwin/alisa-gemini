import json, os, urllib.request
from http.server import BaseHTTPRequestHandler

KEY = os.environ.get("GEMINI_KEY", "")
API = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
MODEL = "gemini-2.5-flash"
SYSTEM = "Ты голосовой помощник в колонке. Отвечай по-русски, коротко, без markdown, списков и эмодзи."

def gemini(q):
    body = json.dumps({"model": MODEL, "messages": [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": q}]}).encode()
    req = urllib.request.Request(API, body, {
        "Authorization": "Bearer " + KEY, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=4.0) as r:
            return json.load(r)["choices"][0]["message"]["content"].strip()
    except Exception:
        return "Не успел подумать, повтори вопрос."

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        req = json.loads(self.rfile.read(content_length))
        
        q = req.get("request", {}).get("original_utterance", "")
        text = "pong" if q == "ping" else gemini(q) if q else "Слушаю."
        
        out = json.dumps({"version": "1.0", "response": {
            "text": text[:1024], "end_session": False}}, ensure_ascii=False).encode('utf-8')
        
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.end_headers()
        self.wfile.write(out)
