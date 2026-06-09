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

# ---- atualização/comentário sobre aposta existente (em reply) ----
_RE_ATUALIZACAO = re.compile(
    r"agora\s+vale|agora\s+valendo|antes\s+[\d,\.]+\s*%|odd\s+atualiz"
    r"|replanilhar|@\s*\d+[\.,]\d+"           # "@7.50" = referência a odd
    r"|odd\s+(?:subiu|caiu|mudou|nova|atual)"
    r"|limit[ea]|sobrecarreg",                # avisos de limite/sobrecarga de banca
    re.IGNORECASE
)


def _parece_atualizacao(texto):
    """Detecta comentário/atualização sobre uma aposta postado em reply."""
    if not texto:
        return False
    return bool(_RE_ATUALIZACAO.search(texto))


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


_RE_BETLINK = re.compile(r"https?://[^\s]*(?:share|/bet/|\.bet\.|sportsbook|aposta)", re.IGNORECASE)


def parece_aposta_ampla(texto, tem_foto=False):
    """Mais abrangente (p/ encaminhar ao Discord): pega tambem apostas que estao
    SO' NA IMAGEM, onde o texto e' so' uma legenda com link/percentual."""
    if parece_aposta(texto):
        return True
    if tem_foto:
        t = (texto or "").lower()
        if _RE_BETLINK.search(texto or ""):
            return True
        if any(p in t for p in ("aposta", "valendo", "vale ", " odd", "stake", "unidade")):
            return True
        if "%" in t and any(p in t for p in ("banca", "entrada", "lucro", "green")):
            return True
    return False


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


def _ja_enviada_discord(dados, msg_id):
    return str(msg_id) in {str(x) for x in dados.get("tips_discord_ids", [])}


def _marcar_discord(dados, msg_id):
    lst = dados.setdefault("tips_discord_ids", [])
    if str(msg_id) not in {str(x) for x in lst}:
        lst.append(msg_id)
    if len(lst) > 3000:
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


def _prune_tips(dados, horas=48):
    """Remove da fila as tips com mais de `horas` (some da aba depois de 48h).
    O dedupe (tips_processadas_ids) impede que voltem."""
    from datetime import datetime, timezone, timedelta
    fila = dados.get("tips_pendentes")
    if not fila:
        return
    limite = datetime.now(timezone.utc) - timedelta(hours=horas)
    mantidas = []
    for t in fila:
        de = t.get("data_envio")
        if de:
            try:
                dt = datetime.fromisoformat(str(de).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt < limite:
                    continue
            except Exception:
                pass
        mantidas.append(t)
    if len(mantidas) != len(fila):
        fila[:] = mantidas


def _links_da_mensagem(msg):
    """Pega URLs que estao escondidas em hyperlinks (MessageEntityTextUrl) —
    garante o link de share mesmo se o Telegram formatar como 'clique aqui'."""
    urls = []
    try:
        for e in (getattr(msg, "entities", None) or []):
            u = getattr(e, "url", None)
            if u:
                urls.append(u)
    except Exception:
        pass
    return urls


_RE_LINK_BET = re.compile(
    r"\.bet\.br|\.bet/|/shr/|/share/|betslip|bscode|/bets\?|sportsbook",
    re.IGNORECASE
)
_RE_LINK_LIXO = re.compile(
    r"t\.me/|telegram\.|calcul|wa\.me/|bit\.ly|tinyurl|aff\.",
    re.IGNORECASE
)


def _link_aposta(msg):
    """Retorna o link de share da aposta, preferindo URLs de casas de apostas.
    Ignora links de calculadoras/afiliados/Telegram."""
    urls = []
    # entidades (hyperlinks embutidos) e texto visível
    for u in _links_da_mensagem(msg):
        urls.append(u)
    txt = getattr(msg, "message", "") or ""
    for m in re.finditer(r"https?://\S+", txt):
        u = m.group(0).rstrip(").,")
        if u not in urls:
            urls.append(u)
    if not urls:
        return None
    # prefere link que parece de aposta e não é lixo
    for u in urls:
        if _RE_LINK_BET.search(u) and not _RE_LINK_LIXO.search(u):
            return u
    # fallback: primeiro que não parece lixo
    for u in urls:
        if not _RE_LINK_LIXO.search(u):
            return u
    return urls[0]


def _casa_do_texto(texto):
    """Tenta achar o nome da casa/site da aposta (pro titulo do embed)."""
    import re as _re
    m = _re.search(r"🏠\s*([^\n]+)", texto or "")
    if m:
        return m.group(1).strip()[:80]
    m = _re.search(r"https?://(?:www\.)?([a-z0-9-]+)\.bet", texto or "", _re.I)
    if m:
        return m.group(1).capitalize()
    return None


def _discord_enviar(webhook, content, img_bytes=None, quote=None, titulo=None):
    """Posta no webhook do Discord como EMBED bonito: barra colorida, titulo,
    texto completo do tipster, contexto da resposta (se houver) e a imagem."""
    if not webhook:
        return
    try:
        import requests as _rq
        import json as _json
        embed = {
            "title": ("🎯 " + titulo if titulo else "🎯 Nova aposta")[:256],
            "description": (content or "")[:4000],
            "color": 0x2ECC71,                       # verde aposta
            "footer": {"text": "Bet Manager • Tips"},
        }
        if quote:
            # cita a mensagem respondida (blockquote dentro do campo)
            q = (quote or "")[:900]
            embed["fields"] = [{
                "name": "↪️ Em resposta a",
                "value": "> " + q.replace("\n", "\n> "),
                "inline": False,
            }]
        if img_bytes:
            embed["image"] = {"url": "attachment://aposta.jpg"}
            r = _rq.post(webhook, data={"payload_json": _json.dumps({"embeds": [embed]})},
                         files={"file": ("aposta.jpg", img_bytes, "image/jpeg")}, timeout=20)
        else:
            r = _rq.post(webhook, json={"embeds": [embed]}, timeout=20)
        if r.status_code not in (200, 204):
            print(f"[discord] aviso HTTP {r.status_code}: {r.text[:200]}")
    except Exception as e:
        print("[discord] erro:", e)


# ============================================================
# Parte de REDE (Telethon) — isolada; so' roda quando `iniciar` e' chamado
# ============================================================

def iniciar(api_id, api_hash, session_str, grupo, anthropic_key,
            dados, salvar_fn, interpretar_fn, horas_catchup=8, interpretar_img_fn=None,
            discord_webhook=None, salvar_img_fn=None):
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

    async def _baixar_img(client, m, tip):
        """Baixa o print da aposta e salva no PostgreSQL (via salvar_img_fn).
        Se nao houver callback, nao salva (imagem ficaria no disco efemero)."""
        if not getattr(m, "photo", None) or not salvar_img_fn:
            return
        if tip.get("img"):          # ja baixada anteriormente
            return
        try:
            b = await client.download_media(m, file=bytes)
            if not b:
                return
            salvar_img_fn(m.id, b)
            tip["img"] = f"/tips/img/{m.id}"
        except Exception as e:
            print("[telegram] falha ao baixar/salvar print:", e)

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

    async def _tip_de_imagem(client, m):
        """Cria tip a partir de aposta que esta' SO' NA IMAGEM (texto e' so' legenda):
        le o print com visao da IA. Best-effort — erro de rede NAO marca processada
        (pra tentar de novo no proximo catch-up)."""
        if ja_processada(dados, m.id):
            return None
        if not (interpretar_img_fn and getattr(m, "photo", None)):
            return None
        try:
            import base64
            b = await client.download_media(m, file=bytes)
            if not b:
                return None
            interp = interpretar_img_fn(m.message or "", base64.b64encode(b).decode())
        except Exception as e:
            print("[telegram] interp imagem falhou:", e)
            return None
        _marcar_processada(dados, m.id)
        if not (interp and interp.get("eh_aposta")):
            return None
        tip = dict(interp)
        tip["id"] = m.id
        if m.date:
            tip["data_envio"] = m.date.isoformat()
        tip["_usou_imagem"] = True
        dados.setdefault("tips_pendentes", []).append(tip)
        return tip

    async def _forward_discord(client, m):
        """Encaminha a aposta pro Discord (embed) UMA vez so' (dedupe por id).
        Marca como enviada ANTES do primeiro await pra evitar race entre handler
        e poll loop (ambos no mesmo event loop, mas await cede controle). Se der
        erro de rede a mensagem fica marcada e nao tenta de novo — preferivel a
        mandar em duplicata. Retorna True se enviou agora."""
        if not discord_webhook or _ja_enviada_discord(dados, m.id):
            return False
        _marcar_discord(dados, m.id)          # marca ANTES do primeiro await
        try:
            img_bytes = await client.download_media(m, file=bytes) if m.photo else None
            txt = (m.message or "").strip()
            for u in _links_da_mensagem(m):
                if u not in txt:
                    txt += "\n" + u
            quote = None
            try:
                if getattr(m, "reply_to", None):
                    rep = await m.get_reply_message()
                    if rep:
                        rtxt = (rep.message or "").strip() or ("[imagem]" if rep.photo else "")
                        if rtxt:
                            quote = rtxt[:900]
            except Exception:
                pass
            _discord_enviar(discord_webhook, txt, img_bytes,
                            quote=quote, titulo=_casa_do_texto(txt))
            print(f"[discord] aposta {m.id} encaminhada (foto={bool(img_bytes)})")
            return True
        except Exception as e:
            print("[discord] falha:", e)
            return False

    async def _processar_msg(client, m, permitir_discord=True):
        """Encaminha pro Discord (se aposta ou atualização) E coloca na fila de Tips.
        - Discord: aposta (texto OU so'-imagem) OU reply com atualizacao de valor/odd.
        - Tips: aposta de TEXTO -> processar_texto; aposta SO'-IMAGEM -> visao.
        Retorna (tip, mudou) — `mudou` indica que ha' algo novo a salvar."""
        texto_msg = m.message or ""
        d_iso = m.date.isoformat() if m.date else None
        mudou = False

        # Discord: aposta normal OU reply de atualização OU reply/fwd de uma aposta já enviada
        eh_reply = bool(getattr(m, "reply_to", None))
        reply_to_id = getattr(getattr(m, "reply_to", None), "reply_to_msg_id", None)
        fwd_orig_id = getattr(getattr(m, "fwd_from", None), "channel_post", None)
        eh_reply_a_aposta = bool(reply_to_id and _ja_enviada_discord(dados, reply_to_id))
        eh_fwd_de_aposta  = bool(fwd_orig_id and _ja_enviada_discord(dados, fwd_orig_id))
        deve_discord = (parece_aposta_ampla(texto_msg, bool(getattr(m, "photo", None)))
                        or (eh_reply and _parece_atualizacao(texto_msg))
                        or eh_reply_a_aposta
                        or eh_fwd_de_aposta)
        if permitir_discord and discord_webhook and deve_discord:
            if await _forward_discord(client, m):
                mudou = True

        tip = None
        if parece_aposta(texto_msg):
            tip = processar_texto(texto_msg, m.id, dados, anthropic_key, interpretar_fn, d_iso)
            if tip:
                await _baixar_img(client, m, tip)
                await _upgrade_com_imagem(client, m, tip)
        elif getattr(m, "photo", None) and parece_aposta_ampla(texto_msg, True):
            tip = await _tip_de_imagem(client, m)
            if tip:
                await _baixar_img(client, m, tip)
        if tip:
            link = _link_aposta(m)
            if link:
                tip["link"] = link
            mudou = True
        return tip, mudou

    async def _catchup(client, ent):
        from datetime import datetime, timezone, timedelta
        agora = datetime.now(timezone.utc)
        limite = agora - timedelta(hours=horas_catchup)
        # Discord no catch-up: so' apostas dos ultimos 20min (cobre o gap de um
        # restart/deploy sem despejar horas de historico). Dedupe evita repeticao.
        disc_limite = agora - timedelta(minutes=20)
        # iter_messages vem da mais NOVA -> mais velha; coletamos e invertemos
        # pra processar/encaminhar na ordem CRONOLOGICA (mais antiga -> recente),
        # igual a ordem em que o tipster postou no grupo.
        msgs = []
        async for m in client.iter_messages(ent, limit=300):
            if m.date and m.date < limite:
                break
            msgs.append(m)
        msgs.reverse()
        novas = 0
        mudou_alguma = False
        for m in msgs:
            perm = bool(m.date and m.date >= disc_limite)
            tip, mudou = await _processar_msg(client, m, permitir_discord=perm)
            if tip:
                novas += 1
            if mudou:
                mudou_alguma = True
        _prune_tips(dados)
        if mudou_alguma:
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
                m = ev.message
                ampla = parece_aposta_ampla(m.message or "", bool(m.photo))
                print(f"[telegram] msg {m.id} recebida | foto={bool(m.photo)} | "
                      f"aposta={ampla}")
                tip, mudou = await _processar_msg(client, m)
                if mudou:
                    _prune_tips(dados)
                    salvar_fn()
                if tip:
                    print(f"[telegram] tip nova: {tip.get('casa')} | {tip.get('jogos')}")
            except Exception as e:
                print("[telegram] erro no handler:", e)

        async def _poll_loop():
            """Polling ativo a cada 10s: busca as ultimas msgs do grupo e processa
            qualquer uma que o handler ao vivo nao tenha recebido (update-gap MTProto).
            O dedupe por id garante que nada e' enviado/processado duas vezes."""
            from datetime import datetime, timezone, timedelta
            JANELA = timedelta(minutes=10)
            while client.is_connected():
                await asyncio.sleep(10)
                try:
                    mudou = False
                    async for m in client.iter_messages(ent, limit=20):
                        if m.date and m.date < datetime.now(timezone.utc) - JANELA:
                            break
                        tip, m_flag = await _processar_msg(client, m)
                        if m_flag:
                            mudou = True
                            if tip:
                                print(f"[telegram] poll: tip nova: "
                                      f"{tip.get('casa')} | {tip.get('jogos')}")
                    if mudou:
                        _prune_tips(dados)
                        salvar_fn()
                except Exception as e:
                    print(f"[telegram] poll: erro: {e}")

        asyncio.ensure_future(_poll_loop())
        await client.run_until_disconnected()
        print("[telegram] desconectado — reconectando...")

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
