import json
import os
import re
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler

# Подхватываем ключ из любой переменной и убираем случайные пробелы
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", os.environ.get("GEMINI_KEY", "")).strip()
SERPER_KEY = os.environ.get("SERPER_API_KEY", os.environ.get("SERPER_KEY", "")).strip()

# Список моделей по приоритету (если первая выдаст 404, код сам найдет рабочую)
PREFERRED_MODELS = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash-latest"]
CACHED_MODEL = None
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
        # Жесткий таймаут 1.2 сек, чтобы успеть ответить Яндексу
        with urllib.request.urlopen(req, timeout=1.2) as r:
            results = json.loads(r.read().decode("utf-8")).get("organic", [])
            return "\n".join(f"{i.get('title')}: {i.get('snippet')}" for i in results)[:1200]
    except Exception:
        return ""

def find_working_model():
    """Автоматически запрашивает у Google список доступных моделей для вашего ключа."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_KEY}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=1.5) as r:
            data = json.loads(r.read().decode("utf-8"))
            avail = [
                m["name"].replace("models/", "")
                for m in data.get("models", [])
                if "generateContent" in m.get("supportedGenerationMethods", [])
            ]
            for pref in PREFERRED_MODELS:
                if pref in avail:
                    return pref
            for m in avail:
                if "flash" in m or "gemini" in m:
                    return m
            return avail[0] if avail else None
    except Exception:
        return None

def call_model(model_name, payload):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_KEY}"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=2.6) as r:
        data = json.loads(r.read().decode("utf-8"))
        parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        return clip("".join(p.get("text", "") for p in parts))

def ask_gemini(message, history, search_context=""):
    global CACHED_MODEL
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

    model_to_use = CACHED_MODEL or PREFERRED_MODELS[0]

    try:
        answer = call_model(model_to_use, payload)
        CACHED_MODEL = model_to_use
        return answer or "Не удалось сформулировать ответ."
    except urllib.error.HTTPError as e:
        if e.code == 404:
            # Если модель не найдена — автоматически ищем доступную на аккаунте
            real_model = find_working_model()
            if real_model:
                try:
                    CACHED_MODEL = real_model
                    return call_model(real_model, payload)
                except Exception as inner_e:
                    return f"Модель {real_model} найдена, но выдала сбой: {str(inner_e)[:80]}"
            return "Ошибка 404: для вашего API ключа не найдено доступных текстовых моделей."
        return f"Ошибка доступа к Google API (код {e.code}). Проверьте ключ."
    except Exception:
        return "Запрос занял слишком много времени, повторите вопрос покороче."

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = {}
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8"))

            req = body.get("request", {})
            session = body.get("session", {})
            
            # Правильное извлечение памяти из запроса Яндекса
            history = body.get("state", {}).get("session", {}).get("history", [])
            if not isinstance(history, list):
                history = []

            q = clip(req.get("original_utterance") or req.get("command") or "")

            # Приветствие при запуске навыка
            if session.get("new") and not q:
                self.send_yandex("Слушаю вас, сэр.", session, [], body)
                return

            if not q:
                self.send_yandex("Я вас слушаю.", session, history, body)
                return

            if q.lower() == "ping":
                self.send_yandex("pong", session, history, body)
                return

            # Поиск в интернете сработает только если в Vercel добавлен SERPER_API_KEY
            search_data = serper_search(q) if (SERPER_KEY and needs_search(q)) else ""
            answer = ask_gemini(q, history, search_data)

            # Сохраняем контекст только при успешном ответе
            if not answer.startswith(("Ошибка", "Запрос занял", "В настройках")):
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
