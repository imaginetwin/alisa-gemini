import json
import os
import re
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", os.environ.get("GEMINI_KEY", ""))
SERPER_API_KEY = os.environ.get("SERPER_API_KEY", "")

# Используем актуальную и существующую модель
GEMINI_MODEL = "gemini-1.5-flash"
MAX_HISTORY = 8

def clip(text, max_length=800):
    return re.sub(r"\s+", " ", str(text or "")).strip()[:max_length]

def needs_search(text):
    keywords = ["сегодня", "сейчас", "последние", "новости", "погода", "курс", "цена", "актуальный", "news", "today", "weather", "price"]
    return any(keyword in text.lower() for keyword in keywords)

def serper_search(query):
    if not SERPER_API_KEY:
        return ""
    url = "https://google.serper.dev/search"
    payload = {"q": query, "num": 3}
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
        results = data.get("organic", [])
        return "\n".join([f"{i+1}. {r.get('title')}: {r.get('snippet')}" for i, r in enumerate(results)])[:2000]
    except Exception:
        return ""

def ask_gemini(message, history, search_context=""):
    if not GEMINI_API_KEY:
        return "Не настроен ключ Gemini."

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    contents = []

    for item in history:
        if item.get("role") in ["user", "model"] and item.get("text"):
            contents.append({"role": item["role"], "parts": [{"text": clip(item["text"])}]})

    prompt = (
        "Ты голосовой ассистент Алиса. Отвечай естественно и кратко (1-3 предложения). "
        "Не используй Markdown, списки и ссылки.\n\n"
    )
    if search_context:
        prompt += f"Актуальная информация из интернета:\n{search_context}\n\n"
    prompt += f"Вопрос: {message}"

    contents.append({"role": "user", "parts": [{"text": prompt}]})

    payload = {
        "contents": contents,
        "generationConfig": {"temperature": 0.5, "maxOutputTokens": 220}
    }

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
        candidates = data.get("candidates", [])
        if not candidates:
            return "Не удалось сформировать ответ."
        parts = candidates[0].get("content", {}).get("parts", [])
        return clip("".join(part.get("text", "") for part in parts), 700)
    except urllib.error.HTTPError as error:
        return f"Gemini API Error {error.code}"
    except Exception:
        return "Не успел подумать."

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(content_length).decode("utf-8"))
            
            request = body.get("request", {})
            session = body.get("session", {})
            
            message = clip(request.get("command") or request.get("original_utterance", ""))
            
            if not message:
                self.send_json(self.build_res("Здравствуйте. Чем могу помочь?", session, [], body))
                return

            session_state = body.get("state", {}).get("session", {})
            previous_history = session_state.get("history", [])
            if not isinstance(previous_history, list):
                previous_history = []

            history = [{"role": i["role"], "text": clip(i["text"])} for i in previous_history if isinstance(i, dict) and i.get("role") in ["user", "model"] and isinstance(i.get("text"), str)]
            history = history[-MAX_HISTORY:]

            search_context = serper_search(message) if needs_search(message) else ""
            answer = ask_gemini(message, history, search_context)

            next_history = history + [{"role": "user", "text": message}, {"role": "model", "text": answer}]
            next_history = next_history[-MAX_HISTORY:]

            self.send_json(self.build_res(answer, session, next_history, body))

        except Exception as error:
            self.send_json(self.build_res("Произошла системная ошибка.", body.get("session", {}), [], body))

    def build_res(self, text, session, history, body):
        return {
            "version": body.get("version", "1.0"),
            "session": session,
            "response": {"text": text, "tts": text, "end_session": False},
            "session_state": {"history": history}
        }

    def send_json(self, data):
        response = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)
