
import json
import os
import re
import time
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler


# =========================
# ENVIRONMENT VARIABLES
# =========================

GEMINI_KEY = (
    os.environ.get("GEMINI_API_KEY")
    or os.environ.get("GEMINI_KEY")
    or ""
).strip().strip('"').strip("'")

SERPER_KEY = (
    os.environ.get("SERPER_API_KEY")
    or os.environ.get("SERPER_KEY")
    or ""
).strip().strip('"').strip("'")


# =========================
# GEMINI SETTINGS
# =========================

GEMINI_MODEL = "gemini-3.8-flash"

API_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/"
    f"models/{GEMINI_MODEL}:generateContent"
)

MAX_HISTORY = 4
GEMINI_TIMEOUT = 3.0
SERPER_TIMEOUT = 0.8


# =========================
# HELPERS
# =========================

def clip(text, max_length=700):
    return re.sub(
        r"\s+",
        " ",
        str(text or "")
    ).strip()[:max_length]


def clean_for_tts(text):
    text = str(text or "")

    text = re.sub(r"[*_`#]", "", text)
    text = re.sub(
        r"\[([^\]]+)\]\([^)]+\)",
        r"\1",
        text
    )

    return clip(text, 900)


# =========================
# SEARCH DETECTION
# =========================

def needs_search(text):

    keywords = [
        "сегодня",
        "сейчас",
        "последние",
        "последний",
        "последняя",
        "новости",
        "новость",
        "погода",
        "курс",
        "цена",
        "цены",
        "стоимость",
        "расписание",
        "кто победил",
        "актуальная",
        "актуальный",
        "актуальные",
        "latest",
        "news",
        "today",
        "weather",
        "price"
    ]

    text = text.lower()

    return any(
        keyword in text
        for keyword in keywords
    )


# =========================
# SERPER SEARCH
# =========================

def serper_search(query):

    if not SERPER_KEY:
        return ""

    url = "https://google.serper.dev/search"

    payload = {
        "q": query,
        "num": 5
    }

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "X-API-KEY": SERPER_KEY,
            "Content-Type": "application/json"
        },
        method="POST"
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=SERPER_TIMEOUT
        ) as response:

            data = json.loads(
                response.read().decode("utf-8")
            )

        results = data.get("organic", [])

        formatted_results = []

        for item in results:

            title = item.get("title", "")
            snippet = item.get("snippet", "")

            if title or snippet:

                formatted_results.append(
                    f"{title}: {snippet}"
                )

        return "\n".join(
            formatted_results
        )[:2500]

    except urllib.error.HTTPError as error:

        print(
            "Serper HTTP error:",
            error.code
        )

        return ""

    except Exception as error:

        print(
            "Serper error:",
            str(error)
        )

        return ""


# =========================
# GEMINI
# =========================

def ask_gemini(
    message,
    history,
    search_context=""
):

    if not GEMINI_KEY:

        return (
            "В настройках Vercel "
            "не найден ключ Gemini API."
        )

    contents = []

    for item in history:

        if not isinstance(item, dict):
            continue

        role = item.get("role")
        text = item.get("text")

        if role in ["user", "model"] and text:

            contents.append({
                "role": role,
                "parts": [{
                    "text": clip(text, 300)
                }]
            })

    prompt = """
Ты голосовой ассистент Джарвис.

Отвечай на русском языке, если пользователь
не говорит на другом языке.

Правила:
- Отвечай кратко, обычно 1-3 предложения.
- Естественно звучать при голосовом озвучивании.
- Не используй Markdown.
- Не используй ссылки.
- Не используй длинные списки.
- Не повторяй вопрос пользователя.
- Отвечай прямо и понятно.
"""

    if search_context:

        prompt += f"""

Свежая информация из интернета:

{search_context}

Используй её, если она относится к вопросу.
Не придумывай актуальные факты.
"""

    prompt += f"""

Текущий запрос пользователя:

{message}
"""

    contents.append({
        "role": "user",
        "parts": [{
            "text": prompt
        }]
    })

    payload = {
        "contents": contents,
        "generationConfig": {
            "temperature": 0.5,
            "maxOutputTokens": 120
        }
    }

    request = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": GEMINI_KEY
        },
        method="POST"
    )

    # Один дополнительный запрос при временном сбое.
    # Общий лимит времени всё равно ограничен Яндексом.

    for attempt in range(2):

        try:

            with urllib.request.urlopen(
                request,
                timeout=GEMINI_TIMEOUT
            ) as response:

                data = json.loads(
                    response.read().decode("utf-8")
                )

            candidates = data.get(
                "candidates",
                []
            )

            if not candidates:

                print(
                    "Gemini returned no candidates:",
                    data
                )

                return "Не удалось сформировать ответ."

            parts = (
                candidates[0]
                .get("content", {})
                .get("parts", [])
            )

            answer = "".join(
                part.get("text", "")
                for part in parts
            )

            answer = clean_for_tts(answer)

            if not answer:
                return "Не удалось сформировать ответ."

            return answer

        except urllib.error.HTTPError as error:

            error_body = error.read().decode(
                "utf-8",
                errors="ignore"
            )

            print(
                "Gemini HTTP error:",
                error.code,
                error_body
            )

            if (
                error.code in [429, 500, 502, 503, 504]
                and attempt == 0
            ):

                time.sleep(0.15)
                continue

            return (
                "Сервис временно недоступен. "
                "Попробуйте ещё раз."
            )

        except Exception as error:

            print(
                "Gemini error:",
                str(error)
            )

            return (
                "Сейчас не удалось получить ответ. "
                "Попробуйте ещё раз."
            )

    return "Сейчас не удалось получить ответ."


# =========================
# YANDEX WEBHOOK
# =========================

class handler(BaseHTTPRequestHandler):

    def do_POST(self):

        body = {}

        try:

            content_length = int(
                self.headers.get(
                    "Content-Length",
                    0
                )
            )

            raw_body = self.rfile.read(
                content_length
            )

            body = json.loads(
                raw_body.decode("utf-8")
            )

            request_data = body.get(
                "request",
                {}
            )

            session = body.get(
                "session",
                {}
            )

            # =========================
            # SESSION HISTORY
            # =========================

            session_state = body.get(
                "state",
                {}
            ).get(
                "session",
                {}
            )

            history = session_state.get(
                "history",
                []
            )

            if not history:

                history = body.get(
                    "session_state",
                    {}
                ).get(
                    "history",
                    []
                )

            if not isinstance(history, list):
                history = []

            clean_history = []

            for item in history:

                if (
                    isinstance(item, dict)
                    and item.get("role") in ["user", "model"]
                    and isinstance(item.get("text"), str)
                ):

                    clean_history.append({
                        "role": item["role"],
                        "text": clip(item["text"], 300)
                    })

            history = clean_history[-MAX_HISTORY:]

            # =========================
            # USER MESSAGE
            # =========================

            question = clip(
                request_data.get("original_utterance")
                or request_data.get("command")
                or ""
            )

            # =========================
            # FIRST LAUNCH
            # =========================

            if session.get("new") and not question:

                self.send_yandex(
                    "Слушаю вас, сэр.",
                    session,
                    [],
                    body
                )

                return

            # =========================
            # EMPTY MESSAGE
            # =========================

            if not question:

                self.send_yandex(
                    "Я вас слушаю.",
                    session,
                    history,
                    body
                )

                return

            # =========================
            # PING
            # =========================

            if question.lower() == "ping":

                self.send_yandex(
                    "pong",
                    session,
                    history,
                    body
                )

                return

            # =========================
            # SERPER
            # =========================

            search_context = ""

            if SERPER_KEY and needs_search(question):

                search_context = serper_search(question)

            # =========================
            # GEMINI
            # =========================

            answer = ask_gemini(
                message=question,
                history=history,
                search_context=search_context
            )

            # =========================
            # SAVE HISTORY
            # =========================

            error_prefixes = (
                "В настройках Vercel",
                "Сейчас не удалось",
                "Не удалось сформировать",
                "Сервис временно недоступен"
            )

            if not answer.startswith(error_prefixes):

                history.append({
                    "role": "user",
                    "text": clip(question, 300)
                })

                history.append({
                    "role": "model",
                    "text": clip(answer, 300)
                })

                history = history[-MAX_HISTORY:]

            # =========================
            # SEND RESPONSE
            # =========================

            self.send_yandex(
                answer,
                session,
                history,
                body
            )

        except Exception as error:

            print(
                "Webhook error:",
                str(error)
            )

            self.send_yandex(
                "Произошла техническая ошибка. Попробуйте ещё раз.",
                body.get("session", {}),
                [],
                body
            )

    # =========================
    # RESPONSE TO YANDEX
    # =========================

    def send_yandex(
        self,
        text,
        session,
        history,
        body
    ):

        text = clean_for_tts(text)

        response_data = {
            "version": body.get("version", "1.0"),
            "session": session,
            "response": {
                "text": text[:1024],
                "tts": text[:1024],
                "end_session": False
            },
            "session_state": {
                "history": history
            }
        }

        output = json.dumps(
            response_data,
            ensure_ascii=False
        ).encode("utf-8")

        self.send_response(200)

        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8"
        )

        self.send_header(
            "Content-Length",
            str(len(output))
        )

        self.end_headers()

        self.wfile.write(output)
