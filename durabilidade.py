# -*- coding: utf-8 -*-
"""
Camada de durabilidade do Bet Manager.

Objetivo: garantir que uma aposta salva NUNCA se perca, mesmo com saves
simultaneos, restart no meio, ou sobrescrita do blob.

Pecas:
  1. LEDGER append-only (apostas_ledger): a cada save, grava um evento
     IMUTAVEL para cada aposta criada/editada/excluida. Nada e' sobrescrito.
     Permite reconstruir as apostas de qualquer usuario em qualquer momento.
  2. ALARME: detecta queda abrupta de apostas por usuario (ex: N -> 0).
  3. BACKUP com retencao real (backups_v2): horarios 48h, diarios 30d,
     semanais 12 semanas. Substitui os 20 snapshots rotativos.

Este modulo NAO conhece o app: recebe conexoes e dados. Isso o torna
testavel isoladamente contra qualquer banco Postgres.

A logica de negocio (diff, reconstrucao, retencao, alarme) e' implementada
como FUNCOES PURAS (sem banco), testaveis sem nenhuma conexao.
"""
import json
import hashlib
from datetime import datetime, timedelta, timezone


# ============================================================
# FUNCOES PURAS (sem banco) -- o coracao da logica
# ============================================================

def hash_bet(b):
    """Hash estavel do conteudo de uma aposta (ignora ordem das chaves)."""
    return hashlib.sha256(
        json.dumps(b, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()


def indexar_bets(bets):
    """Retorna {bet_id: {'user_id', 'hash', 'bet'}} a partir de uma lista de apostas.

    Apostas sem 'id' sao ignoradas no diff (nao deveriam existir: _aplicar_defaults_bets
    garante id), mas tratamos defensivamente."""
    idx = {}
    for b in bets:
        bid = b.get("id")
        if not bid:
            continue
        idx[bid] = {"user_id": b.get("user_id", ""), "hash": hash_bet(b), "bet": b}
    return idx


def calcular_eventos(bets_anteriores, bets_novos):
    """Compara dois estados de apostas e devolve a lista de eventos do ledger.

    Cada evento: {'acao': 'criar'|'editar'|'excluir', 'user_id', 'aposta_id', 'aposta'}.
    - criar: id novo que nao existia antes
    - editar: id existente cujo conteudo mudou
    - excluir: id que existia antes e sumiu

    criar/excluir sao detectados por PRESENCA do id (exato e rapido). edicao e'
    detectada por comparacao direta do dict (mais rapido que hashear tudo).
    """
    ant = {b["id"]: b for b in bets_anteriores if b.get("id")}
    nov = {b["id"]: b for b in bets_novos if b.get("id")}
    eventos = []

    for bid, b in nov.items():
        if bid not in ant:
            eventos.append({"acao": "criar", "user_id": b.get("user_id", ""),
                            "aposta_id": bid, "aposta": b})
        elif b != ant[bid]:
            eventos.append({"acao": "editar", "user_id": b.get("user_id", ""),
                            "aposta_id": bid, "aposta": b})

    for bid, b in ant.items():
        if bid not in nov:
            eventos.append({"acao": "excluir", "user_id": b.get("user_id", ""),
                            "aposta_id": bid, "aposta": b})

    return eventos


def reconstruir_apostas(eventos_em_ordem):
    """Aplica eventos do ledger (do mais antigo ao mais novo) e devolve o
    estado final: lista de apostas. criar/editar = upsert; excluir = remove."""
    estado = {}
    for ev in eventos_em_ordem:
        bid = ev["aposta_id"]
        if ev["acao"] in ("criar", "editar"):
            estado[bid] = ev["aposta"]
        elif ev["acao"] == "excluir":
            estado.pop(bid, None)
    return list(estado.values())


def contar_por_usuario(bets):
    """{user_id: quantidade de apostas}."""
    cont = {}
    for b in bets:
        uid = b.get("user_id", "")
        cont[uid] = cont.get(uid, 0) + 1
    return cont


def detectar_quedas(cont_antes, cont_depois, limite_frac=0.30, limite_abs=5):
    """Detecta usuarios que perderam apostas de forma suspeita.

    Dispara alerta se o usuario perdeu:
      - tudo (foi a 0 tendo >0 antes), OU
      - >= limite_abs apostas E >= limite_frac (fracao) do que tinha.
    Retorna lista de dicts {user_id, antes, depois, perdidas}.
    """
    alertas = []
    for uid, antes in cont_antes.items():
        depois = cont_depois.get(uid, 0)
        perdidas = antes - depois
        if perdidas <= 0:
            continue
        zerou = (depois == 0 and antes > 0)
        grande = (perdidas >= limite_abs and perdidas >= antes * limite_frac)
        if zerou or grande:
            alertas.append({"user_id": uid, "antes": antes,
                            "depois": depois, "perdidas": perdidas})
    return alertas


def ids_backups_a_manter(rows, agora=None,
                         horas_horario=48, dias_diario=30, semanas_semanal=12):
    """Politica de retencao em camadas (GFS). rows = [(id, ts_datetime)].
    Retorna o conjunto de ids a MANTER:
      - todos das ultimas 48h (horarios)
      - o mais recente de cada dia, ultimos 30 dias (diarios)
      - o mais recente de cada semana, ultimas 12 semanas (semanais)
    """
    if agora is None:
        agora = datetime.now(timezone.utc)
    manter = set()
    lim_h = agora - timedelta(hours=horas_horario)
    lim_d = agora - timedelta(days=dias_diario)
    lim_s = agora - timedelta(weeks=semanas_semanal)

    por_dia = {}
    por_sem = {}
    for bid, ts in rows:
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts >= lim_h:
            manter.add(bid)
        if ts >= lim_d:
            d = ts.date()
            if d not in por_dia or ts > por_dia[d][1]:
                por_dia[d] = (bid, ts)
        if ts >= lim_s:
            ic = ts.isocalendar()
            w = (ic[0], ic[1])
            if w not in por_sem or ts > por_sem[w][1]:
                por_sem[w] = (bid, ts)

    manter |= {v[0] for v in por_dia.values()}
    manter |= {v[0] for v in por_sem.values()}
    return manter


# ============================================================
# PARTE DE BANCO -- usa as funcoes puras acima
# ============================================================

def init_durabilidade(conn):
    """Cria as tabelas e indices (idempotente)."""
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS apostas_ledger (
            id BIGSERIAL PRIMARY KEY,
            ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            acao TEXT NOT NULL,
            user_id TEXT NOT NULL,
            aposta_id TEXT NOT NULL,
            aposta JSONB,
            hash TEXT
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ledger_user_ts ON apostas_ledger(user_id, ts)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ledger_ts ON apostas_ledger(ts)")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS backups_v2 (
            id BIGSERIAL PRIMARY KEY,
            ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            label TEXT,
            hash TEXT,
            total_apostas INT,
            data JSONB NOT NULL
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_backups_v2_ts ON backups_v2(ts)")
    # Ledger de USUARIOS (mesma garantia das apostas, para cadastros/edicoes de conta)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS usuarios_ledger (
            id BIGSERIAL PRIMARY KEY,
            ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            acao TEXT NOT NULL,
            usuario_id TEXT NOT NULL,
            dados JSONB
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_usuarios_ledger_uid ON usuarios_ledger(usuario_id, ts)")
    conn.commit()
    cur.close()


def gravar_eventos_usuarios(cur, eventos):
    """Grava no ledger de usuarios (append-only). Reusa o formato de calcular_eventos:
    ev['aposta_id'] = id do usuario, ev['aposta'] = dict do usuario. Nao faz commit."""
    if not eventos:
        return 0
    from psycopg2.extras import execute_values
    valores = [
        (ev["acao"], ev["aposta_id"],
         json.dumps(ev["aposta"], ensure_ascii=False) if ev["aposta"] is not None else None)
        for ev in eventos
    ]
    execute_values(
        cur,
        "INSERT INTO usuarios_ledger (acao, usuario_id, dados) VALUES %s",
        valores,
        template="(%s, %s, %s::jsonb)"
    )
    return len(eventos)


def gravar_eventos(cur, eventos):
    """Insere os eventos no ledger usando um cursor JA ABERTO (para participar
    da MESMA transacao do save do blob -> atomicidade). Nao faz commit.
    Usa insercao em lote (execute_values) para ser rapido inclusive no bootstrap."""
    if not eventos:
        return 0
    from psycopg2.extras import execute_values  # import local: mantem o modulo testavel sem psycopg2
    valores = [
        (ev["acao"], ev["user_id"], ev["aposta_id"],
         json.dumps(ev["aposta"], ensure_ascii=False) if ev["aposta"] is not None else None,
         hash_bet(ev["aposta"]) if ev["aposta"] is not None else None)
        for ev in eventos
    ]
    execute_values(
        cur,
        "INSERT INTO apostas_ledger (acao, user_id, aposta_id, aposta, hash) VALUES %s",
        valores,
        template="(%s, %s, %s, %s::jsonb, %s)"
    )
    return len(eventos)


def ler_eventos_usuario(conn, user_id, ate_ts=None):
    """Le os eventos de um usuario em ordem cronologica (para reconstrucao)."""
    cur = conn.cursor()
    if ate_ts:
        cur.execute("SELECT acao, aposta_id, aposta FROM apostas_ledger "
                    "WHERE user_id=%s AND ts<=%s ORDER BY id ASC", (user_id, ate_ts))
    else:
        cur.execute("SELECT acao, aposta_id, aposta FROM apostas_ledger "
                    "WHERE user_id=%s ORDER BY id ASC", (user_id,))
    eventos = []
    for acao, aposta_id, aposta in cur.fetchall():
        ap = aposta if isinstance(aposta, (dict, type(None))) else json.loads(aposta)
        eventos.append({"acao": acao, "aposta_id": aposta_id, "aposta": ap})
    cur.close()
    return eventos


def historico_tamanho_usuario(conn, user_id):
    """Devolve [(ts, n_apostas)] mostrando como o numero de apostas do usuario
    evoluiu ao longo do tempo (para o admin enxergar QUANDO caiu)."""
    cur = conn.cursor()
    cur.execute("SELECT ts, acao, aposta_id FROM apostas_ledger "
                "WHERE user_id=%s ORDER BY id ASC", (user_id,))
    estado = set()
    historico = []
    for ts, acao, aposta_id in cur.fetchall():
        if acao in ("criar", "editar"):
            estado.add(aposta_id)
        elif acao == "excluir":
            estado.discard(aposta_id)
        historico.append((ts, len(estado)))
    cur.close()
    return historico


def recuperar_estado_pico(conn, user_id):
    """Reconstrucao de emergencia: devolve (apostas, ts) do momento em que o
    usuario teve o MAIOR numero de apostas. Util para desfazer uma perda
    silenciosa sem precisar adivinhar o timestamp exato."""
    cur = conn.cursor()
    cur.execute("SELECT ts, acao, aposta_id, aposta FROM apostas_ledger "
                "WHERE user_id=%s ORDER BY id ASC", (user_id,))
    estado = {}
    melhor = {}
    melhor_ts = None
    for ts, acao, aposta_id, aposta in cur.fetchall():
        if acao in ("criar", "editar"):
            ap = aposta if isinstance(aposta, (dict, type(None))) else json.loads(aposta)
            estado[aposta_id] = ap
        elif acao == "excluir":
            estado.pop(aposta_id, None)
        if len(estado) > len(melhor):
            melhor = dict(estado)
            melhor_ts = ts
    cur.close()
    return list(melhor.values()), melhor_ts


def cifrar_blob(dados_dict, fernet_key):
    """Serializa o dict e CRIPTOGRAFA com Fernet (AES). Retorna bytes cifrados.
    Sem a chave, o resultado e' ilegivel — seguro para guardar fora (GitHub)."""
    from cryptography.fernet import Fernet
    raw = json.dumps(dados_dict, ensure_ascii=False).encode("utf-8")
    return Fernet(fernet_key).encrypt(raw)


def decifrar_blob(blob_cifrado, fernet_key):
    """Inverso de cifrar_blob: devolve o dict original. Para restaurar um backup."""
    from cryptography.fernet import Fernet
    raw = Fernet(fernet_key).decrypt(blob_cifrado)
    return json.loads(raw.decode("utf-8"))


def enviar_arquivo_github(conteudo_bytes, repo, caminho, token, mensagem):
    """Cria/atualiza um arquivo num repo GitHub (Contents API). Retorna (ok, status)."""
    import requests, base64
    url = f"https://api.github.com/repos/{repo}/contents/{caminho}"
    h = {"Authorization": f"token {token}",
         "Accept": "application/vnd.github+json",
         "User-Agent": "betmanager-backup"}
    sha = None
    try:
        r = requests.get(url, headers=h, timeout=30)
        if r.status_code == 200:
            sha = r.json().get("sha")
    except Exception:
        pass
    body = {"message": mensagem,
            "content": base64.b64encode(conteudo_bytes).decode("ascii")}
    if sha:
        body["sha"] = sha
    r = requests.put(url, headers=h, json=body, timeout=45)
    return (r.status_code in (200, 201)), r.status_code


def criar_backup_v2(conn, snapshot, total_apostas, label=None):
    """Grava um snapshot completo em backups_v2 e aplica a retencao em camadas."""
    cur = conn.cursor()
    lbl = label or datetime.now(timezone.utc).strftime("auto_%Y%m%d_%H%M%S")
    blob = json.dumps(snapshot, ensure_ascii=False)
    h = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
    cur.execute("INSERT INTO backups_v2 (label, hash, total_apostas, data) "
                "VALUES (%s, %s, %s, %s::jsonb)", (lbl, h, total_apostas, blob))
    # retencao
    cur.execute("SELECT id, ts FROM backups_v2")
    rows = cur.fetchall()
    manter = ids_backups_a_manter(rows)
    apagar = [bid for bid, _ in rows if bid not in manter]
    if apagar:
        cur.execute("DELETE FROM backups_v2 WHERE id = ANY(%s)", (apagar,))
    conn.commit()
    cur.close()
    return lbl, h, len(apagar)
