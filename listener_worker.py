# -*- coding: utf-8 -*-
"""Worker mínimo: Telegram → IA → Discord + Supabase. Sem interface web.
Roda no Render como web service (health check na porta PORT)."""
import os, threading, json, io
from http.server import HTTPServer, BaseHTTPRequestHandler

PORT        = int(os.environ.get("PORT", 10000))
REAL_WEBHOOK = os.environ.get("DISCORD_WEBHOOK", "")
PROXY_WEBHOOK = f"http://127.0.0.1:{PORT}/discord-proxy"

import requests as _req, base64 as _b64
_SUP_URL = os.environ.get("SUPABASE_URL", "")
_SUP_KEY = os.environ.get("SUPABASE_KEY", "")
_sup_salvos: set = set()

def _sup_insert(msg_id, texto, img_bytes=None):
    if not _SUP_URL or not _SUP_KEY:
        return
    try:
        r = _req.post(
            f"{_SUP_URL}/rest/v1/tips",
            json={"msg_id": int(msg_id), "texto": texto,
                  "img_b64": _b64.b64encode(img_bytes).decode() if img_bytes else None},
            headers={"apikey": _SUP_KEY, "Authorization": f"Bearer {_SUP_KEY}",
                     "Content-Type": "application/json", "Prefer": "return=minimal"},
            timeout=15,
        )
        _sup_salvos.add(int(msg_id))
        print(f"[supabase] tip {msg_id} salva (status {r.status_code})")
    except Exception as e:
        print(f"[supabase] erro ao salvar tip: {e}")


# ── Dados mínimos em memória ───────────────────────────────────────────────────
dados = {"bets": [], "saldo_casas": {}, "saldo_casas_por_usuario": {},
         "movimentacoes_casas_por_usuario": {}, "tips_grupo": []}

def _salvar():
    pass  # Supabase é salvo no proxy do Discord

def _salvar_img(msg_id, img_bytes):
    pass  # imagem é salva no proxy do Discord (via multipart)


# ── Proxy Discord → Supabase + Discord real ────────────────────────────────────
class _Health(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(length)
        ct     = self.headers.get("Content-Type", "")

        texto     = ""
        img_bytes = None

        # — Extrai texto e imagem do payload do Discord —
        if "application/json" in ct:
            try:
                payload = json.loads(body)
                embeds  = payload.get("embeds", [])
                if embeds:
                    texto = embeds[0].get("description", "")
            except Exception:
                pass
        elif "multipart" in ct:
            try:
                import cgi
                environ = {"REQUEST_METHOD": "POST", "CONTENT_TYPE": ct,
                           "CONTENT_LENGTH": str(length)}
                form = cgi.FieldStorage(fp=io.BytesIO(body), environ=environ,
                                        keep_blank_values=True)
                if "payload_json" in form:
                    payload = json.loads(form["payload_json"].value)
                    embeds  = payload.get("embeds", [])
                    if embeds:
                        texto = embeds[0].get("description", "")
                if "file" in form:
                    img_bytes = form["file"].file.read()
            except Exception as e:
                print(f"[proxy] erro parse multipart: {e}")

        # — Pega o msg_id do último mensagem marcada —
        ids    = dados.get("discord_enviados", [])
        msg_id = ids[-1] if ids else None
        if msg_id and int(msg_id) not in _sup_salvos:
            threading.Thread(
                target=_sup_insert,
                args=(msg_id, texto),
                kwargs={"img_bytes": img_bytes},
                daemon=True,
            ).start()

        # — Encaminha pro Discord real —
        if REAL_WEBHOOK:
            try:
                _req.post(REAL_WEBHOOK, data=body,
                          headers={"Content-Type": ct}, timeout=20)
            except Exception as e:
                print(f"[proxy] erro Discord forward: {e}")

        self.send_response(204)
        self.end_headers()

    def log_message(self, *a):
        pass


threading.Thread(
    target=lambda: HTTPServer(("0.0.0.0", PORT), _Health).serve_forever(),
    daemon=True
).start()
print(f"[worker] health check + proxy em :{PORT}")


# ── Listener Telegram → Discord (via proxy) ────────────────────────────────────
api_id   = os.environ.get("TELEGRAM_API_ID")
api_hash = os.environ.get("TELEGRAM_API_HASH")
session  = os.environ.get("TELEGRAM_SESSION")
grupo    = os.environ.get("TELEGRAM_GRUPO", "")
key      = os.environ.get("ANTHROPIC_API_KEY", "")

if not all([api_id, api_hash, session, grupo, key]):
    print("[worker] ERRO: variáveis de ambiente incompletas. Verifique:")
    for v in ["TELEGRAM_API_ID","TELEGRAM_API_HASH","TELEGRAM_SESSION",
              "TELEGRAM_GRUPO","ANTHROPIC_API_KEY"]:
        print(f"  {v}: {'OK' if os.environ.get(v) else 'FALTANDO'}")
else:
    import interpretacao as _Itp
    import telegram_listener as _TL

    def _interpretar(texto, k):
        return _Itp.interpretar_mensagem_grupo(texto, api_key=k)

    def _interpretar_img(texto, b64):
        return _Itp.interpretar_mensagem_grupo(texto, api_key=key, imagem_b64=b64)

    threading.Thread(
        target=_TL.iniciar,
        kwargs=dict(
            api_id=int(api_id), api_hash=api_hash, session_str=session,
            grupo=grupo, anthropic_key=key, dados=dados, salvar_fn=_salvar,
            interpretar_fn=_interpretar, interpretar_img_fn=_interpretar_img,
            discord_webhook=PROXY_WEBHOOK,   # proxy local, não o Discord direto
            salvar_img_fn=_salvar_img,
        ),
        daemon=True,
    ).start()
    print(f"[worker] listener Telegram iniciado (proxy={PROXY_WEBHOOK})")


# ── Mantém o processo vivo ─────────────────────────────────────────────────────
import time
while True:
    time.sleep(60)
