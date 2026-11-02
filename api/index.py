import json, os, urllib.request
from http.server import BaseHTTPRequestHandler

# Подхватит любое из двух названий ключа
KEY = os.environ.get("GEMINI_API_KEY", os.environ.get("GEMINI_KEY", ""))
API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={KEY}"

def gemini(q, history):
    if not KEY:
        return "Ошибка: Ключ API не найден.", history
    
    # Собираем историю прошлых сообщений для памяти
    contents = [{"role": msg["role"], "parts": [{"text": msg["text"]}]} for msg in history]
    # Добавляем текущий вопрос
    contents.append({"role": "user", "parts": [{"text": q}]})

    payload = {
        "system_instruction": {"parts": [{"text": "Ты голосовой помощник Алиса. Отвечай коротко, по-русски, без списков и markdown-разметки."}]},
        "contents": contents
    }
    
    req = urllib.request.Request(API_URL, data=json.dumps(payload).encode('utf-8'), headers={"Content-Type": "application/json"})
    
    try:
        with urllib.request.urlopen(req, timeout=6.0) as r:
            answer = json.loads(r.read().decode('utf-8'))["candidates"][0]["content"]["parts"][0]["text"].strip()
            
            # Обновляем историю диалога (храним последние 6 реплик, чтобы не перегружать Яндекс)
            history.append({"role": "user", "text": q})
            history.append({"role": "model", "text": answer})
            return answer, history[-6:]
    except Exception as e:
        return f"Ошибка API: {str(e)}", history

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
        q = body.get("request", {}).get("original_utterance", "")
        
        # Достаем контекст из памяти Яндекса
        history = body.get("state", {}).get("session", {}).get("chat_history", [])

        if q == "ping":
            text, new_history = "pong", history
        elif q:
            text, new_history = gemini(q, history)
        else:
            text, new_history = "Слушаю.", history
        
        # Упаковываем ответ и обновленную память
        res = {
            "version": "1.0",
            "response": {"text": text[:1024], "end_session": False},
            "session_state": {"chat_history": new_history}
        }
        
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.end_headers()
        self.wfile.write(json.dumps(res, ensure_ascii=False).encode('utf-8'))
