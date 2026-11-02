import json
import os
import re
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler

# Подхватываем ключ в новом формате AQ. (или старом, если остался)
RAW_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GEMINI_KEY") or ""
GEMINI_KEY = RAW_KEY.strip().strip('"').strip("'")

RAW_SERPER = os.environ.get("SERPER_API_KEY") or os.environ.get("SERPER_KEY") or ""
SERPER_KEY = RAW_SERPER.strip().strip('"').strip("'")

# Используем стабильный эндпоинт v1beta с поддержкой новых ключей через заголовки
API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"
MAX_HISTORY = 6

def clip(text, max_length=700):
    return re.sub(r"\s+", " ", str(text or "")).strip()[:max_length]

def needs_search(text):
    keywords = [
        "сегодня", "сейчас", "последние", "новости", "погода",
        "курс", "цена", "стоимость", "расписание", "кто победил"
    ]
    return any(k in text.lower() for k in keywords)

def serper_search(query):
    if not SERPER_KEY:
        return ""
    req = urllib.request.Request(
        "https://google.serper.dev/search",
        data=json.dumps({"q": query, "num": 3}).encode("utf-8"),
        headers={"X-API-KEY": SERPER_KEY, "Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=1.2) as r:
            results = json.loads(r.read().decode("utf-8")).get("organic", [])
            return "\n".join(f"{i.get('title')}: {i.get('snippet')}" for i in results)[:1200]
    except Exception:
        return ""

def ask_gemini(message, history, search_context=""):
    if not GEMINI_KEY:
        return "В настройках Vercel не найден ключ API."

    contents = []
    for item in history:
        if isinstance(item, dict) and item.get("role") in ["user", "model"] and item.get("text"):
            contents.append({"role": item["role"], "parts": [{"text": clip(item["text"], 400)}]})

    prompt = (
        "Ты голосовой ассистент Джарвис. Отвечай на русском языке, кратко (1-3 предложения), "
        "естественно для озвучки голосом, без списков, звездочек и Markdown.\n"
    )
    if search_context:
        prompt += f"\nСвежие данные из интернета:\n{search_context}\n"
    prompt += f"\nЗапрос пользователя: {message}"

    contents.append({"role": "user", "parts": [{"text": prompt}]})
    payload = {
        "contents": contents,
        "generationConfig": {"temperature": 0.5, "maxOutputTokens": 180}
    }

    # Передаем новый ключ AQ. исключительно через заголовок безопасности x-goog-api-key
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": GEMINI_KEY
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=4.0) as response:
            data = json.loads(response.read().decode("utf-8"))
            parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            return clip("".join(p.get("text", "") for p in parts))
    except urllib.error.HTTPError as e:
        err_message = e.read().decode("utf-8", errors="ignore")[:150]
        return f"Ошибка API {e.code}: {err_message}"
    except Exception as e:
        return f"Сбой связи: {str(e)[:80]}"

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = {}
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8"))

            req = body.get("request", {})
            session = body.get("session", {})
            
            history = body.get("state", {}).get("session", {}).get("history", [])
            if not isinstance(history, list):
                history = []

            q = clip(req.get("original_utterance") or req.get("command") or "")

            if session.get("new") and not q:
                self.send_yandex("Слушаю вас, сэр.", session, [], body)
                return

            if not q:
                self.send_yandex("Я вас слушаю.", session, history, body)
                return

            if q.lower() == "ping":
                self.send_yandex("pong", session, history, body)
                return

            search_data = serper_search(q) if (SERPER_KEY and needs_search(q)) else ""
            answer = ask_gemini(q, history, search_data)

            if not answer.startswith(("Ошибка API", "В настройках", "Сбой связи")):
                history.append({"role": "user", "text": q})
                history.append({"role": "model", "text": answer})
                history = history[-MAX_HISTORY:]

            self.send_yandex(answer, session, history, body)

        except Exception:
            self.send_yandex("Произошла техническая заминка, повторите еще раз.", body.get("session", {}), [], body)

    def send_yandex(self, text, session, history, body):
        res = {
            "version": body.get("version", "1.0"),
            "session": session,
            "response": {
                "text": text[:1024],
                "tts": text[:1024],
                "end_session": False
            },
            "session_state": {"history": history}
        }
        out = json.dumps(res, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)
