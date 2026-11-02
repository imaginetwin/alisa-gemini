import json, os, urllib.request
from http.server import BaseHTTPRequestHandler

KEY = os.environ.get("GEMINI_KEY", "")
API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={KEY}"
SYSTEM = "Ты голосовой помощник в колонке. Отвечай коротко и по-русски."

def gemini(q):
    if not KEY:
        return "Ошибка: Ключ GEMINI_KEY не найден."
    
    payload = {"system_instruction": {"parts": [{"text": SYSTEM}]}, "contents": [{"parts": [{"text": q}]}]}
    req = urllib.request.Request(API_URL, data=json.dumps(payload).encode('utf-8'), headers={"Content-Type": "application/json"})
    
    try:
        with urllib.request.urlopen(req, timeout=5.0) as r:
            return json.loads(r.read().decode('utf-8'))["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        return f"Системный сбой: {str(e)}"

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        q = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0)))).get("request", {}).get("original_utterance", "")
        text = "pong" if q == "ping" else gemini(q) if q else "Слушаю."
        
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.end_headers()
        self.wfile.write(json.dumps({"version": "1.0", "response": {"text": text[:1024], "end_session": False}}, ensure_ascii=False).encode('utf-8'))
