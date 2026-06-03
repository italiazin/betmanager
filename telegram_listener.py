# -*- coding: utf-8 -*-
"""Listener 24/7 do grupo de tips no Telegram (roda numa thread do web service).

PRINCIPIOS DE SEGURANCA (pra nunca afetar as partes criticas do app):
  - O import do Telethon e' LAZY (so' dentro de `iniciar`). Se a lib nao estiver
    instalada, o app sobe normal e so' o listener fica desligado.
  - So' liga se TELEGRAM_LISTENER_ON=1 E todas as credenciais existirem.
  - Toda a logica de fila/IA roda em funcoes PURAS e testaveis (sem rede).
  - Filtro pre-IA (`parece_aposta`) evita gastar IA com comentarios.
  - Dedupe por id de mensagem -> o catch-up nao re-processa nada apos restart.
  - Catch-up: ao (re)conectar, le as ultimas horas pra cobrir o buraco do deploy.
"""
import re

# ---- confronto "Time x Time" / "A vs B" / "🆚" ----
_RE_CONFRONTO = re.compile(r"\w[\w\.\-]*\s*(?:x|vs|×)\s*\w", re.IGNORECASE)
_SINAIS_APOSTA = ("over", "under", "handicap", "escanteio", "cartã", "cartao",
                  "ambas marcam", "btts", "vence", "gols", "gol ", "ml ",
                  "dupla chance", "mais de", "menos de", "intervalo", "marcador",
                  "@", "odd", "stake", "entrada", "unidade", "%")


def parece_aposta(texto):
    """Heuristica BARATA: a mensagem parece uma aposta? (evita chamar IA a` toa)."""
    if not texto:
        return False
    if "🆚" in texto:
        return True
    t = texto.lower()
    tem_confronto = bool(_RE_CONFRONTO.search(texto))
    tem_sinal = any(p in t for p in _SINAIS_APOSTA)
    return tem_confronto and tem_sinal


# ============================================================
# Fila + dedupe (PURO — testavel sem rede)
# ============================================================

def _ids_processados(dados):
    return {str(x) for x in dados.get("tips_processadas_ids", [])}


def ja_processada(dados, msg_id):
    return str(msg_id) in _ids_processados(dados)


def _marcar_processada(dados, msg_id):
    lst = dados.setdefault("tips_processadas_ids", [])
    if str(msg_id) not in {str(x) for x in lst}:
        lst.append(msg_id)
    if len(lst) > 3000:            # limita memoria: guarda os ultimos 3000 ids
        del lst[:len(lst) - 3000]


def processar_texto(texto, msg_id, dados, anthropic_key, interpretar_fn, data_iso=None):
    """Decide e (se for aposta nova) adiciona a` fila `tips_pendentes`.
    Retorna a tip adicionada ou None. NAO salva (quem chama agrupa o save).

    `interpretar_fn(texto, key) -> dict|None` e' injetado (mockavel nos testes).
    `data_iso` = horario de envio da mensagem (ISO), guardado pra exibir no card."""
    if ja_processada(dados, msg_id):
        return None
    if not parece_aposta(texto):
        _marcar_processada(dados, msg_id)        # nao e' aposta: nao reavalia (poupa IA)
        return None
    try:
        interp = interpretar_fn(texto, anthropic_key)
    except Exception as e:
        print("[telegram] erro na interpretacao:", e)
        return None
    _marcar_processada(dados, msg_id)
    if not (interp and interp.get("eh_aposta")):
        return None
    tip = dict(interp)
    tip["id"] = msg_id
    if data_iso:
        tip["data_envio"] = data_iso
    dados.setdefault("tips_pendentes", []).append(tip)
    return tip


# ============================================================
# Parte de REDE (Telethon) — isolada; so' roda quando `iniciar` e' chamado
# ============================================================

def iniciar(api_id, api_hash, session_str, grupo, anthropic_key,
            dados, salvar_fn, interpretar_fn, horas_catchup=8, interpretar_img_fn=None):
    """Loop do listener — BLOQUEIA, entao chame numa thread daemon.
    Reconecta sozinho com backoff. Telethon e' importado AQUI (lazy).
    `interpretar_img_fn(texto, b64) -> dict` (opcional): visao hibrida — quando a
    leitura so'-texto fica arriscada e ha' print, re-interpreta com a imagem."""
    import asyncio
    import time
    try:
        from telethon import TelegramClient, events
        from telethon.sessions import StringSession
    except Exception as e:
        print("[telegram] Telethon indisponivel — listener desligado:", e)
        return
    try:
        import interpretacao as _Itp
    except Exception:
        _Itp = None

    async def _achar_grupo(client):
        alvo = (grupo or "").lower()
        async for d in client.iter_dialogs():
            if alvo and alvo in (d.name or "").lower():
                return d.entity
        return None

    import os
    PASTA_IMG = os.path.join("static", "tips_imgs")
    os.makedirs(PASTA_IMG, exist_ok=True)

    async def _baixar_img(client, m, tip):
        """Baixa o print da aposta pra static/ e poe o caminho na tip. Best-effort."""
        if not getattr(m, "photo", None):
            return
        try:
            caminho = os.path.join(PASTA_IMG, f"msg_{m.id}.jpg")
            if not os.path.exists(caminho):
                await client.download_media(m, caminho)
            tip["img"] = f"/static/tips_imgs/msg_{m.id}.jpg"
        except Exception as e:
            print("[telegram] falha ao baixar print:", e)

    async def _upgrade_com_imagem(client, m, tip):
        """Visao hibrida: se a leitura so'-texto ficou arriscada (ex: multipla de
        varios jogos) e ha' print, re-interpreta COM a imagem e atualiza a tip."""
        if not (interpretar_img_fn and _Itp and getattr(m, "photo", None)):
            return
        try:
            if not _Itp.precisa_de_imagem(tip):
                return
            import base64
            b = await client.download_media(m, file=bytes)
            if not b:
                return
            interp2 = interpretar_img_fn(m.message or "", base64.b64encode(b).decode())
            if interp2 and interp2.get("eh_aposta"):
                _id, _img, _de = tip.get("id"), tip.get("img"), tip.get("data_envio")
                tip.clear(); tip.update(interp2)
                tip["id"] = _id
                if _img:
                    tip["img"] = _img
                if _de:
                    tip["data_envio"] = _de
                tip["_usou_imagem"] = True
        except Exception as e:
            print("[telegram] upgrade com imagem falhou:", e)

    async def _catchup(client, ent):
        from datetime import datetime, timezone, timedelta
        limite = datetime.now(timezone.utc) - timedelta(hours=horas_catchup)
        novas = 0
        async for m in client.iter_messages(ent, limit=300):
            if m.date and m.date < limite:
                break
            d_iso = m.date.isoformat() if m.date else None
            tip = processar_texto(m.message or "", m.id, dados, anthropic_key, interpretar_fn, d_iso)
            if tip:
                await _baixar_img(client, m, tip)
                await _upgrade_com_imagem(client, m, tip)
                novas += 1
        if novas:
            salvar_fn()
        print(f"[telegram] catch-up: {novas} tip(s) recuperada(s)")

    async def _run():
        client = TelegramClient(StringSession(session_str), api_id, api_hash)
        await client.connect()
        if not await client.is_user_authorized():
            print("[telegram] sessao NAO autorizada — gere a StringSession de novo. Listener off.")
            return
        ent = await _achar_grupo(client)
        if not ent:
            print(f"[telegram] grupo nao encontrado: {grupo!r}. Listener off.")
            await client.disconnect()
            return
        print(f"[telegram] conectado. Ouvindo o grupo: {grupo!r}")
        try:
            await _catchup(client, ent)
        except Exception as e:
            print("[telegram] catch-up falhou (segue em tempo real):", e)

        @client.on(events.NewMessage(chats=ent))
        async def _handler(ev):
            try:
                d_iso = ev.message.date.isoformat() if ev.message.date else None
                tip = processar_texto(ev.message.message or "", ev.message.id,
                                      dados, anthropic_key, interpretar_fn, d_iso)
                if tip:
                    await _baixar_img(client, ev.message, tip)
                    await _upgrade_com_imagem(client, ev.message, tip)
                    salvar_fn()
                    print(f"[telegram] tip nova: {tip.get('casa')} | {tip.get('jogos')}")
            except Exception as e:
                print("[telegram] erro no handler:", e)

        await client.run_until_disconnected()

    espera = 30
    while True:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_run())
            espera = 30                      # saiu limpo -> reseta backoff
        except Exception as e:
            print(f"[telegram] caiu ({e}); reconecta em {espera}s")
        finally:
            try:
                loop.close()
            except Exception:
                pass
        time.sleep(espera)
        espera = min(espera * 2, 300)        # backoff ate 5min
