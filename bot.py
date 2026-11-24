import os, time, threading, requests
from http.server import BaseHTTPRequestHandler, HTTPServer

TOKEN = os.environ["BOT_TOKEN"]
KEY = os.environ["GEMINI_KEY"]
DEFAULT_MODEL = os.environ.get("MODEL", "gemini-2.5-flash")
TG = f"https://api.telegram.org/bot{TOKEN}"
GM = "https://generativelanguage.googleapis.com/v1beta"

chat_model = {}   # chat_id -> model
history = {}      # chat_id -> [{role, parts}]
model_list = []   # cache of model names


# ---------- keep-alive web server (Render ke liye) ----------
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
    def do_HEAD(self):
        self.send_response(200); self.end_headers()
    def log_message(self, *a): pass

def web():
    HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 10000))), H).serve_forever()


# ---------- telegram helpers ----------
def tg(method, **p):
    try:
        return requests.post(f"{TG}/{method}", json=p, timeout=40).json()
    except Exception as e:
        print("tg err", e); return {}

def send(cid, text, markup=None):
    text = text or "(empty)"
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    for i, c in enumerate(chunks):
        p = {"chat_id": cid, "text": c}
        if markup and i == len(chunks) - 1:
            p["reply_markup"] = markup
        tg("sendMessage", **p)


# ---------- gemini ----------
def get_models():
    global model_list
    r = requests.get(f"{GM}/models?key={KEY}&pageSize=200", timeout=30).json()
    if "error" in r:
        raise Exception(r["error"].get("message", "models error"))
    names = []
    for m in r.get("models", []):
        if "generateContent" in m.get("supportedGenerationMethods", []):
            names.append(m["name"].replace("models/", ""))
    model_list = names
    return names

def read_prompt():
    try:
        with open("prompt.txt", "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""

def ask(cid, text):
    model = chat_model.get(cid, DEFAULT_MODEL)
    h = history.setdefault(cid, [])
    h.append({"role": "user", "parts": [{"text": text}]})
    body = {"contents": h[-20:]}
    sp = read_prompt()
    if sp:
        body["systemInstruction"] = {"parts": [{"text": sp}]}
    r = requests.post(f"{GM}/models/{model}:generateContent?key={KEY}",
                      json=body, timeout=120).json()
    if "error" in r:
        h.pop()
        return "Error: " + r["error"].get("message", str(r["error"]))
    try:
        out = "".join(p.get("text", "") for p in r["candidates"][0]["content"]["parts"])
    except Exception:
        h.pop()
        return "Gemini ne jawab nahi diya (blocked ya empty). Dobara try karo."
    h.append({"role": "model", "parts": [{"text": out}]})
    del h[:-20]
    return out


# ---------- handlers ----------
def models_menu(cid):
    names = get_models()
    cur = chat_model.get(cid, DEFAULT_MODEL)
    rows = [[{"text": ("✅ " if n == cur else "") + n, "callback_data": f"m:{i}"}]
            for i, n in enumerate(names[:60])]
    send(cid, f"Total {len(names)} model mile. Abhi: {cur}\nNeeche se chuno:",
         {"inline_keyboard": rows})

def on_message(m):
    cid = m["chat"]["id"]
    text = m.get("text", "")
    if not text:
        return
    try:
        if text.startswith("/start"):
            send(cid, "Bot chalu hai.\n/models - model list/badlo\n/model - current model\n/reset - chat saaf")
        elif text.startswith("/models"):
            models_menu(cid)
        elif text.startswith("/model"):
            send(cid, "Current model: " + chat_model.get(cid, DEFAULT_MODEL))
        elif text.startswith("/reset"):
            history[cid] = []
            send(cid, "Chat reset ho gayi.")
        else:
            tg("sendChatAction", chat_id=cid, action="typing")
            send(cid, ask(cid, text))
    except Exception as e:
        send(cid, "Error: " + str(e))

def on_callback(q):
    cid = q["message"]["chat"]["id"]
    data = q.get("data", "")
    if data.startswith("m:"):
        i = int(data[2:])
        if i < len(model_list):
            chat_model[cid] = model_list[i]
            history[cid] = []
            tg("answerCallbackQuery", callback_query_id=q["id"], text="Model set: " + model_list[i])
            send(cid, "✅ Model badal gaya: " + model_list[i])
            return
    tg("answerCallbackQuery", callback_query_id=q["id"])


def main():
    threading.Thread(target=web, daemon=True).start()
    me = tg("getMe")
    if not me.get("ok"):
        print("BOT_TOKEN GALAT HAI ya Telegram se connect nahi hua:", me, flush=True)
    else:
        print("bot connected: @" + me["result"]["username"], flush=True)
    print("deleteWebhook:", tg("deleteWebhook", drop_pending_updates=True), flush=True)
    offset = 0
    while True:
        try:
            r = requests.get(f"{TG}/getUpdates",
                             params={"timeout": 30, "offset": offset}, timeout=40).json()
            if not r.get("ok"):
                print("getUpdates error:", r, flush=True)
                time.sleep(5)
                continue
            for u in r.get("result", []):
                offset = u["update_id"] + 1
                if "message" in u:
                    threading.Thread(target=on_message, args=(u["message"],), daemon=True).start()
                elif "callback_query" in u:
                    threading.Thread(target=on_callback, args=(u["callback_query"],), daemon=True).start()
        except Exception as e:
            print("poll err", e); time.sleep(3)

main()
