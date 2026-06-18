# -*- coding: utf-8 -*-
"""Worker mínimo: Telegram → IA → Discord. Sem interface web.
Roda no Render como web service (health check na porta PORT)."""
import os, threading, json
from http.server import HTTPServer, BaseHTTPRequestHandler

PORT = int(os.environ.get("PORT", 10000))

# ── Health check mínimo (Render exige porta aberta) ────────────────────────────
class _Health(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, *a):
        pass

threading.Thread(
    target=lambda: HTTPServer(("0.0.0.0", PORT), _Health).serve_forever(),
    daemon=True
).start()
print(f"[worker] health check em :{PORT}")

# ── Dados mínimos em memória ───────────────────────────────────────────────────
dados = {"bets": [], "saldo_casas": {}, "saldo_casas_por_usuario": {},
         "movimentacoes_casas_por_usuario": {}, "tips_grupo": []}

def _salvar():
    pass  # sem persistência — só encaminha pro Discord

def _salvar_img(msg_id, img_bytes):
    pass  # sem banco

# ── Listener Telegram → Discord ────────────────────────────────────────────────
api_id    = os.environ.get("TELEGRAM_API_ID")
api_hash  = os.environ.get("TELEGRAM_API_HASH")
session   = os.environ.get("TELEGRAM_SESSION")
grupo     = os.environ.get("TELEGRAM_GRUPO", "")
key       = os.environ.get("ANTHROPIC_API_KEY", "")
webhook   = os.environ.get("DISCORD_WEBHOOK", "")

if not all([api_id, api_hash, session, grupo, key]):
    print("[worker] ERRO: variáveis de ambiente incompletas. Verifique:")
    for v in ["TELEGRAM_API_ID","TELEGRAM_API_HASH","TELEGRAM_SESSION","TELEGRAM_GRUPO","ANTHROPIC_API_KEY"]:
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
            discord_webhook=webhook, salvar_img_fn=_salvar_img,
        ),
        daemon=True,
    ).start()
    print("[worker] listener Telegram iniciado")

# ── Mantém o processo vivo ─────────────────────────────────────────────────────
import time
while True:
    time.sleep(60)
