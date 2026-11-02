import json, os, urllib.request
from http.server import BaseHTTPRequestHandler

KEY = os.environ.get("GEMINI_KEY", "")
API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={KEY}"
SYSTEM = "Ты голосовой помощник в колонке. Отвечай по-русски, коротко, без markdown, списков и эмодзи."

def gemini(q):
    if not KEY:
        return "Ошибка: API ключ не найден в настройках Vercel."
    
    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"parts": [{"text": q}]}]
    }
    
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode('utf-8'),
        headers={"Content-Type": "application/json"}
    )
    
    try:
        with urllib.request.urlopen(req, timeout=4.2) as response:
            res_data = json.loads(response.read().decode('utf-8'))
            return res_data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        print(f"Gemini error: {e}")
        return "Не успел подумать, повтори вопрос."

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)
        req = json.loads(body.decode('utf-8'))
        
        q = req.get("request", {}).get("original_utterance", "")
        text = "pong" if q == "ping" else gemini(q) if q else "Слушаю."
        
        out = json.dumps({
            "version": "1.0",
            "response": {
                "text": text[:1024],
                "end_session": False
            }
        }, ensure_ascii=False).encode('utf-8')
        
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.end_headers()
        self.wfile.write(out)
