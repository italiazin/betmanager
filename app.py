from flask import Flask, render_template, request, redirect, jsonify, session, url_for
import json
import uuid
import os
import re
import base64
import unicodedata
import calendar
import difflib
from datetime import datetime, timedelta
import requests
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash

import pytesseract
from PIL import Image

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "troque-essa-chave-em-producao")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
ARQUIVO = os.path.join(BASE_DIR, "dados.json")
DADOS_PATH = ARQUIVO
CACHE_API = os.path.join(BASE_DIR, "api_cache.json")
USUARIOS_PATH = os.path.join(BASE_DIR, "usuarios.json")


# ============================================================
# V66 - BANCO DE DADOS
# Usa DATABASE_URL quando existir.
# Guarda dados/usuários em tabela app_store para preservar tudo no Render.
# ============================================================

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
DB_ENGINE = None

def _normalizar_database_url(url):
    if url.startswith("postgres://"):
        return "postgresql+psycopg2://" + url[len("postgres://"):]
    if url.startswith("postgresql://") and "+psycopg2" not in url:
        return "postgresql+psycopg2://" + url[len("postgresql://"):]
    return url


def banco_ativo():
    return bool(DATABASE_URL)


def get_db_engine():
    global DB_ENGINE

    if not banco_ativo():
        return None

    if DB_ENGINE is None:
        DB_ENGINE = create_engine(
            _normalizar_database_url(DATABASE_URL),
            pool_pre_ping=True,
            pool_recycle=280
        )
        inicializar_banco()

    return DB_ENGINE


def inicializar_banco():
    if not DATABASE_URL:
        return

    engine = DB_ENGINE or create_engine(
        _normalizar_database_url(DATABASE_URL),
        pool_pre_ping=True,
        pool_recycle=280
    )

    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS app_store (
                chave TEXT PRIMARY KEY,
                valor JSONB NOT NULL,
                atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))

        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_app_store_chave ON app_store (chave)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_app_store_atualizado ON app_store (atualizado_em)"))


def db_get_json(chave, default):
    if not banco_ativo():
        return default

    try:
        engine = get_db_engine()

        with engine.begin() as conn:
            row = conn.execute(
                text("SELECT valor FROM app_store WHERE chave = :chave"),
                {"chave": chave}
            ).fetchone()

            if not row:
                db_set_json(chave, default)
                return default

            valor = row[0]

            if valor is None:
                return default

            if isinstance(valor, str):
                try:
                    return json.loads(valor)
                except:
                    return default

            return valor

    except Exception as e:
        print("ERRO db_get_json:", chave, repr(e))
        return default


def db_set_json(chave, valor):
    if not banco_ativo():
        return False

    try:
        engine = get_db_engine()

        with engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO app_store (chave, valor, atualizado_em)
                    VALUES (:chave, CAST(:valor AS JSONB), CURRENT_TIMESTAMP)
                    ON CONFLICT (chave)
                    DO UPDATE SET valor = EXCLUDED.valor, atualizado_em = CURRENT_TIMESTAMP
                """),
                {"chave": chave, "valor": json.dumps(valor, ensure_ascii=False)}
            )

        return True

    except Exception as e:
        print("ERRO db_set_json:", chave, repr(e))
        return False


def migrar_json_para_banco_se_vazio():
    if not banco_ativo():
        return

    try:
        engine = get_db_engine()

        with engine.begin() as conn:
            row_dados = conn.execute(text("SELECT 1 FROM app_store WHERE chave = 'dados'")).fetchone()
            row_usuarios = conn.execute(text("SELECT 1 FROM app_store WHERE chave = 'usuarios'")).fetchone()

        if not row_dados and os.path.exists(DADOS_PATH):
            with open(DADOS_PATH, "r", encoding="utf-8") as f:
                db_set_json("dados", json.load(f))

        if not row_usuarios and os.path.exists(USUARIOS_PATH):
            with open(USUARIOS_PATH, "r", encoding="utf-8") as f:
                db_set_json("usuarios", json.load(f))

    except Exception as e:
        print("ERRO migrar_json_para_banco:", repr(e))

    try:
        # Se banco ainda não tem dados, importa dos JSONs locais.
        dados_db = db_get_json("dados", None)
        usuarios_db = db_get_json("usuarios", None)

        if dados_db is None and os.path.exists(DADOS_PATH):
            with open(DADOS_PATH, "r", encoding="utf-8") as f:
                db_set_json("dados", json.load(f))

        if usuarios_db is None and os.path.exists(USUARIOS_PATH):
            with open(USUARIOS_PATH, "r", encoding="utf-8") as f:
                db_set_json("usuarios", json.load(f))

    except Exception as e:
        print("ERRO migrar_json_para_banco:", repr(e))


CACHE_RESULTADOS = {}
CACHE_EVENTOS = {}
CACHE_ESTATISTICAS = {}

try:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        CONFIG = json.load(f)
except:
    CONFIG = {"API_KEY": ""}

API_KEY = CONFIG.get("API_KEY", "")

print("CONFIG PATH:", CONFIG_PATH)
print("API KEY:", API_KEY)
print("VERSAO_CARREGADA: OCR_CLIENTE_V70_ADMIN_LOGIN_FORCE")

if os.name == "nt":
    tess_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if os.path.exists(tess_path):
        pytesseract.pytesseract.tesseract_cmd = tess_path


CASAS_DISPONIVEIS = [
    "1Xbet", "4Win", "4play", "7Games", "7K", "A247", "Ai", "Alfa",
    "Aposta Ganha", "Aposta1", "ApostaTudo", "Apostou", "Aviaobet",
    "B2xBet", "BETesporte", "BRBET", "BandBet", "Bateu", "Bet Aki",
    "Bet Do Milhão", "Bet Falcons", "Bet dá Sorte", "BetFusion",
    "BetGorillas", "BetMGM", "BetPix365", "Betano", "Betao", "Betboo",
    "Betboom", "Betbra", "Betespecial", "Betfair", "Betnacional",
    "Betou", "Betsson", "Betsul", "Betvip", "Betwarrior", "BigBet",
    "Bingo", "Blaze", "Bolsa De Aposta", "Br4BET", "Brasil da Sorte",
    "Brasil.Bet", "BravoBet", "BrxBet", "BullsBet", "CBesportes",
    "Casa de Apostas", "Cassino", "Donald Bet", "DonosDaBola",
    "Esportes da Sorte", "Esportiva", "Esportivavip", "EstrelaBet",
    "F12", "FlaBet", "FullTBet", "Fullbet", "Galera Bet", "Ganhei",
    "Ganhei Bet", "GingaBet", "GoldeBet", "H2bet", "Hiperbet",
    "Jogajunto", "Jogo de Ouro", "Jogão", "KTO", "KingPanda",
    "Lance de Sorte", "Lotogreen", "Lottoland", "Lottu", "Luva.Bet",
    "Líderbet", "MMABet", "Matchbook", "MaximaBet", "McGames",
    "Meridianbet", "Milhao", "Mr. Jack", "MultiBet", "Nossabet",
    "Novibet", "Oleybet", "Pagol", "Papigames", "Pixbet", "Play",
    "Play bet", "Playbet", "Qgbet", "R7.BET", "Reals", "Rei do Pitaco",
    "Seguro", "SeuBet", "Sortenabet", "Spin", "Sportingbet", "Stake",
    "Superbet", "Suprema Bet", "Tivo Bet", "ULTRA", "Upbet", "VBET",
    "VERSUSbet", "Vaidebet", "Vera", "Viva Sorte", "Vupi", "Zeroum",
    "bet365", "betfast", "betpontobet", "faz1bet", "ganhei.bet.br",
    "jogajunto.bet.br", "play.bet.br", "uxbet"
]

ESPORTES_DISPONIVEIS = [
    "Atletismo", "Basquete", "Beisebol", "Boxe", "Ciclismo", "Dardos",
    "Futebol", "Futebol Americano", "Futsal", "Fórmula 1", "Handeball",
    "Hóquei no Gelo", "MMA", "Outros Esportes", "Polo Aquático",
    "Sinuca", "Tênis", "Tênis de Mesa", "Vários", "Vôlei", "eSports",
    "Golfe", "League of Legends"
]


def carregar():
    dados_padrao = {
        "banca_inicial": 1000,
        "bets": [],
        "saldo_casas": {},
        "saldo_casas_por_usuario": {},
        "movimentacoes_casas_por_usuario": {}
    }

    if banco_ativo():
        migrar_json_para_banco_se_vazio()
        dados_db = db_get_json("dados", dados_padrao) or dados_padrao
        dados_db.setdefault("banca_inicial", 1000)
        dados_db.setdefault("bets", [])
        dados_db.setdefault("saldo_casas", {})
        dados_db.setdefault("saldo_casas_por_usuario", {})
        dados_db.setdefault("movimentacoes_casas_por_usuario", {})

        for b in dados_db.get("bets", []):
            b.setdefault("id", str(uuid.uuid4()))
            b.setdefault("origem", "manual")
            b.setdefault("casa", "")
            b.setdefault("esporte", "")
            b.setdefault("jogo", "")
            b.setdefault("mercado", "Outro")
            b.setdefault("direcao", "")
            b.setdefault("linha", None)
            b.setdefault("periodo", "jogo inteiro")
            b.setdefault("selecao", "")
            b.setdefault("btts_resposta", "")
            b.setdefault("api_status", "")
            b.setdefault("texto_bruto", "")
            b.setdefault("texto_interpretado", "")
            b.setdefault("itens_multipla", {})
            b.setdefault("itens_multipla_detalhados", [])
            b.setdefault("saldo_debitado", False)
            b.setdefault("saldo_creditado_estado", "")
            b.setdefault("saldo_creditado_valor", 0.0)
            b.setdefault("publica", False)

        return dados_db

    if not os.path.exists(DADOS_PATH):
        with open(DADOS_PATH, "w", encoding="utf-8") as f:
            json.dump(dados_padrao, f, indent=4, ensure_ascii=False)

    with open(DADOS_PATH, "r", encoding="utf-8") as f:
        try:
            dados_local = json.load(f)
        except:
            dados_local = dados_padrao

    # Compatibilidade caso dados.json antigo seja lista.
    if isinstance(dados_local, list):
        dados_local = {"banca_inicial": 1000, "bets": dados_local}

    dados_local.setdefault("banca_inicial", 1000)
    dados_local.setdefault("bets", [])
    dados_local.setdefault("saldo_casas", {})
    dados_local.setdefault("saldo_casas_por_usuario", {})
    dados_local.setdefault("movimentacoes_casas_por_usuario", {})

    for b in dados_local.get("bets", []):
        b.setdefault("id", str(uuid.uuid4()))
        b.setdefault("origem", "manual")
        b.setdefault("casa", "")
        b.setdefault("esporte", "")
        b.setdefault("jogo", "")
        b.setdefault("mercado", "Outro")
        b.setdefault("direcao", "")
        b.setdefault("linha", None)
        b.setdefault("periodo", "jogo inteiro")
        b.setdefault("selecao", "")
        b.setdefault("btts_resposta", "")
        b.setdefault("api_status", "")
        b.setdefault("texto_bruto", "")
        b.setdefault("texto_interpretado", "")
        b.setdefault("itens_multipla", {})
        b.setdefault("itens_multipla_detalhados", [])
        b.setdefault("saldo_debitado", False)
        b.setdefault("saldo_creditado_estado", "")
        b.setdefault("saldo_creditado_valor", 0.0)
        b.setdefault("publica", False)

    return dados_local

def salvar():
    if banco_ativo():
        db_set_json("dados", dados)
        return

    with open(DADOS_PATH, "w", encoding="utf-8") as f:
        json.dump(dados, f, indent=4, ensure_ascii=False)

def carregar_cache():
    try:
        with open(CACHE_API, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"teams": {}}


def salvar_cache(cache):
    with open(CACHE_API, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=4, ensure_ascii=False)


dados = carregar()


# ============================================================
# V61 - REFORÇO DE SEGURANÇA MULTIUSUÁRIO
# ============================================================

def is_admin_atual():
    u = usuario_logado()
    return bool(u and u.get("is_admin"))


def bet_pertence_usuario_v61(b, uid=None):
    uid = uid or session.get("user_id", "")
    return bool(uid and b.get("user_id") == uid)


def bets_do_usuario_v61():
    uid = session.get("user_id", "")
    return [b for b in dados.get("bets", []) if bet_pertence_usuario_v61(b, uid)]


def buscar_aposta_segura_v61(bet_id):
    for b in dados.get("bets", []):
        if b.get("id") == bet_id:
            if bet_pertence_usuario_v61(b) or is_admin_atual():
                return b
            return None
    return None


def saldo_casas_usuario_v61():
    uid = session.get("user_id", "")
    return dados.setdefault("saldo_casas_por_usuario", {}).setdefault(uid, {})


def movimentacoes_usuario_v61():
    uid = session.get("user_id", "")
    return dados.setdefault("movimentacoes_casas_por_usuario", {}).setdefault(uid, [])


def total_saldos_casas_v61():
    return round(sum(float(v or 0) for v in saldo_casas_usuario_v61().values()), 2)


@app.context_processor
def inject_usuario():
    return {
        "usuario": usuario_logado(),
        "usuario_inicial": ((usuario_logado() or {}).get("nome", "U")[:1].upper()),
        "assinatura_ativa_usuario": assinatura_ativa_usuario if "assinatura_ativa_usuario" in globals() else (lambda: False),
        "aposta_publica_padrao_usuario": aposta_publica_padrao_usuario if "aposta_publica_padrao_usuario" in globals() else (lambda: False)
    }



# ============================================================
# V49 - CAMADA DE ESTABILIZAÇÃO GLOBAL
# Garante funções essenciais mesmo se patches anteriores quebraram ordem/definição.
# ============================================================

def usuario_id_atual():
    try:
        return session.get("user_id") or ""
    except Exception:
        return ""


def usuario_logado():
    try:
        uid = session.get("user_id")
    except Exception:
        uid = None

    if not uid:
        return None

    try:
        usuarios = carregar_usuarios()
        for u in usuarios.get("users", []):
            if u.get("id") == uid:
                u.setdefault("ativo", True)
                u.setdefault("assinatura_ativa", bool(u.get("is_admin", False)))
                u.setdefault("plano", "admin" if u.get("is_admin") else "free")
                u.setdefault("apostas_publicas_padrao", False)
                return u
    except Exception:
        return None

    return None


def assinatura_ativa_usuario():
    try:
        u = usuario_logado()
        return bool(u and (u.get("is_admin") or u.get("assinatura_ativa")))
    except Exception:
        return False


def aposta_publica_padrao_usuario():
    u = usuario_logado()
    return bool(u and u.get("apostas_publicas_padrao", False))



def bet_pertence_usuario(b, uid=None):
    uid = uid or usuario_id_atual()

    if not b.get("user_id"):
        u = usuario_logado()
        return bool(u and u.get("is_admin"))

    return b.get("user_id") == uid


def bets_do_usuario():
    try:
        uid = usuario_id_atual()
        return [b for b in dados.get("bets", []) if bet_pertence_usuario(b, uid)]
    except Exception:
        return []


def saldo_casas_usuario():
    try:
        uid = usuario_id_atual()
        saldos_por_usuario = dados.setdefault("saldo_casas_por_usuario", {})
        if uid not in saldos_por_usuario:
            saldos_por_usuario[uid] = {}
        return saldos_por_usuario.setdefault(uid, {})
    except Exception:
        return {}


def movimentacoes_usuario():
    try:
        uid = usuario_id_atual()
        movs = dados.setdefault("movimentacoes_casas_por_usuario", {})
        return movs.setdefault(uid, [])
    except Exception:
        return []


def encontrar_chave_saldo_casa(casa):
    try:
        casa = limpar_casa(casa or "")
    except Exception:
        casa = str(casa or "").strip()

    if not casa:
        return ""

    try:
        alvo = normalizar_nome(casa)
        for k in saldo_casas_usuario().keys():
            if normalizar_nome(k) == alvo:
                return k
    except Exception:
        pass

    return casa


def get_saldo_casa(casa):
    chave = encontrar_chave_saldo_casa(casa)
    if not chave:
        return 0.0
    return float(saldo_casas_usuario().get(chave, 0.0))


def set_saldo_casa(casa, valor):
    chave = encontrar_chave_saldo_casa(casa)
    if chave:
        saldo_casas_usuario()[chave] = round(float(valor or 0), 2)


def alterar_saldo_casa(casa, delta):
    chave = encontrar_chave_saldo_casa(casa)
    if chave:
        saldos = saldo_casas_usuario()
        saldos[chave] = round(float(saldos.get(chave, 0.0)) + float(delta or 0), 2)


def total_saldos_casas():
    try:
        return round(sum(float(v or 0) for v in saldo_casas_usuario().values()), 2)
    except Exception:
        return 0.0


def calcular_lucro(b):
    estado = b.get("estado", "")
    odd = float(b.get("odd", 0) or 0)
    valor = float(b.get("valor", 0) or 0)

    if estado == "ganha":
        return round((odd - 1) * valor, 2)

    if estado == "perdida":
        return round(-valor, 2)

    return 0


def recalcular():
    for b in dados.get("bets", []):
        try:
            b["lucro"] = calcular_lucro(b)
        except Exception:
            b["lucro"] = 0


def retorno_por_estado_saldo(b):
    estado = b.get("estado", "")
    odd = float(b.get("odd", 0) or 0)
    valor = float(b.get("valor", 0) or 0)

    if estado == "ganha":
        return round(odd * valor, 2)

    if estado == "anulada":
        return round(valor, 2)

    return 0.0


def debitar_stake_saldo_casa(b):
    if b.get("saldo_debitado"):
        return

    casa = b.get("casa", "")
    valor = float(b.get("valor", 0) or 0)

    if casa and valor > 0:
        alterar_saldo_casa(casa, -valor)
        b["saldo_debitado"] = True


def remover_credito_resultado_saldo(b):
    casa = b.get("casa", "")
    credito_antigo = float(b.get("saldo_creditado_valor", 0) or 0)

    if casa and credito_antigo:
        alterar_saldo_casa(casa, -credito_antigo)

    b["saldo_creditado_estado"] = ""
    b["saldo_creditado_valor"] = 0.0


def aplicar_credito_resultado_saldo(b):
    casa = b.get("casa", "")
    credito = retorno_por_estado_saldo(b)

    if casa and credito:
        alterar_saldo_casa(casa, credito)

    b["saldo_creditado_estado"] = b.get("estado", "")
    b["saldo_creditado_valor"] = round(float(credito or 0), 2)


def registrar_nova_aposta_saldo(b):
    b.setdefault("saldo_debitado", False)
    b.setdefault("saldo_creditado_estado", "")
    b.setdefault("saldo_creditado_valor", 0.0)
    debitar_stake_saldo_casa(b)

    if b.get("estado"):
        aplicar_credito_resultado_saldo(b)


def atualizar_resultado_saldo(b, novo_estado):
    b.setdefault("saldo_debitado", False)
    b.setdefault("saldo_creditado_estado", "")
    b.setdefault("saldo_creditado_valor", 0.0)

    debitar_stake_saldo_casa(b)
    remover_credito_resultado_saldo(b)

    b["estado"] = novo_estado
    b["lucro"] = calcular_lucro(b)

    aplicar_credito_resultado_saldo(b)


def preparar_edicao_saldo_snapshot(b):
    return {
        "casa": b.get("casa", ""),
        "valor": float(b.get("valor", 0) or 0),
        "estado": b.get("estado", ""),
        "saldo_debitado": bool(b.get("saldo_debitado", False)),
        "saldo_creditado_valor": float(b.get("saldo_creditado_valor", 0) or 0)
    }


def reverter_saldo_snapshot(snapshot):
    casa = snapshot.get("casa", "")
    if not casa:
        return

    credito = float(snapshot.get("saldo_creditado_valor", 0) or 0)
    if credito:
        alterar_saldo_casa(casa, -credito)

    if snapshot.get("saldo_debitado"):
        alterar_saldo_casa(casa, float(snapshot.get("valor", 0) or 0))


def reaplicar_saldo_apos_edicao(b):
    b["saldo_debitado"] = False
    b["saldo_creditado_estado"] = ""
    b["saldo_creditado_valor"] = 0.0
    registrar_nova_aposta_saldo(b)


def registrar_movimentacao_casa(casa, tipo, valor, descricao=""):
    if not casa or not valor:
        return

    try:
        casa_limpa = limpar_casa(casa)
    except Exception:
        casa_limpa = str(casa or "").strip()

    movimentacoes_usuario().append({
        "id": str(uuid.uuid4()),
        "data": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "casa": casa_limpa,
        "tipo": tipo,
        "valor": round(float(valor or 0), 2),
        "descricao": descricao
    })


def aplicar_movimento_manual_casa(casa, tipo, valor, destino=""):
    try:
        casa = limpar_casa(casa)
        destino = limpar_casa(destino)
    except Exception:
        casa = str(casa or "").strip()
        destino = str(destino or "").strip()

    valor = float(valor or 0)

    if not casa or valor <= 0:
        return

    if tipo == "deposito":
        alterar_saldo_casa(casa, valor)
        registrar_movimentacao_casa(casa, "Depósito", valor, "Entrada manual")

    elif tipo == "saque":
        alterar_saldo_casa(casa, -valor)
        registrar_movimentacao_casa(casa, "Saque", -valor, "Saída manual")

    elif tipo == "bonus":
        alterar_saldo_casa(casa, valor)
        registrar_movimentacao_casa(casa, "Bônus", valor, "Crédito de bônus")

    elif tipo == "transferencia" and destino:
        alterar_saldo_casa(casa, -valor)
        alterar_saldo_casa(destino, valor)
        registrar_movimentacao_casa(casa, "Transferência enviada", -valor, f"Para {destino}")
        registrar_movimentacao_casa(destino, "Transferência recebida", valor, f"De {casa}")


def limpar_aposta_display_v39(b):
    b2 = dict(b)
    jogo = str(b2.get("jogo", "") or "").strip()
    aposta = str(b2.get("aposta", "") or "").strip()

    if jogo and aposta.lower().startswith((jogo + " - ").lower()):
        b2["aposta_display"] = aposta[len(jogo) + 3:].strip()
    else:
        b2["aposta_display"] = aposta

    return b2


def bets_display_v39():
    return [limpar_aposta_display_v39(b) for b in list(reversed(bets_do_usuario()))]


def ultimas_apostas_comunidade_base(limit=10):
    bets = list(reversed(dados.get("bets", [])))
    saida = []

    for b in bets:
        if len(saida) >= limit:
            break
        if not b.get("publica", False):
            continue

        bd = limpar_aposta_display_v39(b)
        saida.append({
            "id": bd.get("id", ""),
            "data": bd.get("data", ""),
            "casa": bd.get("casa", ""),
            "esporte": bd.get("esporte", ""),
            "jogo": bd.get("jogo", ""),
            "aposta": bd.get("aposta_display") or bd.get("aposta", ""),
            "odd": bd.get("odd", ""),
            "valor": bd.get("valor", "")
        })

    return saida


def buscar_aposta(bet_id):
    return buscar_aposta_segura_v61(bet_id)

def remover_emojis(texto):
    texto = "".join(
        ch for ch in str(texto)
        if not unicodedata.category(ch).startswith("So")
    )
    texto = re.sub(r"[^\w\sÀ-ÿ.,:%/+\-$xX]", "", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def limpar_casa(texto):
    texto = remover_emojis(texto)
    texto = re.sub(r"[^A-Za-zÀ-ÿ0-9.\s]", "", texto)
    return texto.strip()


def limpar_linha(texto):
    return remover_emojis(texto).strip()


def normalizar_nome(texto):
    texto = str(texto).lower()
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(ch for ch in texto if unicodedata.category(ch) != "Mn")
    texto = re.sub(r"[^a-z0-9\s]", "", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def nome_bate(a, b):
    a = normalizar_nome(a)
    b = normalizar_nome(b)

    if not a or not b:
        return False

    return a in b or b in a


def extrair_linha(texto):
    texto = str(texto).lower().replace(",", ".")
    match = re.search(r"\d+(\.\d+)?", texto)
    return float(match.group(0)) if match else None


def extrair_times_jogo(jogo):
    texto = str(jogo)

    separadores = [" x ", " vs ", " v ", " - "]

    for sep in separadores:
        if sep.lower() in texto.lower():
            partes = re.split(sep, texto, flags=re.IGNORECASE)
            if len(partes) >= 2:
                return partes[0].strip(), partes[1].strip()

    return "", ""


def texto_tem(texto_norm, padroes):
    return any(p in texto_norm for p in padroes)


def detectar_periodo(texto):
    t = normalizar_nome(texto)

    if texto_tem(t, [
        "vence o ht", "vence ht", "ht", "1h", "1t", "1 tempo",
        "primeiro tempo", "first half", "half time", "intervalo"
    ]):
        return "1º tempo"

    if texto_tem(t, [
        "2t", "2 tempo", "segundo tempo", "second half", "2h"
    ]):
        return "2º tempo"

    return "jogo inteiro"


def detectar_direcao(texto):
    texto_original = str(texto)
    t = normalizar_nome(texto_original)

    padroes_under = [
        "under",
        "menos de",
        "abaixo de",
        "menor que",
        "menos gols",
        "menos pontos",
        "total abaixo",
        "total menor",
        "under gols",
        "under goals"
    ]

    if any(p in t for p in padroes_under):
        return "under"

    if re.search(r"\bu\s*\d+([\.,]\d+)?\b", texto_original.lower()):
        return "under"

    if re.search(r"(^|\s)-\s*\d+([\.,]\d+)?", texto_original.lower()):
        return "under"

    padroes_over = [
        "over",
        "mais de",
        "acima de",
        "maior que",
        "mais gols",
        "mais pontos",
        "total acima",
        "total maior",
        "over gols",
        "over goals"
    ]

    if any(p in t for p in padroes_over):
        return "over"

    if re.search(r"\bo\s*\d+([\.,]\d+)?\b", texto_original.lower()):
        return "over"

    if re.search(r"(^|\s)\+\s*\d+([\.,]\d+)?", texto_original.lower()):
        return "over"

    return ""


def detectar_btts_resposta(texto):
    t = normalizar_nome(texto)

    # =========================
    # BTTS NÃO / AMBAS NÃO MARCAM
    # Prioridade absoluta: NÃO vem antes de SIM.
    # =========================
    padroes_nao = [
        "ambas marcam nao",
        "ambos marcam nao",
        "ambas equipes marcam nao",
        "ambas equipes para marcar nao",
        "ambas equipes nao marcam",
        "ambas equipes nao para marcar",
        "as duas marcam nao",
        "os dois marcam nao",
        "os 2 marcam nao",
        "ambos times marcam nao",
        "ambas times marcam nao",
        "ambas as equipes marcam nao",
        "ambas as equipes para marcar nao",
        "both teams to score no",
        "both team to score no",
        "both teams no",
        "btts no",
        "bbts no",
        "bts no",
        "gg nao",
        "gg no",
        "ng",
        "no goal",
        "no goals",
        "nao ambas marcam",
        "nao ambas equipes marcam",
        "nao ambas equipes para marcar",
        "nao as duas marcam",
        "sem ambas marcam"
    ]

    if any(p in t for p in padroes_nao):
        return "nao"

    if re.search(r"\bnao\b", t) and (
        "ambas" in t
        or "ambos" in t
        or "btts" in t
        or "bbts" in t
        or "bts" in t
        or "both teams" in t
        or "as duas" in t
        or "os dois" in t
    ):
        return "nao"

    if re.search(r"\bno\b", t) and (
        "btts" in t
        or "bbts" in t
        or "bts" in t
        or "both teams" in t
        or "both team" in t
    ):
        return "nao"

    # =========================
    # BTTS SIM / AMBAS MARCAM
    # =========================
    padroes_sim = [
        "ambas marcam",
        "ambos marcam",
        "ambas equipes marcam",
        "ambas equipes para marcar",
        "ambas equipes a marcar",
        "ambas as equipes marcam",
        "ambas as equipes para marcar",
        "ambas equipas marcam",
        "ambas equipas para marcar",
        "ambos times marcam",
        "os dois times marcam",
        "os 2 times marcam",
        "os dois marcam",
        "os 2 marcam",
        "as duas marcam",
        "as 2 marcam",
        "cada equipe marca",
        "cada equipa marca",
        "cada time marca",
        "gols para ambas",
        "gol para ambas",
        "both teams to score",
        "both team to score",
        "both teams score",
        "both teams yes",
        "btts yes",
        "bbts yes",
        "bts yes",
        "btts sim",
        "bbts sim",
        "bts sim",
        "sim ambas marcam",
        "sim ambas equipes",
        "sim ambas equipes para marcar",
        "sim as duas marcam",
        "gg"
    ]

    if any(p in t for p in padroes_sim):
        return "sim"

    # Casos tipo "Sim / Ambas Marcam", "Sim - Ambas equipes para marcar"
    if re.search(r"\bsim\b", t) and (
        "ambas" in t
        or "ambos" in t
        or "btts" in t
        or "bbts" in t
        or "bts" in t
        or "as duas" in t
        or "os dois" in t
        or "both teams" in t
    ):
        return "sim"

    if re.search(r"\byes\b", t) and (
        "btts" in t
        or "bbts" in t
        or "bts" in t
        or "both teams" in t
        or "both team" in t
    ):
        return "sim"

    return ""


def eh_texto_btts(texto):
    t = normalizar_nome(texto)

    gatilhos = [
        "ambas marcam",
        "ambos marcam",
        "ambas equipes",
        "ambas equipas",
        "ambas as equipes",
        "ambas as equipas",
        "as duas marcam",
        "as 2 marcam",
        "os dois marcam",
        "os 2 marcam",
        "os dois times marcam",
        "os 2 times marcam",
        "ambos times marcam",
        "ambas equipes para marcar",
        "ambas equipes a marcar",
        "ambas equipas para marcar",
        "cada equipe marca",
        "cada equipa marca",
        "cada time marca",
        "gols para ambas",
        "gol para ambas",
        "both teams to score",
        "both team to score",
        "both teams score",
        "both teams yes",
        "both teams no",
        "no goal",
        "no goals",
    ]

    if any(g in t for g in gatilhos):
        return True

    if re.search(r"\bbtts\b", t):
        return True

    if re.search(r"\bbbts\b", t):
        return True

    if re.search(r"\bbts\b", t):
        return True

    # GG = ambas sim, NG = ambas não
    if re.search(r"\bgg\b", t):
        return True

    if re.search(r"\bng\b", t):
        return True

    # Casos tipo "Sim / Ambas..." ou "Não / Ambas..."
    if (re.search(r"\bsim\b", t) or re.search(r"\bnao\b", t)) and (
        "ambas" in t or "ambos" in t or "as duas" in t or "os dois" in t
    ):
        return True

    return False


def detectar_mercado(texto):
    return interpretar_aposta(texto).get("mercado", "Outro")


def extrair_selecao(texto, jogo=""):
    t_original = str(texto)
    t = normalizar_nome(t_original)

    casa, fora = extrair_times_jogo(jogo)

    if re.search(r"\bfora\b", t) and fora:
        return fora

    if (re.search(r"\bcasa\b", t) or "mandante" in t) and casa:
        return casa

    if t in ["empate", "draw", "x"]:
        return "Empate"

    selecao = t_original

    remover_regex = [
        r"\b(sim|nao|não|yes|no|ng|gg)\b",
        r"\d+\s*[:xX-]\s*",
        r"\b(resultado final|resultado|final|1x2)\b",
        r"\b(vence o ht|vence ht|vence o 1º tempo|vence primeiro tempo|vence o primeiro tempo)\b",
        r"\b(ml|moneyline|vence|vencedor|winner|win|para vencer|ganha o jogo)\b",
        r"\b(fora|casa|mandante|visitante)\b",
        r"\b(ht|1h|1t|1º tempo|1 tempo|primeiro tempo|first half|half time|intervalo)\b",
        r"\b(2t|2h|2º tempo|2 tempo|segundo tempo|second half)\b",
    ]

    for rgx in remover_regex:
        selecao = re.sub(rgx, " ", selecao, flags=re.IGNORECASE)

    selecao = re.sub(r"[:/|()\[\]{}]", " ", selecao)
    selecao = re.sub(r"\s+", " ", selecao).strip(" -/|:")

    return selecao



def detectar_dupla_chance_selecao(texto):
    t = normalizar_nome(texto)

    # Ordem importa: detectar expressões explícitas
    if re.search(r"\b1x\b", t) or "casa ou empate" in t or "mandante ou empate" in t:
        return "1X"

    if re.search(r"\bx2\b", t) or "empate ou fora" in t or "visitante ou empate" in t:
        return "X2"

    if re.search(r"\b12\b", t) or "casa ou fora" in t or "sem empate" in t or "empate nao" in t or "empate não" in str(texto).lower():
        return "12"

    return ""


def limpar_nome_jogador(texto):
    jogador = limpar_linha(texto)

    remover_frases = [
        "tem 1 ou mais chutes a gol",
        "tem 1 ou mais chutes gol",
        "tem 1 ou mais chutes no gol",
        "tem um ou mais chutes a gol",
        "tem um ou mais chutes gol",
        "tem um ou mais chutes no gol",
        "1 ou mais chutes a gol",
        "1 ou mais chutes gol",
        "1 ou mais chutes no gol",
        "um ou mais chutes a gol",
        "um ou mais chutes gol",
        "um ou mais chutes no gol",
    ]

    for frase in remover_frases:
        jogador = re.sub(rf"\b{re.escape(frase)}\b", " ", jogador, flags=re.I)

    remover = [
        "jogador", "player", "marcador", "marca", "marcar", "marcou",
        "gol", "gols", "a qualquer momento", "anytime", "assistencia",
        "assistência", "assistir", "assists", "assist", "para marcar",
        "para dar assistencia", "para dar assistência", "dar assistencia",
        "dar assistência", "shot on target", "chute a gol", "chutes a gol",
        "chutes gol", "chute gol", "chutes no gol", "chute no gol"
    ]

    for termo in remover:
        jogador = re.sub(rf"\b{re.escape(termo)}\b", " ", jogador, flags=re.I)

    jogador = re.sub(r"\b(tem|ou|mais|sim|nao|não|yes|no|over|under|mais de|menos de)\b", " ", jogador, flags=re.I)
    jogador = re.sub(r"\d+[,.]?\d*", " ", jogador)
    jogador = re.sub(r"[:/|()\[\]{}+\-]", " ", jogador)
    jogador = re.sub(r"\s+", " ", jogador).strip()

    return jogador


def detectar_jogador_mercado(texto):
    t = normalizar_nome(texto)

    if texto_tem(t, [
        "assistencia", "assistência", "assist", "assists",
        "dar assistencia", "dar assistência", "para dar assistencia", "para dar assistência"
    ]):
        return "Assistência"

    if texto_tem(t, [
        "marcador", "jogador marca", "jogador marcar", "para marcar",
        "marca a qualquer momento", "marcar a qualquer momento",
        "anytime goalscorer", "to score", "gol do jogador"
    ]):
        return "Marcador"

    return ""


def interpretar_aposta(texto_aposta, jogo=""):
    texto = str(texto_aposta or "")
    t = normalizar_nome(texto)

    info = {
        "mercado": "Outro",
        "direcao": "",
        "linha": None,
        "periodo": detectar_periodo(texto),
        "selecao": "",
        "btts_resposta": ""
    }

    # =========================
    # BTTS / AMBAS MARCAM
    # =========================
    if eh_texto_btts(texto):
        info["mercado"] = "Ambas Marcam"
        info["btts_resposta"] = detectar_btts_resposta(texto) or "sim"
        info["selecao"] = info["btts_resposta"]
        info["linha"] = None
        return info

    direcao = detectar_direcao(texto)
    linha = extrair_linha(texto)


    # =========================
    # JOGADOR CHUTES / CHUTES NO GOL
    # =========================
    if texto_tem(t, [
        "tem 1 ou mais chutes", "tem um ou mais chutes", "1 ou mais chutes",
        "um ou mais chutes", "chutes gol", "chute gol", "chutes a gol",
        "chute a gol", "chutes no gol", "chute no gol",
        "shots on target", "shot on target"
    ]):
        info["mercado"] = "Jogador Chutes no Gol" if ("gol" in t or "target" in t) else "Jogador Chutes"
        info["direcao"] = "over"
        info["selecao"] = limpar_nome_jogador(texto)
        info["linha"] = extrair_linha(texto) or 0.5
        return info

    # =========================
    # DUPLA CHANCE
    # =========================
    if texto_tem(t, ["dupla chance", "double chance"]) or detectar_dupla_chance_selecao(texto):
        info["mercado"] = "Dupla Chance"
        info["selecao"] = detectar_dupla_chance_selecao(texto)
        info["linha"] = None
        return info

    # =========================
    # MARCADOR / ASSISTÊNCIA
    # =========================
    mercado_jogador = detectar_jogador_mercado(texto)
    if mercado_jogador:
        info["mercado"] = mercado_jogador
        info["selecao"] = limpar_nome_jogador(texto)
        info["linha"] = None
        return info

    # =========================
    # CHUTES A GOL / CHUTES
    # =========================
    if texto_tem(t, [
        "chutes a gol", "chute a gol", "chutes no gol", "chute no gol",
        "finalizacoes no gol", "finalizações no gol",
        "remates a baliza", "remates no alvo", "shots on target",
        "total shots on target", "sot"
    ]):
        info["mercado"] = "Chutes no Gol"
        info["direcao"] = direcao
        info["selecao"] = direcao
        info["linha"] = linha
        return info

    if texto_tem(t, [
        "chutes", "chute", "finalizacoes", "finalizações",
        "finalizacoes totais", "finalizações totais",
        "remates", "shots", "total shots"
    ]):
        info["mercado"] = "Chutes"
        info["direcao"] = direcao
        info["selecao"] = direcao
        info["linha"] = linha
        return info

    # =========================
    # ESCANTEIOS
    # =========================
    if texto_tem(t, ["escanteio", "escanteios", "corner", "corners", "cantos"]):
        info["mercado"] = "Escanteios"
        info["direcao"] = direcao
        info["selecao"] = direcao
        info["linha"] = linha
        return info

    # =========================
    # CARTÕES
    # =========================
    if texto_tem(t, ["cartao", "cartoes", "cartão", "cartões", "card", "cards", "yellow cards", "red cards"]):
        info["mercado"] = "Cartões"
        info["direcao"] = direcao
        info["selecao"] = direcao
        info["linha"] = linha
        return info

    # =========================
    # TOTAL / OVER UNDER GOLS
    # =========================
    if direcao:
        info["mercado"] = "Total"
        info["direcao"] = direcao
        info["selecao"] = direcao
        info["linha"] = linha
        return info

    if texto_tem(t, ["total de gols", "gols", "goals"]):
        info["mercado"] = "Total de Gols"
        info["direcao"] = direcao
        info["selecao"] = direcao
        info["linha"] = linha
        return info

    # =========================
    # MONEYLINE / RESULTADO FINAL
    # =========================
    if (
        texto_tem(t, [
            "resultado final", "moneyline", "vencedor", "winner", "para vencer",
            "ganha o jogo", "vence", "fora", "casa", "mandante", "visitante"
        ])
        or re.search(r"\bml\b", t)
        or re.search(r"\b1x2\b", t)
        or info["periodo"] in ["1º tempo", "2º tempo"]
        or t in ["empate", "draw", "x"]
    ):
        info["mercado"] = "Moneyline"
        info["selecao"] = extrair_selecao(texto, jogo)

        if normalizar_nome(info["selecao"]) in ["", "resultado final", "resultado", "final"]:
            casa, fora = extrair_times_jogo(jogo)

            if casa and normalizar_nome(casa) in t:
                info["selecao"] = casa
            elif fora and normalizar_nome(fora) in t:
                info["selecao"] = fora

        return info

    # =========================
    # OUTROS
    # =========================
    if texto_tem(t, ["handicap", "hdp", "asian handicap", "ah", "spread"]):
        info["mercado"] = "Handicap"
        info["linha"] = linha
        return info

    if texto_tem(t, ["draw no bet", "dnb", "empate anula"]):
        info["mercado"] = "Empate Anula"
        info["selecao"] = extrair_selecao(texto, jogo)
        return info

    return info


def eh_aposta_btts(aposta):
    return aposta.get("mercado", "") == "Ambas Marcam" or eh_texto_btts(aposta.get("aposta", "")) or eh_texto_btts(aposta.get("selecao", ""))


def detectar_btts_resposta_aposta(aposta):
    texto_total = " ".join([
        str(aposta.get("aposta", "")),
        str(aposta.get("selecao", "")),
        str(aposta.get("btts_resposta", ""))
    ])
    return detectar_btts_resposta(texto_total) or "sim"


def preparar_aposta_para_validacao(b):
    aposta = dict(b)
    texto = aposta.get("aposta", "")
    jogo = aposta.get("jogo", "")

    cls = interpretar_aposta(texto, jogo)

    if cls.get("mercado") != "Outro":
        aposta["mercado"] = cls.get("mercado", aposta.get("mercado", ""))
        aposta["direcao"] = cls.get("direcao", aposta.get("direcao", "")) or aposta.get("direcao", "")
        aposta["linha"] = cls.get("linha", aposta.get("linha")) if cls.get("linha") is not None else aposta.get("linha")
        aposta["periodo"] = cls.get("periodo", aposta.get("periodo", "jogo inteiro")) or aposta.get("periodo", "jogo inteiro")

        if cls.get("mercado") in ["Total", "Total de Gols", "Pontos"] and cls.get("direcao"):
            aposta["selecao"] = cls.get("direcao")

        if cls.get("mercado") == "Ambas Marcam":
            aposta["btts_resposta"] = cls.get("btts_resposta") or detectar_btts_resposta_aposta(aposta)

        if cls.get("mercado") == "Moneyline":
            selecao_atual = aposta.get("selecao", "")
            selecao_cls = cls.get("selecao", "")
            if selecao_cls and normalizar_nome(selecao_atual) in ["", "resultado final", "resultado", "final"]:
                aposta["selecao"] = selecao_cls

    return aposta


def classificar_aposta(texto_aposta, jogo=""):
    return interpretar_aposta(texto_aposta, jogo)





def metricas():
    recalcular()

    bets_user = bets_do_usuario()
    lucro_total = round(sum(float(b.get("lucro", 0)) for b in bets_user), 2)
    saldo_total_casas = total_saldos_casas()

    banca_atual = round(saldo_total_casas, 2) if saldo_total_casas > 0 else round(float(dados.get("banca_inicial", 0)) + lucro_total, 2)

    greens = len([b for b in bets_user if b.get("estado") == "ganha"])
    reds = len([b for b in bets_user if b.get("estado") == "perdida"])
    pendentes = len([b for b in bets_user if b.get("estado", "") == ""])

    total_apostado_resolvido = sum(
        float(b.get("valor", 0))
        for b in bets_user
        if b.get("estado") in ["ganha", "perdida"]
    )

    roi = round((lucro_total / total_apostado_resolvido) * 100, 2) if total_apostado_resolvido else 0
    taxa = round((greens / (greens + reds)) * 100, 2) if (greens + reds) else 0

    return {
        "banca_atual": banca_atual,
        "lucro_total": lucro_total,
        "roi": roi,
        "taxa": taxa,
        "total": len(bets_user),
        "pendentes": pendentes,
        "greens": greens,
        "reds": reds,
        "saldo_casas_total": saldo_total_casas
    }



def grafico():
    banca = float(dados.get("banca_inicial", 0))
    labels, valores = [], []

    # Se houver saldo por casa, o gráfico usa o saldo atual como referência final,
    # mas mantém evolução por lucro das apostas do usuário.
    for b in bets_do_usuario():
        banca += float(b.get("lucro", 0))
        labels.append(b.get("data", ""))
        valores.append(round(banca, 2))

    if not labels:
        labels = ["Início"]
        valores = [total_saldos_casas() or banca]

    return labels, valores




# ============================================================
# V50 - FIX: parse_data restaurado
# ============================================================

def parse_data(data_str):
    if not data_str:
        return None

    formatos = [
        "%d/%m/%Y %H:%M",
        "%d/%m/%y %H:%M",
        "%d/%m/%Y",
        "%d/%m/%y",
        "%d/%m %H:%M",
        "%d/%m"
    ]

    for fmt in formatos:
        try:
            dt = datetime.strptime(str(data_str).strip(), fmt)
            if "%Y" not in fmt and "%y" not in fmt:
                dt = dt.replace(year=datetime.now().year)
            return dt
        except:
            pass

    return None


def calendario_historico(ano=None, mes=None):
    hoje = datetime.now()
    ano = int(ano or hoje.year)
    mes = int(mes or hoje.month)

    if mes < 1:
        mes = 12
        ano -= 1
    elif mes > 12:
        mes = 1
        ano += 1
    por_dia = {}

    for b in bets_do_usuario():
        dt = parse_data(b.get("data", ""))
        if not dt or dt.year != ano or dt.month != mes:
            continue

        dia = dt.day
        por_dia.setdefault(dia, {"lucro": 0, "apostas": 0})
        por_dia[dia]["lucro"] += float(b.get("lucro", 0))
        por_dia[dia]["apostas"] += 1

    cal = calendar.Calendar(firstweekday=6)
    semanas = []

    for semana in cal.monthdayscalendar(ano, mes):
        linha = []

        for dia in semana:
            if dia == 0:
                linha.append({"dia": "", "lucro": None, "apostas": 0, "classe": "empty"})
            else:
                info = por_dia.get(dia, {"lucro": 0, "apostas": 0})
                lucro = round(info["lucro"], 2)

                if lucro > 0:
                    classe = "day-green"
                elif lucro < 0:
                    classe = "day-red"
                else:
                    classe = "day-neutral"

                linha.append({
                    "dia": dia,
                    "lucro": lucro,
                    "apostas": info["apostas"],
                    "classe": classe
                })

        semanas.append(linha)

    mes_ref = datetime(ano, mes, 1)
    prev_mes = mes - 1
    prev_ano = ano
    next_mes = mes + 1
    next_ano = ano

    if prev_mes < 1:
        prev_mes = 12
        prev_ano -= 1

    if next_mes > 12:
        next_mes = 1
        next_ano += 1

    return {
        "mes_nome": mes_ref.strftime("%B").capitalize(),
        "ano": ano,
        "mes": mes,
        "prev_mes": prev_mes,
        "prev_ano": prev_ano,
        "next_mes": next_mes,
        "next_ano": next_ano,
        "semanas": semanas
    }


def ranking_por_campo(campo):
    ranking = {}

    for b in bets_do_usuario():
        chave = b.get(campo, "").strip() or "Sem informação"
        ranking.setdefault(chave, {"lucro": 0, "apostas": 0})
        ranking[chave]["lucro"] += float(b.get("lucro", 0))
        ranking[chave]["apostas"] += 1

    lista = [
        {"nome": k, "lucro": round(v["lucro"], 2), "apostas": v["apostas"]}
        for k, v in ranking.items()
    ]

    return sorted(lista, key=lambda x: x["lucro"], reverse=True)[:5]


def estatisticas_extras():
    if dados["bets"]:
        ticket_medio = sum(float(b.get("valor", 0)) for b in dados["bets"]) / len(dados["bets"])
    else:
        ticket_medio = 0

    maior_green = max([float(b.get("lucro", 0)) for b in dados["bets"]] or [0])
    maior_red = min([float(b.get("lucro", 0)) for b in dados["bets"]] or [0])

    sequencia = 0
    tipo_seq = ""

    for b in reversed(dados["bets"]):
        if b.get("estado") not in ["ganha", "perdida"]:
            continue

        if not tipo_seq:
            tipo_seq = b.get("estado")
            sequencia = 1
        elif b.get("estado") == tipo_seq:
            sequencia += 1
        else:
            break

    return {
        "ticket_medio": round(ticket_medio, 2),
        "maior_green": round(maior_green, 2),
        "maior_red": round(maior_red, 2),
        "sequencia": sequencia,
        "tipo_seq": tipo_seq,
        "ranking_casas": ranking_por_campo("casa"),
        "ranking_esportes": ranking_por_campo("esporte"),
        "ranking_mercados": ranking_por_campo("mercado")
    }


def preparar_imagem(caminho):
    img = Image.open(caminho)
    largura, altura = img.size
    img = img.resize((largura * 2, altura * 2))
    img = img.convert("L")
    return img


def ler_imagem(caminho):
    img = preparar_imagem(caminho)
    return pytesseract.image_to_string(img, lang="por+eng", config="--psm 6")


def limpar_odd(texto):
    texto = limpar_linha(texto).replace(",", ".")

    matches = re.findall(r"\d+\.\d+", texto)
    odds = []

    for m in matches:
        try:
            v = float(m)
            if 1.01 <= v <= 100:
                odds.append(v)
        except:
            pass

    if odds:
        return odds[-1]

    matches_int = re.findall(r"\d+", texto)
    if matches_int:
        try:
            return float(matches_int[-1])
        except:
            pass

    return 1.0


def limpar_valor(texto):
    texto = str(texto).lower()
    texto = texto.replace("r$", "").replace("rs", "").replace("r5", "").replace("r ", "").replace("$", "")
    texto = remover_emojis(texto).replace(" ", "")
    texto = re.sub(r"[^\d,\.]", "", texto)

    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")

    match = re.search(r"\d+\.\d+", texto)
    if match:
        return float(match.group(0))

    match = re.search(r"\d+", texto)
    if match:
        return float(match.group(0))

    return 0.0



def limpar_lixo_ocr_linha(linha):
    """
    Limpeza leve/agressiva só em lixo comum.
    Não destrói a estrutura antiga das linhas.
    """
    l = limpar_linha(linha)

    lixo_frases = [
        "golden boost",
        "ganhos aumentados",
        "ganho aumentado",
        "limite da aposta",
        "possível retorno",
        "possivel retorno",
        "retorno possível",
        "retorno possivel",
        "criar aposta",
        "cash out",
        "cashout",
        "remover seleção",
        "remover selecao",
        "aposta turbinada",
        "turbinada",
        "casadinha",
        "bilhete",
        "cupom"
    ]

    for termo in lixo_frases:
        l = re.sub(rf"\b{re.escape(termo)}\b", " ", l, flags=re.I)

    # remove valores monetários perdidos
    l = re.sub(r"R\$\s*\d+[,.]?\d*", " ", l, flags=re.I)

    # remove porcentagens/boosts
    l = re.sub(r"\+?\d+[,.]?\d*\s*%", " ", l)

    # remove odds riscadas/soltas no final quando vierem grudadas em lixo
    l = re.sub(r"\b(era|odd|odds)\b\s*\d+[,.]\d+", " ", l, flags=re.I)

    l = re.sub(r"\s+", " ", l).strip()
    return l


def linha_lixo_ocr(linha):
    l = limpar_linha(linha)
    n = normalizar_nome(l)

    if not n:
        return True

    lixo = [
        "golden boost",
        "ganhos aumentados",
        "ganho aumentado",
        "limite da aposta",
        "possivel retorno",
        "possível retorno",
        "criar aposta",
        "cashout",
        "cash out",
        "remover",
        "bilhete",
        "cupom",
        "turbinada",
        "casadinha"
    ]

    if any(x in n for x in lixo):
        return True

    if re.fullmatch(r"\d+", l):
        return True

    # linha só valor monetário
    if re.fullmatch(r"R\$\s*\d+[,.]?\d*", l, flags=re.I):
        return True

    # linha só porcentagem
    if re.fullmatch(r"\+?\d+[,.]?\d*\s*%", l):
        return True

    return False


def montar_linhas_padrao_ocr(texto):
    linhas_originais = [linha.strip() for linha in texto.split("\n") if linha.strip()]
    linhas = []

    for linha in linhas_originais:
        limpa = limpar_lixo_ocr_linha(linha)
        if not limpa:
            continue
        if linha_lixo_ocr(limpa):
            continue
        linhas.append(limpa)

    return linhas


def achar_indice_bloco_padrao(linhas):
    """
    Tenta achar onde começa o bloco padrão:
    casa / jogo / esporte / aposta / odd / ...
    Preferimos a última ocorrência de casa, porque em prints com topo + rodapé
    o bloco de baixo costuma repetir a casa e ser mais limpo.
    """
    idx = None

    casas_norm = [(casa, normalizar_nome(casa)) for casa in CASAS_DISPONIVEIS]

    for i, linha in enumerate(linhas):
        ln = normalizar_nome(linha)
        for casa, casa_norm in casas_norm:
            if casa_norm and ln == casa_norm:
                idx = i
            elif casa_norm and len(casa_norm) >= 4 and re.search(rf"\b{re.escape(casa_norm)}\b", ln):
                idx = i
                idx = i

    return idx if idx is not None else 0



def extrair_valores_de_linha_ocr(linha):
    original = str(linha or "").strip()
    n = normalizar_nome(original)

    if not original:
        return []

    if "limite" in n:
        return []

    lixo = [
        "golden boost", "boost", "ganhos aumentados", "possivel retorno",
        "possível retorno", "retorno", "odd", "odds", "cashout", "cash out",
        "cupom", "bilhete", "criar aposta"
    ]

    if any(x in n for x in lixo):
        return []

    candidatos = []

    # Moeda explícita. Inclui OCR ruim tipo R5, RS, R 65,00.
    moeda_regex = r"(?:R\$|RS\$|R5\$?|R\s*\$?|RS|BRL)\s*([0-9]+(?:[.,][0-9]{1,2})?)"
    for m in re.finditer(moeda_regex, original, flags=re.I):
        candidatos.append(limpar_valor(m.group(0)))

    # Decimal 65,00 / 65.00 sem moeda
    for m in re.finditer(r"\b([0-9]{1,5}[.,][0-9]{2})\b", original):
        val = limpar_valor(m.group(1))
        if val >= 3:
            candidatos.append(val)

    # Linha só inteiro: 65
    if re.fullmatch(r"\d{1,5}", original):
        val = limpar_valor(original)
        if val > 0:
            candidatos.append(val)

    saida = []
    for v in candidatos:
        try:
            v = float(v)
        except:
            continue

        if v <= 0:
            continue

        if v not in saida:
            saida.append(v)

    return saida


def detectar_valor_apostado_bloco(texto, bloco, linhas_originais):
    # 1) linha 8 padrão
    if len(bloco) > 7:
        vals = extrair_valores_de_linha_ocr(bloco[7])
        if vals:
            return vals[-1]

    # 2) linhas próximas, porque OCR pode quebrar/deslocar
    for idx in [8, 6, 9, 5, 10, 7]:
        if len(bloco) > idx:
            vals = extrair_valores_de_linha_ocr(bloco[idx])
            if vals:
                return vals[-1]

    # 3) bloco de baixo pra cima
    for linha in reversed(bloco):
        vals = extrair_valores_de_linha_ocr(linha)
        if vals:
            return vals[-1]

    # 4) OCR inteiro de baixo pra cima
    for linha in reversed(linhas_originais):
        vals = extrair_valores_de_linha_ocr(linha)
        if vals:
            return vals[-1]

    return 0.0


def linha_e_esporte_ocr(linha):
    n = normalizar_nome(linha)
    esportes = [
        "futebol", "basquete", "tenis", "tenis de mesa", "volei",
        "mma", "futebol americano", "esports", "e sports", "golfe"
    ]
    return any(n == normalizar_nome(e) for e in esportes)


def linha_e_odd_ocr(linha):
    l = str(linha).strip().replace(",", ".")

    if re.search(r"r\$", l, flags=re.I):
        return False

    match = re.search(r"\b(\d{1,3}\.\d{2})\b", l)
    if match:
        val = float(match.group(1))
        return 1.01 <= val <= 100

    return False


def linha_e_valor_ocr(linha):
    return bool(re.search(r"R\$\s*\d+[,.]?\d*", str(linha), flags=re.I))


def linha_e_limite_ocr(linha):
    return "limite" in normalizar_nome(linha)


def limpar_jogo_multiplas_ocr(texto_jogo):
    jogo = limpar_linha(texto_jogo)

    # remove lixos ocasionais
    jogo = re.sub(r"\b(futebol|basquete|tenis|tênis|volei|vôlei)\b", " ", jogo, flags=re.I)
    jogo = re.sub(r"\b(limite da aposta|limite|resultado final|ambas marcam|ambas equipes marcam)\b", " ", jogo, flags=re.I)
    jogo = re.sub(r"R\$\s*\d+[,.]?\d*", " ", jogo, flags=re.I)
    jogo = re.sub(r"\s+", " ", jogo).strip(" /-|")

    return jogo


def limpar_aposta_multiplas_ocr(texto_aposta):
    aposta = limpar_linha(texto_aposta)

    # remove valores/lixo sem remover termos de mercado
    aposta = re.sub(r"\b(limite da aposta|limite|golden boost|boost|ganhos aumentados|cupom|bilhete)\b", " ", aposta, flags=re.I)
    aposta = re.sub(r"R\$\s*\d+[,.]?\d*", " ", aposta, flags=re.I)
    aposta = re.sub(r"\+?\d+[,.]?\d*\s*%", " ", aposta)
    aposta = re.sub(r"\s+", " ", aposta).strip(" /-|")

    return aposta


def separar_por_barra_inteligente(texto):
    partes = [limpar_linha(p).strip(" /-|") for p in re.split(r"\s*/\s*", str(texto)) if limpar_linha(p).strip(" /-|")]
    return partes


def normalizar_item_multipla(item):
    item = limpar_linha(item)
    item = re.sub(r"\b(resultado final|result|resultado|mercado final)\b", " ", item, flags=re.I)
    item = re.sub(r"\b(futebol|basquete|tenis|tênis)\b", " ", item, flags=re.I)
    item = re.sub(r"R\$\s*\d+[,.]?\d*", " ", item, flags=re.I)
    item = re.sub(r"\b\d+[,.]\d{2}\b$", " ", item)
    item = re.sub(r"\s+", " ", item).strip(" /-|")
    return item


def extrair_partes_multipla(jogo, aposta):
    jogos = separar_por_barra_inteligente(jogo)
    selecoes = separar_por_barra_inteligente(aposta)

    jogos_limpos = []
    for j in jogos:
        j2 = normalizar_item_multipla(j)
        if j2:
            jogos_limpos.append(j2)

    selecoes_limpas = []
    for s in selecoes:
        s2 = normalizar_item_multipla(s)
        if s2:
            selecoes_limpas.append(s2)

    return {
        "jogos": jogos_limpos,
        "selecoes": selecoes_limpas,
        "qtd_jogos": len(jogos_limpos),
        "qtd_selecoes": len(selecoes_limpas)
    }


def montar_resumo_multipla(partes):
    selecoes = partes.get("selecoes", [])
    jogos = partes.get("jogos", [])

    if selecoes:
        return " / ".join(selecoes[:4]) + (" ..." if len(selecoes) > 4 else "")

    if jogos:
        return " / ".join(jogos[:4]) + (" ..." if len(jogos) > 4 else "")

    return "múltipla"



def classificar_item_multipla(item, jogo=""):
    item_limpo = normalizar_item_multipla(item)
    t = normalizar_nome(item_limpo)

    out = {
        "texto": item_limpo,
        "mercado": "Outro",
        "selecao": "",
        "direcao": "",
        "linha": None
    }

    if not item_limpo:
        return out


    # Jogador chutes/chutes a gol
    if texto_tem(t, [
        "tem 1 ou mais chutes", "tem um ou mais chutes", "1 ou mais chutes",
        "um ou mais chutes", "chutes gol", "chute gol", "chutes a gol",
        "chute a gol", "chutes no gol", "chute no gol",
        "shots on target", "shot on target"
    ]):
        out["mercado"] = "Jogador Chutes no Gol" if ("gol" in t or "target" in t) else "Jogador Chutes"
        out["direcao"] = "over"
        out["selecao"] = limpar_nome_jogador(item_limpo)
        out["linha"] = extrair_linha(item_limpo) or 0.5
        return out

    # Frase de múltipla de vencedores
    if "vencerem seus jogos" in t or "vencem seus jogos" in t or "vencerem os seus jogos" in t or "vencem os seus jogos" in t:
        out["mercado"] = "Múltipla - Moneyline"
        out["selecao"] = re.sub(r"\b(vencerem seus jogos|vencem seus jogos|vencerem os seus jogos|vencem os seus jogos)\b", "", item_limpo, flags=re.I).strip()
        return out

    # Dupla chance natural: "Time ou empate"
    casa, fora = extrair_times_jogo(jogo)

    if " ou empate" in t or "empate ou " in t or "chance dupla" in t or "dupla chance" in t:
        out["mercado"] = "Dupla Chance"

        if casa and normalizar_nome(casa) in t and "empate" in t:
            out["selecao"] = "1X"
        elif fora and normalizar_nome(fora) in t and "empate" in t:
            out["selecao"] = "X2"
        else:
            dc = detectar_dupla_chance_selecao(item_limpo)
            out["selecao"] = dc or ""

        return out

    # Over/Under / Total
    direcao = detectar_direcao(item_limpo)
    linha = extrair_linha(item_limpo)

    if direcao:
        if texto_tem(t, ["escanteio", "escanteios", "corner", "corners", "cantos"]):
            out["mercado"] = "Escanteios"
        elif texto_tem(t, ["chutes a gol", "chutes no gol", "shots on target"]):
            out["mercado"] = "Chutes no Gol"
        elif texto_tem(t, ["chutes", "shots"]):
            out["mercado"] = "Chutes"
        else:
            out["mercado"] = "Total"

        out["direcao"] = direcao
        out["selecao"] = direcao
        out["linha"] = linha
        return out

    # BTTS
    if eh_texto_btts(item_limpo):
        out["mercado"] = "Ambas Marcam"
        out["selecao"] = detectar_btts_resposta(item_limpo) or "sim"
        return out

    # Moneyline natural
    if texto_tem(t, ["vence", "vencem", "resultado final", "moneyline", "para vencer"]):
        out["mercado"] = "Moneyline"
        out["selecao"] = extrair_selecao(item_limpo, jogo)
        return out

    return out


def classificar_itens_multipla(jogo, tipo_aposta):
    partes = extrair_partes_multipla(jogo, tipo_aposta)

    itens = []

    # Usa seleções se existirem; senão usa jogos.
    base = partes.get("selecoes") or partes.get("jogos") or []

    for item in base:
        c = classificar_item_multipla(item, jogo)
        if c.get("texto"):
            itens.append(c)

    mercados = [i["mercado"] for i in itens if i["mercado"] != "Outro"]

    if not itens:
        tipo = "Múltipla"
    elif len(set(mercados)) == 1 and mercados:
        tipo = f"Múltipla - {mercados[0]}"
    elif mercados:
        tipo = "Múltipla - Combinada"
    else:
        tipo = "Múltipla"

    return tipo, partes, itens


def montar_resumo_itens_multipla(itens, partes):
    if itens:
        textos = []
        for i in itens:
            if i.get("mercado") == "Dupla Chance" and i.get("selecao"):
                textos.append(f"{i.get('texto')} ({i.get('selecao')})")
            elif i.get("direcao") and i.get("linha") is not None:
                textos.append(f"{i.get('direcao')} {i.get('linha')}")
            else:
                textos.append(i.get("texto", ""))

        textos = [t for t in textos if t]
        return " / ".join(textos[:4]) + (" ..." if len(textos) > 4 else "")

    return montar_resumo_multipla(partes)


def detectar_tipo_multipla(jogo, aposta):
    partes = extrair_partes_multipla(jogo, aposta)

    if partes["qtd_jogos"] > 1 or partes["qtd_selecoes"] > 1:
        return True, partes

    return False, partes


def classificar_aposta_multiplas_ou_simples(jogo, tipo_aposta):
    eh_multipla, partes = detectar_tipo_multipla(jogo, tipo_aposta)

    t_aposta = normalizar_nome(tipo_aposta)
    if texto_tem(t_aposta, ["vencerem seus jogos", "vencem seus jogos", "vencerem os seus jogos", "vencem os seus jogos"]):
        eh_multipla = True
        if not partes.get("selecoes"):
            partes["selecoes"] = [tipo_aposta]
            partes["qtd_selecoes"] = 1

    if eh_multipla:
        mercado_base, partes, itens = classificar_itens_multipla(jogo, tipo_aposta)

        # usa a classificação geral só como fallback para direção/linha quando for múltipla homogênea
        cls = classificar_aposta(f"{jogo} {tipo_aposta}", jogo)

        cls["mercado"] = mercado_base
        cls["itens_multipla"] = partes
        cls["itens_multipla_detalhados"] = itens

        # Em múltipla combinada, seleção precisa ser resumo curto, não texto bruto inteiro.
        cls["selecao"] = montar_resumo_itens_multipla(itens, partes)

        # Se tiver só um tipo over/under, pode manter direção/linha; se for combinada, deixa sem linha geral.
        mercados = [i.get("mercado") for i in itens if i.get("mercado") != "Outro"]
        direcoes = [i.get("direcao") for i in itens if i.get("direcao")]
        linhas = [i.get("linha") for i in itens if i.get("linha") is not None]

        if mercado_base == "Múltipla - Combinada":
            cls["direcao"] = ""
            cls["linha"] = None
        elif len(set(direcoes)) == 1 and direcoes:
            cls["direcao"] = direcoes[0]
            cls["linha"] = linhas[0] if linhas else None

        return cls

    return classificar_aposta(tipo_aposta, jogo)


def extrair_linhas_padrao_multibloco(texto):
    linhas_originais = [linha.strip() for linha in texto.split("\n") if linha.strip()]

    linhas = []
    for linha in linhas_originais:
        limpa = limpar_lixo_ocr_linha(linha) if "limpar_lixo_ocr_linha" in globals() else limpar_linha(linha)
        if not limpa:
            continue
        if "linha_lixo_ocr" in globals() and linha_lixo_ocr(limpa):
            continue
        linhas.append(limpa)

    if not linhas:
        raise ValueError("OCR sem linhas úteis")

    idx = achar_indice_bloco_padrao(linhas) if "achar_indice_bloco_padrao" in globals() else 0
    bloco = linhas[idx:]

    casa = limpar_casa(bloco[0]) if len(bloco) > 0 else ""

    idx_esporte = None
    for i in range(1, len(bloco)):
        if linha_e_esporte_ocr(bloco[i]):
            idx_esporte = i
            break

    if idx_esporte is None:
        jogo = limpar_jogo_multiplas_ocr(bloco[1]) if len(bloco) > 1 else ""
        esporte = limpar_linha(bloco[2]) if len(bloco) > 2 else "Futebol"
        idx_aposta_ini = 3
    else:
        jogo = limpar_jogo_multiplas_ocr(" / ".join(bloco[1:idx_esporte]))
        esporte = limpar_linha(bloco[idx_esporte])
        idx_aposta_ini = idx_esporte + 1

    idx_odd = None
    for i in range(idx_aposta_ini, len(bloco)):
        if linha_e_odd_ocr(bloco[i]):
            idx_odd = i
            break

    if idx_odd is None:
        tipo_aposta = limpar_aposta_multiplas_ocr(bloco[idx_aposta_ini]) if len(bloco) > idx_aposta_ini else ""
        odd = 1.0
    else:
        tipo_aposta = limpar_aposta_multiplas_ocr(" / ".join(bloco[idx_aposta_ini:idx_odd]))
        odd = limpar_odd(bloco[idx_odd])

    jogo = re.sub(r"\s*/\s*/+\s*", " / ", jogo).strip(" /-|")
    tipo_aposta = re.sub(r"\s*/\s*/+\s*", " / ", tipo_aposta).strip(" /-|")

    valor = detectar_valor_apostado_bloco(texto, bloco, linhas_originais)

    classificacao = classificar_aposta_multiplas_ou_simples(jogo, tipo_aposta)

    if classificacao.get("mercado") == "Ambas Marcam":
        resposta = classificacao.get("btts_resposta") or detectar_btts_resposta(tipo_aposta) or "sim"
        classificacao["selecao"] = resposta
        classificacao["btts_resposta"] = resposta
        classificacao["linha"] = None

    if classificacao.get("direcao") in ["over", "under"]:
        classificacao["selecao"] = classificacao["direcao"]

    aposta_final = f"{jogo} - {tipo_aposta}" if jogo and tipo_aposta else (tipo_aposta or jogo or "Erro OCR - revise manualmente")
    texto_interpretado = f"{jogo} {tipo_aposta}".strip()

    return {
        "casa": casa,
        "esporte": esporte,
        "jogo": jogo,
        "aposta": aposta_final,
        "odd": odd,
        "valor": valor,
        "mercado": classificacao["mercado"],
        "direcao": classificacao.get("direcao", ""),
        "linha": classificacao.get("linha", None),
        "periodo": classificacao.get("periodo", "jogo inteiro"),
        "selecao": classificacao.get("selecao", ""),
        "btts_resposta": classificacao.get("btts_resposta", ""),
        "texto_bruto": texto,
        "texto_interpretado": texto_interpretado,
        "itens_multipla": classificacao.get("itens_multipla", {}),
        "itens_multipla_detalhados": classificacao.get("itens_multipla_detalhados", [])
    }



# =========================
# OCR SaaS SEM IA - PARSER ROBUSTO V19
# =========================

def limpar_valor_ocr_robusto(linha):
    original = str(linha or "").strip()
    n = normalizar_nome(original)

    if not original:
        return 0.0

    if "limite" in n:
        return 0.0

    if any(x in n for x in [
        "possivel retorno", "possível retorno", "retorno",
        "odd", "odds", "golden boost", "boost", "ganhos aumentados",
        "cupom", "bilhete", "cashout", "cash out"
    ]):
        return 0.0

    m = re.search(r"(?:R\$|RS\$|R5\$?|R\s*\$?|RS|BRL)\s*([0-9]+(?:[.,][0-9]{1,2})?)", original, flags=re.I)
    if m:
        return limpar_valor(m.group(0))

    m = re.search(r"\b([0-9]{1,5}[.,][0-9]{2})\b", original)
    if m:
        val = limpar_valor(m.group(1))
        if val >= 3:
            return val

    if re.fullmatch(r"\d{1,5}", original):
        return limpar_valor(original)

    return 0.0


def detectar_valor_apostado_ocr_v19(texto, bloco, linhas_originais):
    if len(bloco) > 7:
        val = limpar_valor_ocr_robusto(bloco[7])
        if val:
            return val

    for idx in [8, 6, 9, 5, 10, 7, 11]:
        if len(bloco) > idx:
            val = limpar_valor_ocr_robusto(bloco[idx])
            if val:
                return val

    for linha in reversed(bloco):
        val = limpar_valor_ocr_robusto(linha)
        if val:
            return val

    for linha in reversed(linhas_originais):
        val = limpar_valor_ocr_robusto(linha)
        if val:
            return val

    return 0.0


def linha_e_esporte_ocr_v19(linha):
    n = normalizar_nome(linha)
    mapa = {
        "futebol": "Futebol",
        "soccer": "Futebol",
        "basquete": "Basquete",
        "basketball": "Basquete",
        "tenis": "Tênis",
        "tennis": "Tênis",
        "tenis de mesa": "Tênis de Mesa",
        "table tennis": "Tênis de Mesa",
        "volei": "Vôlei",
        "volleyball": "Vôlei",
        "mma": "MMA",
        "ufc": "MMA",
        "futebol americano": "Futebol Americano",
        "esports": "eSports",
        "e sports": "eSports"
    }

    for termo, esporte in mapa.items():
        if n == termo or termo in n:
            return esporte

    return ""


def linha_parece_odd_ocr_v19(linha):
    l = str(linha).strip().replace(",", ".")

    if re.search(r"r\$", l, flags=re.I):
        return False

    match = re.search(r"\b(\d{1,3}\.\d{2})\b", l)
    if match:
        val = float(match.group(1))
        return 1.01 <= val <= 100

    return False


def linha_parece_lixo_ocr_v19(linha):
    l = str(linha or "").strip()
    n = normalizar_nome(l)

    if not l:
        return True

    lixo = [
        "golden boost", "boost", "ganhos aumentados", "ganho aumentado",
        "limite da aposta", "possivel retorno", "possível retorno",
        "retorno possivel", "retorno possível", "criar aposta",
        "remover selecao", "remover seleção", "bilhete", "cupom",
        "cashout", "cash out", "turbinada", "casadinha", "stake"
    ]

    if any(x in n for x in lixo):
        return True

    if re.fullmatch(r"\d{1,3}", l):
        return True

    if re.fullmatch(r"\+?\d+[.,]?\d*\s*%", l):
        return True

    return False


def limpar_linha_ocr_v19(linha):
    l = limpar_linha(linha)

    for termo in [
        "golden boost", "boost", "ganhos aumentados", "ganho aumentado",
        "limite da aposta", "possivel retorno", "possível retorno",
        "criar aposta", "remover seleção", "remover selecao",
        "bilhete", "cupom"
    ]:
        l = re.sub(rf"\b{re.escape(termo)}\b", " ", l, flags=re.I)

    l = re.sub(r"R\$\s*\d+[,.]?\d*", " ", l, flags=re.I)
    l = re.sub(r"\+?\d+[,.]?\d*\s*%", " ", l)
    l = re.sub(r"\s+", " ", l).strip(" /-|")
    return l


def montar_linhas_ocr_v19(texto):
    linhas_originais = [l.strip() for l in texto.split("\n") if l.strip()]
    linhas = []

    for linha in linhas_originais:
        limpa = limpar_linha_ocr_v19(linha)
        if not limpa:
            continue

        if linha_parece_lixo_ocr_v19(limpa):
            continue

        linhas.append(limpa)

    return linhas_originais, linhas


def achar_inicio_bloco_v19(linhas):
    idx = None

    for i, linha in enumerate(linhas):
        ln = normalizar_nome(linha)

        for casa in CASAS_DISPONIVEIS:
            cn = normalizar_nome(casa)
            if cn and ln == cn:
                idx = i
            elif cn and len(cn) >= 4 and re.search(rf"\b{re.escape(cn)}\b", ln):
                idx = i
                idx = i

    return idx if idx is not None else 0


def limpar_item_multipla_v19(item):
    item = limpar_linha(item)
    item = re.sub(r"\b(resultado final|resultado|mercado final|futebol|basquete|tenis|tênis)\b", " ", item, flags=re.I)
    item = re.sub(r"R\$\s*\d+[,.]?\d*", " ", item, flags=re.I)
    item = re.sub(r"\b\d+[,.]\d{2}\b$", " ", item)
    item = re.sub(r"\s+", " ", item).strip(" /-|")
    return item


def dividir_itens_v19(texto):
    return [limpar_item_multipla_v19(p) for p in re.split(r"\s*/\s*", str(texto)) if limpar_item_multipla_v19(p)]


def extrair_partes_multipla(jogo, aposta):
    jogos = dividir_itens_v19(jogo)
    selecoes = dividir_itens_v19(aposta)

    return {
        "jogos": jogos,
        "selecoes": selecoes,
        "qtd_jogos": len(jogos),
        "qtd_selecoes": len(selecoes)
    }


def detectar_tipo_multipla(jogo, aposta):
    partes = extrair_partes_multipla(jogo, aposta)
    return (partes["qtd_jogos"] > 1 or partes["qtd_selecoes"] > 1), partes


def classificar_item_multipla_v19(item, jogo=""):
    item = limpar_item_multipla_v19(item)
    t = normalizar_nome(item)

    out = {
        "texto": item,
        "mercado": "Outro",
        "selecao": "",
        "direcao": "",
        "linha": None
    }

    if not item:
        return out


    # Jogador chutes/chutes a gol
    if texto_tem(t, [
        "tem 1 ou mais chutes", "tem um ou mais chutes", "1 ou mais chutes",
        "um ou mais chutes", "chutes gol", "chute gol", "chutes a gol",
        "chute a gol", "chutes no gol", "chute no gol",
        "shots on target", "shot on target"
    ]):
        out["mercado"] = "Jogador Chutes no Gol" if ("gol" in t or "target" in t) else "Jogador Chutes"
        out["direcao"] = "over"
        out["selecao"] = limpar_nome_jogador(item)
        out["linha"] = extrair_linha(item) or 0.5
        return out

    # Frase de múltipla de vencedores
    if "vencerem seus jogos" in t or "vencem seus jogos" in t or "vencerem os seus jogos" in t or "vencem os seus jogos" in t:
        out["mercado"] = "Múltipla - Moneyline"
        out["selecao"] = re.sub(r"\b(vencerem seus jogos|vencem seus jogos|vencerem os seus jogos|vencem os seus jogos)\b", "", item, flags=re.I).strip()
        return out

    casa, fora = extrair_times_jogo(jogo)

    if " ou empate" in t or "empate ou " in t or "dupla chance" in t or "chance dupla" in t:
        out["mercado"] = "Dupla Chance"

        if casa and normalizar_nome(casa) in t:
            out["selecao"] = "1X"
        elif fora and normalizar_nome(fora) in t:
            out["selecao"] = "X2"
        else:
            out["selecao"] = detectar_dupla_chance_selecao(item) or ""

        return out

    direcao = detectar_direcao(item)
    linha = extrair_linha(item)

    if direcao:
        if texto_tem(t, ["escanteio", "escanteios", "corner", "corners", "cantos"]):
            out["mercado"] = "Escanteios"
        elif texto_tem(t, ["chutes a gol", "chutes no gol", "shots on target"]):
            out["mercado"] = "Chutes no Gol"
        elif texto_tem(t, ["chutes", "shots"]):
            out["mercado"] = "Chutes"
        else:
            out["mercado"] = "Total"

        out["direcao"] = direcao
        out["selecao"] = direcao
        out["linha"] = linha
        return out

    if eh_texto_btts(item):
        out["mercado"] = "Ambas Marcam"
        out["selecao"] = detectar_btts_resposta(item) or "sim"
        return out

    if texto_tem(t, ["vence", "vencem", "resultado final", "moneyline", "para vencer"]):
        out["mercado"] = "Moneyline"
        out["selecao"] = extrair_selecao(item, jogo)
        return out

    mercado_jogador = detectar_jogador_mercado(item) if "detectar_jogador_mercado" in globals() else ""
    if mercado_jogador:
        out["mercado"] = mercado_jogador
        out["selecao"] = limpar_nome_jogador(item)
        return out

    return out


def montar_resumo_multipla_v19(itens, partes):
    if itens:
        textos = []

        for i in itens:
            if i.get("mercado") == "Dupla Chance" and i.get("selecao"):
                textos.append(f"{i.get('texto')} ({i.get('selecao')})")
            elif i.get("direcao") and i.get("linha") is not None:
                textos.append(f"{i.get('direcao')} {i.get('linha')}")
            else:
                textos.append(i.get("texto", ""))

        textos = [t for t in textos if t]
        return " / ".join(textos[:5]) + (" ..." if len(textos) > 5 else "")

    selecoes = partes.get("selecoes", [])
    jogos = partes.get("jogos", [])

    if selecoes:
        return " / ".join(selecoes[:5]) + (" ..." if len(selecoes) > 5 else "")

    if jogos:
        return " / ".join(jogos[:5]) + (" ..." if len(jogos) > 5 else "")

    return "múltipla"


def classificar_aposta_multiplas_ou_simples(jogo, tipo_aposta):
    eh_multipla, partes = detectar_tipo_multipla(jogo, tipo_aposta)

    t_aposta = normalizar_nome(tipo_aposta)
    if texto_tem(t_aposta, ["vencerem seus jogos", "vencem seus jogos", "vencerem os seus jogos", "vencem os seus jogos"]):
        eh_multipla = True
        if not partes.get("selecoes"):
            partes["selecoes"] = [tipo_aposta]
            partes["qtd_selecoes"] = 1

    if eh_multipla:
        base = partes.get("selecoes") or partes.get("jogos") or []
        itens = [classificar_item_multipla_v19(i, jogo) for i in base if i]

        mercados = [i["mercado"] for i in itens if i["mercado"] != "Outro"]

        if not mercados:
            mercado_base = "Múltipla"
        elif len(set(mercados)) == 1:
            mercado_base = f"Múltipla - {mercados[0]}"
        else:
            mercado_base = "Múltipla - Combinada"

        cls = classificar_aposta(f"{jogo} {tipo_aposta}", jogo)
        cls["mercado"] = mercado_base
        cls["itens_multipla"] = partes
        cls["itens_multipla_detalhados"] = itens
        cls["selecao"] = montar_resumo_multipla_v19(itens, partes)

        if mercado_base == "Múltipla - Combinada":
            cls["direcao"] = ""
            cls["linha"] = None

        return cls

    return classificar_aposta(tipo_aposta, jogo)


def extrair_linhas_padrao_saas_v19(texto):
    linhas_originais, linhas = montar_linhas_ocr_v19(texto)

    if not linhas:
        raise ValueError("OCR sem linhas úteis")

    idx = achar_inicio_bloco_v19(linhas)
    bloco = linhas[idx:]

    casa = limpar_casa(bloco[0]) if len(bloco) > 0 else ""

    idx_esporte = None
    esporte = "Futebol"

    for i in range(1, len(bloco)):
        e = linha_e_esporte_ocr_v19(bloco[i])
        if e:
            idx_esporte = i
            esporte = e
            break

    if idx_esporte is None:
        jogo = limpar_linha(bloco[1]) if len(bloco) > 1 else ""
        idx_aposta_ini = 3
        if len(bloco) > 2:
            esporte_detectado = linha_e_esporte_ocr_v19(bloco[2])
            if esporte_detectado:
                esporte = esporte_detectado
    else:
        jogo = " / ".join([limpar_item_multipla_v19(x) for x in bloco[1:idx_esporte] if limpar_item_multipla_v19(x)])
        idx_aposta_ini = idx_esporte + 1

    idx_odd = None

    for i in range(idx_aposta_ini, len(bloco)):
        if linha_parece_odd_ocr_v19(bloco[i]):
            idx_odd = i
            break

    if idx_odd is None:
        tipo_aposta = limpar_item_multipla_v19(bloco[idx_aposta_ini]) if len(bloco) > idx_aposta_ini else ""
        odd = 1.0
    else:
        tipo_aposta = " / ".join([limpar_item_multipla_v19(x) for x in bloco[idx_aposta_ini:idx_odd] if limpar_item_multipla_v19(x)])
        odd = limpar_odd(bloco[idx_odd])

    valor = detectar_valor_apostado_ocr_v19(texto, bloco, linhas_originais)

    classificacao = classificar_aposta_multiplas_ou_simples(jogo, tipo_aposta)

    if classificacao.get("mercado") == "Ambas Marcam":
        resposta = classificacao.get("btts_resposta") or detectar_btts_resposta(tipo_aposta) or "sim"
        classificacao["selecao"] = resposta
        classificacao["btts_resposta"] = resposta
        classificacao["linha"] = None

    if classificacao.get("direcao") in ["over", "under"]:
        classificacao["selecao"] = classificacao["direcao"]

    aposta_final = f"{jogo} - {tipo_aposta}" if jogo and tipo_aposta else (tipo_aposta or jogo or "Erro OCR - revise manualmente")
    texto_interpretado = f"{jogo} {tipo_aposta}".strip()

    return {
        "casa": casa,
        "esporte": esporte,
        "jogo": jogo,
        "aposta": aposta_final,
        "odd": odd,
        "valor": valor,
        "mercado": classificacao.get("mercado", "Outro"),
        "direcao": classificacao.get("direcao", ""),
        "linha": classificacao.get("linha", None),
        "periodo": classificacao.get("periodo", "jogo inteiro"),
        "selecao": classificacao.get("selecao", ""),
        "btts_resposta": classificacao.get("btts_resposta", ""),
        "texto_bruto": texto,
        "texto_interpretado": texto_interpretado,
        "itens_multipla": classificacao.get("itens_multipla", {}),
        "itens_multipla_detalhados": classificacao.get("itens_multipla_detalhados", [])
    }



def extrair(texto):
    try:
        if "extrair_v20" in globals():
            resultado = extrair_v20(texto)
        elif "extrair_linhas_padrao_saas_v19" in globals():
            resultado = extrair_linhas_padrao_saas_v19(texto)
        elif "extrair_linhas_padrao_multibloco" in globals():
            resultado = extrair_linhas_padrao_multibloco(texto)
        else:
            raise Exception("Nenhum extrator base encontrado")

        return aplicar_formatacao_multiplas_combinadas(resultado)

    except Exception as e:
        print("ERRO OCR/extrair V25:", e)
        texto_completo_limpo = limpar_linha(texto)
        classificacao = classificar_aposta(texto_completo_limpo, "")
        resultado = {
            "casa": "",
            "esporte": "Futebol",
            "jogo": "",
            "aposta": texto_completo_limpo[:180] if texto_completo_limpo else "Erro OCR - revise manualmente",
            "odd": 1.0,
            "valor": 0.0,
            "mercado": classificacao["mercado"],
            "direcao": classificacao["direcao"],
            "linha": classificacao["linha"],
            "periodo": classificacao["periodo"],
            "selecao": classificacao["selecao"],
            "btts_resposta": classificacao["btts_resposta"],
            "texto_bruto": texto,
            "texto_interpretado": texto_completo_limpo,
            "itens_multipla": {},
            "itens_multipla_detalhados": []
        }
        return aplicar_formatacao_multiplas_combinadas(resultado)



# ============================================================
# V23 - VALIDAÇÃO DE MÚLTIPLAS SIMPLES PELA API
# Ex: "Flamengo e Palmeiras vencem" -> só ganha se Flamengo E Palmeiras ganharem.
# ============================================================

def separar_times_vencedores_texto(texto):
    bruto = limpar_linha(texto)

    bruto = re.sub(r"\b(vencerem seus jogos|vencem seus jogos|vencerem os seus jogos|vencem os seus jogos)\b", "", bruto, flags=re.I)
    bruto = re.sub(r"\b(vence|vencem|vencer|vencerem|para vencer|ganha|ganham|resultado final|moneyline)\b", "", bruto, flags=re.I)
    bruto = re.sub(r"\b(futebol|basquete|tenis|tênis|volei|vôlei)\b", "", bruto, flags=re.I)
    bruto = re.sub(r"\s+", " ", bruto).strip(" /-|")

    partes = re.split(r"\s*(?:/|,|\+|\be\b|\band\b)\s*", bruto, flags=re.I)

    times = []
    vistos = set()

    for p in partes:
        p = limpar_linha(p)
        p = re.sub(r"\b(de|do|da|dos|das)\s+jogos?\b", "", p, flags=re.I)
        p = re.sub(r"\s+", " ", p).strip(" /-|")

        if len(p) < 3:
            continue

        n = normalizar_nome(p)

        if n in ["resultado", "final", "vencedor", "vencedores", "time", "times"]:
            continue

        if n and n not in vistos:
            vistos.add(n)
            times.append(p)

    return times


def detectar_multipla_moneyline_times(aposta):
    mercado = str(aposta.get("mercado", ""))
    texto_total = " ".join([
        str(aposta.get("aposta", "")),
        str(aposta.get("selecao", "")),
        str(aposta.get("texto_interpretado", ""))
    ])

    t = normalizar_nome(texto_total)

    if mercado.startswith("Múltipla") and texto_tem(t, [
        "vencem", "vencerem", "vence", "para vencer", "moneyline", "resultado final"
    ]):
        times = separar_times_vencedores_texto(texto_total)

        if len(times) < 2:
            times = separar_times_vencedores_texto(aposta.get("selecao", ""))

        if len(times) < 2:
            times = separar_times_vencedores_texto(aposta.get("aposta", ""))

        return times if len(times) >= 2 else []

    if texto_tem(t, ["vencem", "vencerem", "vencerem seus jogos", "vencem seus jogos"]):
        times = separar_times_vencedores_texto(texto_total)
        return times if len(times) >= 2 else []

    return []


def buscar_resultado_time_simples(nome_time, aposta_base):
    temp = dict(aposta_base)
    temp["jogo"] = nome_time
    temp["selecao"] = nome_time
    temp["mercado"] = "Moneyline"
    temp["esporte"] = aposta_base.get("esporte", "Futebol") or "Futebol"

    return buscar_resultado_futebol(temp)


def validar_time_venceu_no_resultado(nome_time, resultado):
    home = resultado.get("home_team", "")
    away = resultado.get("away_team", "")
    hs = resultado.get("home_score")
    aw = resultado.get("away_score")

    if hs is None or aw is None:
        return None

    if nome_bate(nome_time, home):
        return hs > aw

    if nome_bate(nome_time, away):
        return aw > hs

    return None


def validar_multipla_moneyline_api(aposta):
    times = detectar_multipla_moneyline_times(aposta)

    if len(times) < 2:
        return None, "múltipla sem times suficientes"

    detalhes = []

    for time_nome in times:
        resultado = buscar_resultado_time_simples(time_nome, aposta)

        if not resultado:
            return None, f"resultado não encontrado para {time_nome}"

        if resultado.get("status") not in ["FT", "AET", "PEN"]:
            return None, f"jogo ainda não finalizado para {time_nome}"

        venceu = validar_time_venceu_no_resultado(time_nome, resultado)

        if venceu is None:
            return None, f"não consegui confirmar o time {time_nome} no jogo encontrado"

        detalhes.append(f"{time_nome}: {'ganhou' if venceu else 'não ganhou'}")

        if not venceu:
            return "perdida", " | ".join(detalhes)

    return "ganha", " | ".join(detalhes)




# ============================================================
# V24 - MOTOR UNIVERSAL DE MÚLTIPLAS
# ============================================================

def dividir_itens_multipla_universal(texto):
    bruto = limpar_linha(texto)
    bruto = re.sub(r"\b(resultado final|moneyline)\s*[:\-]?", " ", bruto, flags=re.I)
    bruto = re.sub(r"\b(futebol|basquete|tenis|tênis|volei|vôlei)\b", " ", bruto, flags=re.I)
    bruto = re.sub(r"R\$\s*\d+[,.]?\d*", " ", bruto, flags=re.I)
    bruto = re.sub(r"\s+", " ", bruto).strip(" /-|")

    partes = re.split(r"\s*(?:/|\+|;|\n)\s*", bruto)
    itens = []

    for parte in partes:
        parte = limpar_linha(parte).strip(" /-|")
        if not parte:
            continue
        n = normalizar_nome(parte)

        if re.search(r"\b(e|and)\b", n) and texto_tem(n, ["vencem", "vencerem", "vence", "para vencer"]):
            frase = parte
            frase = re.sub(r"\b(vencerem seus jogos|vencem seus jogos|vencerem os seus jogos|vencem os seus jogos)\b", "", frase, flags=re.I)
            frase = re.sub(r"\b(vence|vencem|vencer|vencerem|para vencer|ganha|ganham)\b", "", frase, flags=re.I)
            subs = re.split(r"\s+\b(?:e|and)\b\s+", frase, flags=re.I)
            for sp in subs:
                sp = limpar_linha(sp).strip(" /-|")
                if len(sp) >= 3:
                    itens.append(sp + " vence")
            continue

        itens.append(parte)

    saida = []
    vistos = set()
    for item in itens:
        item = re.sub(r"\s+", " ", item).strip(" /-|")
        n = normalizar_nome(item)
        if n and n not in vistos:
            vistos.add(n)
            saida.append(item)
    return saida


def extrair_itens_multipla_universal(aposta):
    candidatos = []

    det = aposta.get("itens_multipla_detalhados", [])
    if isinstance(det, list):
        for it in det:
            if isinstance(it, dict) and it.get("texto"):
                candidatos.append(str(it.get("texto")))

    im = aposta.get("itens_multipla", {})
    if isinstance(im, dict):
        for campo in ["selecoes", "jogos"]:
            val = im.get(campo, [])
            if isinstance(val, list):
                candidatos.extend([str(x) for x in val if str(x).strip()])

    for campo in ["selecao", "aposta", "texto_interpretado"]:
        val = str(aposta.get(campo, "") or "")
        if val:
            candidatos.extend(dividir_itens_multipla_universal(val))

    texto_total = " ".join([str(aposta.get("aposta", "")), str(aposta.get("selecao", "")), str(aposta.get("texto_interpretado", ""))])
    candidatos.extend(dividir_itens_multipla_universal(texto_total))

    saida = []
    vistos = set()
    for c in candidatos:
        c = limpar_linha(c)
        c = re.sub(r"\b(multipla|múltipla|dupla|tripla)\b", " ", c, flags=re.I)
        c = re.sub(r"\s+", " ", c).strip(" /-|")
        if len(c) < 3:
            continue
        n = normalizar_nome(c)
        if n in vistos:
            continue
        if len(c.split()) > 14 and len(saida) >= 2:
            continue
        vistos.add(n)
        saida.append(c)

    if len(saida) == 1:
        div = dividir_itens_multipla_universal(saida[0])
        if len(div) > 1:
            saida = div
    return saida


def montar_item_aposta_para_validar(item_texto, aposta_base):
    jogo_base = aposta_base.get("jogo", "")
    item_limpo = limpar_linha(item_texto)
    n = normalizar_nome(item_limpo)

    if (not texto_tem(n, ["vence", "vencem", "vencer", "empate", "over", "under", "mais de", "menos de", "ambas", "btts", "escanteio", "corner", "chute", "marcador", "assistencia", "assistência", "dupla chance", "chance dupla"]) and len(item_limpo.split()) <= 4):
        item_limpo = item_limpo + " vence"

    cls = classificar_item_combinada_visual_v28(item_limpo, jogo_base) if "classificar_item_combinada_visual_v28" in globals() else classificar_aposta(item_limpo, jogo_base)
    item = dict(aposta_base)
    item["aposta"] = item_limpo
    item["texto_interpretado"] = item_limpo
    item["mercado"] = cls.get("mercado", "Outro")
    item["direcao"] = cls.get("direcao", "")
    item["linha"] = cls.get("linha", None)
    item["periodo"] = cls.get("periodo", "jogo inteiro")
    item["selecao"] = cls.get("selecao", "")
    item["btts_resposta"] = cls.get("btts_resposta", "")

    if item["mercado"] == "Moneyline":
        sel = cls.get("selecao", "")
        if not sel or normalizar_nome(sel) in ["resultado final", "resultado", "final"]:
            sel = re.sub(r"\b(vence|vencem|vencer|vencerem|para vencer|ganha|ganham)\b", "", item_limpo, flags=re.I)
            sel = re.sub(r"\s+", " ", sel).strip()
        item["selecao"] = sel
        if not jogo_base or " x " not in normalizar_nome(jogo_base):
            item["jogo"] = sel
    item = corrigir_item_quantitativo_v27(item)

    return item



def corrigir_item_quantitativo_v27(item):
    mercado = str(item.get("mercado", ""))
    texto = " ".join([
        str(item.get("aposta", "")),
        str(item.get("selecao", "")),
        str(item.get("texto_interpretado", ""))
    ])

    if mercado in ["Escanteios", "Chutes", "Chutes no Gol", "Total", "Total de Gols", "Cartões"]:
        direcao, linha = normalizar_direcao_linha_v27(texto)

        if direcao:
            item["direcao"] = direcao
            item["selecao"] = direcao

        if linha is not None:
            item["linha"] = linha

    return item


def validar_item_multipla_universal(item_aposta):
    if normalizar_nome(item_aposta.get("esporte", "Futebol")) != "futebol":
        return None, "ignorado: não é futebol"

    resultado = buscar_resultado_futebol(item_aposta)
    if not resultado:
        return None, "resultado não encontrado"
    if resultado.get("status") not in ["FT", "AET", "PEN"]:
        return None, "jogo ainda não finalizado"

    if item_aposta.get("mercado") == "HT Vence sem sofrer":
        status = validar_ht_vence_sem_sofrer_v28(item_aposta, resultado)
    else:
        status = validar_aposta_com_resultado(item_aposta, resultado)

    if status:
        return status, "validado"
    return None, "mercado não validado"


def validar_multipla_universal_api(aposta):
    itens = extrair_itens_multipla_universal(aposta)
    if len(itens) < 2:
        return None, "múltipla sem itens suficientes"

    detalhes = []
    for item_texto in itens:
        item_aposta = montar_item_aposta_para_validar(item_texto, aposta)
        mercado = item_aposta.get("mercado", "Outro")
        if mercado == "Outro":
            detalhes.append(f"{item_texto}: mercado não identificado")
            return None, " | ".join(detalhes)

        status, msg = validar_item_multipla_universal(item_aposta)
        detalhes.append(f"{item_texto} [{mercado}]: {status or msg}")

        if status == "perdida":
            return "perdida", " | ".join(detalhes)
        if status != "ganha":
            return None, " | ".join(detalhes)

    return "ganha", " | ".join(detalhes)






# ============================================================
# V25 - FORMATAÇÃO INTELIGENTE DE MÚLTIPLAS COMBINADAS
# ============================================================

def dividir_itens_mercados_mesma_linha(texto):
    bruto = limpar_linha(texto)
    bruto = re.sub(r"\b(resultado final|futebol)\b", " ", bruto, flags=re.I)
    bruto = re.sub(r"\s+", " ", bruto).strip(" /-|")
    partes = re.split(r"\s*(?:/|,|\+|;|\s+e\s+|\s+and\s+)\s*", bruto, flags=re.I)

    saida = []
    for p in partes:
        p = limpar_linha(p).strip(" /-|")
        if not p:
            continue
        n = normalizar_nome(p)

        if re.search(r"\d+[,.]\d+", p) and texto_tem(n, ["cantos", "canto", "escanteios", "escanteio", "corners", "corner"]):
            if not detectar_direcao(p):
                p = "Over " + p

        if re.search(r"\d+[,.]\d+", p) and texto_tem(n, ["gols", "gol", "goals"]):
            if not detectar_direcao(p) and texto_tem(normalizar_nome(bruto), ["over", "mais de"]):
                p = "Over " + p

        saida.append(p)

    if len(saida) == 1:
        s = saida[0]
        tokens = []

        m_gols = re.search(r"(over|mais de|under|menos de)?\s*(\d+[,.]\d+)\s*(gols?|goals?)", s, flags=re.I)
        if m_gols:
            dire = m_gols.group(1) or "over"
            tokens.append(f"{dire} {m_gols.group(2)} gols")

        if eh_texto_btts(s):
            tokens.append("BTTS")

        m_cantos = re.search(r"(over|mais de|under|menos de)?\s*(\d+[,.]\d+)\s*(cantos?|escanteios?|corners?)", s, flags=re.I)
        if m_cantos:
            dire = m_cantos.group(1) or "over"
            tokens.append(f"{dire} {m_cantos.group(2)} cantos")

        if len(tokens) > 1:
            return tokens

    return saida


def classificar_item_combinada_visual(item, jogo=""):
    item = limpar_linha(item)
    t = normalizar_nome(item)

    out = {"texto": item, "mercado": "Outro", "selecao": "", "direcao": "", "linha": None}

    if not item:
        return out

    if eh_texto_btts(item):
        out["mercado"] = "Ambas Marcam"
        out["selecao"] = detectar_btts_resposta(item) or "sim"
        return out

    direcao = detectar_direcao(item)
    linha = extrair_linha(item)

    if texto_tem(t, ["cantos", "canto", "escanteios", "escanteio", "corner", "corners"]):
        out["mercado"] = "Escanteios"
        out["direcao"] = direcao or "over"
        out["selecao"] = out["direcao"]
        out["linha"] = linha
        return out

    if texto_tem(t, ["chutes a gol", "chutes no gol", "shot on target", "shots on target"]):
        out["mercado"] = "Chutes no Gol"
        out["direcao"] = direcao or ("over" if linha is not None else "")
        out["selecao"] = out["direcao"]
        out["linha"] = linha
        return out

    if texto_tem(t, ["chutes", "shots", "finalizacoes", "finalizações"]):
        out["mercado"] = "Chutes"
        out["direcao"] = direcao or ("over" if linha is not None else "")
        out["selecao"] = out["direcao"]
        out["linha"] = linha
        return out

    if texto_tem(t, ["gols", "gol", "goals"]) or direcao:
        out["mercado"] = "Total"
        out["direcao"] = direcao or ("over" if linha is not None else "")
        out["selecao"] = out["direcao"]
        out["linha"] = linha
        return out

    cls = classificar_aposta(item, jogo)
    out["mercado"] = cls.get("mercado", "Outro")
    out["selecao"] = cls.get("selecao", "")
    out["direcao"] = cls.get("direcao", "")
    out["linha"] = cls.get("linha", None)
    return out


def resumir_multiplas_para_campos(itens):
    mercados, selecoes, linhas = [], [], []
    for it in itens:
        mercados.append(it.get("mercado", "Outro") or "Outro")
        sel = it.get("selecao", "") or it.get("direcao", "")
        selecoes.append(sel if sel else "-")
        linha = it.get("linha", None)
        if isinstance(linha, float):
            linhas.append(str(linha).rstrip("0").rstrip("."))
        elif linha is None:
            linhas.append("-")
        else:
            linhas.append(str(linha))
    return {"mercado": " / ".join(mercados), "selecao": " / ".join(selecoes), "linha": " / ".join(linhas)}



# ============================================================
# V27 - FIX LINHA EM MÚLTIPLAS
# Ex: "Ambas Marcam / Mais de 10.5 Escanteios"
# mercado: Ambas Marcam / Escanteios
# selecao: sim / over
# linha: - / 10.5
# ============================================================

def extrair_linha_mercado_v27(texto):
    s = str(texto or "").replace(",", ".")

    # Prioriza decimal.
    m = re.search(r"\b(\d{1,3}\.\d+)\b", s)
    if m:
        try:
            return float(m.group(1))
        except:
            pass

    # Depois inteiro, mas evita odds/valores grandes demais.
    m = re.search(r"\b(\d{1,3})\b", s)
    if m:
        try:
            v = float(m.group(1))
            if 0 <= v <= 99:
                return v
        except:
            pass

    return None


def normalizar_direcao_linha_v27(texto):
    direcao = detectar_direcao(texto)
    linha = extrair_linha_mercado_v27(texto)

    # Se tem linha e mercado quantitativo sem direção explícita, assume over.
    t = normalizar_nome(texto)
    if linha is not None and not direcao and texto_tem(t, [
        "gols", "gol", "goals", "escanteios", "escanteio", "cantos", "canto",
        "corner", "corners", "chutes", "shots", "cartoes", "cartões", "cards"
    ]):
        direcao = "over"

    return direcao, linha


def classificar_item_combinada_visual_v27(item, jogo=""):
    item = limpar_linha(item)
    t = normalizar_nome(item)

    out = {
        "texto": item,
        "mercado": "Outro",
        "selecao": "",
        "direcao": "",
        "linha": None,
        "periodo": detectar_periodo(item)
    }

    if not item:
        return out

    if eh_texto_btts(item):
        out["mercado"] = "Ambas Marcam"
        out["selecao"] = detectar_btts_resposta(item) or "sim"
        out["linha"] = None
        return out

    if texto_tem(t, [
        "algum time vence ht", "algum time vence o ht",
        "algum time vence 1 tempo", "algum time vence o 1 tempo",
        "algum time vence primeiro tempo", "algum time vence o primeiro tempo"
    ]):
        out["mercado"] = "HT Resultado"
        out["selecao"] = "sim"
        out["linha"] = None
        out["periodo"] = "1º tempo"
        return out

    direcao, linha = normalizar_direcao_linha_v27(item)

    if texto_tem(t, ["escanteio", "escanteios", "canto", "cantos", "corner", "corners"]):
        out["mercado"] = "Escanteios"
        out["direcao"] = direcao or "over"
        out["selecao"] = out["direcao"]
        out["linha"] = linha
        return out

    if texto_tem(t, ["chutes a gol", "chutes no gol", "shot on target", "shots on target"]):
        out["mercado"] = "Chutes no Gol"
        out["direcao"] = direcao or ("over" if linha is not None else "")
        out["selecao"] = out["direcao"]
        out["linha"] = linha
        return out

    if texto_tem(t, ["chutes", "shots", "finalizacoes", "finalizações"]):
        out["mercado"] = "Chutes"
        out["direcao"] = direcao or ("over" if linha is not None else "")
        out["selecao"] = out["direcao"]
        out["linha"] = linha
        return out

    if texto_tem(t, ["gols", "gol", "goals"]) or direcao:
        out["mercado"] = "Total de Gols" if texto_tem(t, ["gols", "gol", "goals"]) else "Total"
        out["direcao"] = direcao or ("over" if linha is not None else "")
        out["selecao"] = out["direcao"]
        out["linha"] = linha
        return out

    cls = classificar_aposta(item, jogo)
    out["mercado"] = cls.get("mercado", "Outro")
    out["selecao"] = cls.get("selecao", "")
    out["direcao"] = cls.get("direcao", "")
    out["linha"] = cls.get("linha", None)
    out["periodo"] = cls.get("periodo", detectar_periodo(item))
    return out


def aplicar_formatacao_multiplas_combinadas(resultado):
    aposta_txt = str(resultado.get("aposta", ""))
    jogo = resultado.get("jogo", "")
    mercados_txt = aposta_txt.split(" - ", 1)[1] if " - " in aposta_txt else aposta_txt

    itens_txt = dividir_itens_mercados_mesma_linha(mercados_txt)
    if len(itens_txt) < 2:
        return resultado

    itens = [classificar_item_combinada_visual_v27(x, jogo) for x in itens_txt]
    itens_validos = [i for i in itens if i.get("mercado") != "Outro"]

    if len(itens_validos) < 2:
        return resultado

    resumo = resumir_multiplas_para_campos(itens_validos)

    resultado["mercado"] = resumo["mercado"]
    resultado["selecao"] = resumo["selecao"]
    resultado["linha"] = resumo["linha"]
    resultado["direcao"] = ""
    resultado["mercado_api"] = "Múltipla - Combinada"
    resultado["itens_multipla_detalhados"] = itens_validos
    resultado["itens_multipla"] = {
        "jogos": [jogo] if jogo else [],
        "selecoes": [i.get("texto", "") for i in itens_validos],
        "qtd_jogos": 1 if jogo else 0,
        "qtd_selecoes": len(itens_validos)
    }
    return resultado




# ============================================================
# V26 - MULTIPLAS COM DESCRIÇÃO DE MERCADO NO FINAL
# ============================================================

def item_tem_selecao_clara_v26(item):
    t = normalizar_nome(item)

    if detectar_direcao(item):
        return True

    if eh_texto_btts(item):
        return True

    if texto_tem(t, [
        "vence", "vencem", "vencer", "vencerem", "ml", "moneyline",
        "ou empate", "dupla chance", "chance dupla",
        "marcador", "assistencia", "assistência",
        "tem 1 ou mais", "chutes", "chutes a gol",
        "algum time vence"
    ]):
        return True

    if re.search(r"\d+[,.]\d+", str(item)) and texto_tem(t, [
        "gols", "gol", "escanteios", "escanteio", "cantos", "canto",
        "chutes", "cartoes", "cartões", "cards"
    ]):
        return True

    return False


def item_e_descricao_mercado_v26(item):
    t = normalizar_nome(item)

    if item_tem_selecao_clara_v26(item):
        return False

    descricoes = [
        "total de gols", "total gols", "total de gol",
        "total de escanteios", "total escanteios", "total de cantos", "total cantos",
        "resultado final", "mercado final",
        "total de chutes", "total chutes",
        "total de cartoes", "total de cartões"
    ]

    return any(d in t for d in descricoes)


def juntar_descricoes_de_mercado_v26(partes):
    partes = [limpar_linha(p).strip(" /-|") for p in partes if limpar_linha(p).strip(" /-|")]

    if len(partes) < 3:
        return partes

    selecoes = [p for p in partes if item_tem_selecao_clara_v26(p)]
    descricoes = [p for p in partes if item_e_descricao_mercado_v26(p)]

    if len(selecoes) >= 1 and len(descricoes) >= 1 and len(selecoes) + len(descricoes) == len(partes):
        saida = []
        for i, sel in enumerate(selecoes):
            desc = descricoes[i] if i < len(descricoes) else ""
            saida.append(sel + (" | " + desc if desc else ""))
        return saida

    return partes


def classificar_item_combinada_visual_v26(item, jogo=""):
    item_original = limpar_linha(item)
    selecao_txt = item_original
    descricao_txt = ""

    if " | " in item_original:
        selecao_txt, descricao_txt = [x.strip() for x in item_original.split(" | ", 1)]

    texto_analise = (selecao_txt + " " + descricao_txt).strip()
    t = normalizar_nome(texto_analise)

    out = {
        "texto": selecao_txt,
        "descricao_mercado": descricao_txt,
        "mercado": "Outro",
        "selecao": "",
        "direcao": "",
        "linha": None,
        "periodo": detectar_periodo(texto_analise)
    }

    if not selecao_txt:
        return out

    if texto_tem(t, [
        "algum time vence ht", "algum time vence o ht",
        "algum time vence 1 tempo", "algum time vence o 1 tempo",
        "algum time vence primeiro tempo", "algum time vence o primeiro tempo"
    ]):
        out["mercado"] = "HT Resultado"
        out["selecao"] = "sim"
        out["linha"] = None
        out["periodo"] = "1º tempo"
        return out

    if eh_texto_btts(texto_analise):
        out["mercado"] = "Ambas Marcam"
        out["selecao"] = detectar_btts_resposta(texto_analise) or "sim"
        out["linha"] = None
        return out

    # ML / time vence
    if texto_tem(t, [" ml", "ml ", "vence", "vencem", "para vencer", "moneyline"]):
        cls = classificar_aposta(selecao_txt, jogo)
        if cls.get("mercado") == "Moneyline" or texto_tem(t, ["ml", "vence", "vencem", "para vencer"]):
            out["mercado"] = "Moneyline"
            selecao = cls.get("selecao", "")
            if not selecao or normalizar_nome(selecao) in ["resultado final", "resultado", "final"]:
                selecao = re.sub(r"\b(ml|vence|vencem|vencer|vencerem|para vencer|ganha|ganham)\b", "", selecao_txt, flags=re.I)
                selecao = re.sub(r"\s+", " ", selecao).strip()
            out["selecao"] = selecao
            return out

    direcao = detectar_direcao(selecao_txt) or detectar_direcao(texto_analise)
    linha = extrair_linha(selecao_txt)

    if linha is not None and not direcao and texto_tem(t, [
        "gols", "gol", "escanteios", "escanteio", "cantos", "canto",
        "chutes", "cartoes", "cartões"
    ]):
        direcao = "over"

    if texto_tem(t, ["escanteio", "escanteios", "canto", "cantos", "corner", "corners"]):
        out["mercado"] = "Escanteios"
        out["direcao"] = direcao or "over"
        out["selecao"] = out["direcao"]
        out["linha"] = linha
        return out

    if texto_tem(t, ["chutes a gol", "chutes no gol", "shot on target", "shots on target"]):
        out["mercado"] = "Chutes no Gol"
        out["direcao"] = direcao or ("over" if linha is not None else "")
        out["selecao"] = out["direcao"]
        out["linha"] = linha
        return out

    if texto_tem(t, ["chutes", "shots", "finalizacoes", "finalizações"]):
        out["mercado"] = "Chutes"
        out["direcao"] = direcao or ("over" if linha is not None else "")
        out["selecao"] = out["direcao"]
        out["linha"] = linha
        return out

    if texto_tem(t, ["gols", "gol", "goals"]) or direcao:
        out["mercado"] = "Total de Gols" if texto_tem(t, ["gols", "gol", "goals"]) else "Total"
        out["direcao"] = direcao or ("over" if linha is not None else "")
        out["selecao"] = out["direcao"]
        out["linha"] = linha
        return out

    cls = classificar_aposta(selecao_txt, jogo)
    out["mercado"] = cls.get("mercado", "Outro")
    out["selecao"] = cls.get("selecao", "")
    out["direcao"] = cls.get("direcao", "")
    out["linha"] = cls.get("linha", None)
    out["periodo"] = cls.get("periodo", detectar_periodo(texto_analise))
    return out


def dividir_itens_mercados_mesma_linha(texto):
    bruto = limpar_linha(texto)
    bruto = re.sub(r"\b(futebol)\b", " ", bruto, flags=re.I)
    bruto = re.sub(r"\s+", " ", bruto).strip(" /-|")

    partes = re.split(r"\s*(?:/|,|\+|;|\s+e\s+|\s+and\s+)\s*", bruto, flags=re.I)
    partes = [limpar_linha(p).strip(" /-|") for p in partes if limpar_linha(p).strip(" /-|")]

    partes = juntar_descricoes_de_mercado_v26(partes)

    saida = []
    for p in partes:
        n = normalizar_nome(p)

        if re.search(r"\d+[,.]\d+", p) and texto_tem(n, ["cantos", "canto", "escanteios", "escanteio", "corners", "corner"]):
            if not detectar_direcao(p):
                p = "Over " + p

        if re.search(r"\d+[,.]\d+", p) and texto_tem(n, ["gols", "gol", "goals"]):
            if not detectar_direcao(p) and texto_tem(normalizar_nome(bruto), ["over", "mais de"]):
                p = "Over " + p

        saida.append(p)

    if len(saida) == 1:
        s = saida[0]
        tokens = []

        m_gols = re.search(r"(over|mais de|under|menos de)?\s*(\d+[,.]\d+)\s*(gols?|goals?)(?:\s*no\s*1[ºo]?\s*tempo)?", s, flags=re.I)
        if m_gols:
            dire = m_gols.group(1) or "over"
            extra = " no 1º tempo" if re.search(r"1[ºo]?\s*tempo", s, flags=re.I) else ""
            tokens.append(f"{dire} {m_gols.group(2)} gols{extra}")

        if eh_texto_btts(s):
            tokens.append("BTTS")

        m_cantos = re.search(r"(over|mais de|under|menos de)?\s*(\d+[,.]\d+)\s*(cantos?|escanteios?|corners?)", s, flags=re.I)
        if m_cantos:
            dire = m_cantos.group(1) or "over"
            tokens.append(f"{dire} {m_cantos.group(2)} cantos")

        if len(tokens) > 1:
            return tokens

    return saida


def resumir_multiplas_para_campos(itens):
    mercados, selecoes, linhas, periodos = [], [], [], []

    for it in itens:
        mercado = it.get("mercado", "Outro") or "Outro"
        selecao = it.get("selecao", "") or it.get("direcao", "")
        linha = it.get("linha", None)
        periodo = it.get("periodo", "jogo inteiro") or "jogo inteiro"

        mercados.append(mercado)
        selecoes.append(selecao if selecao else "-")
        linhas.append(str(linha).rstrip("0").rstrip(".") if isinstance(linha, float) else (str(linha) if linha is not None else "-"))
        periodos.append(periodo)

    return {
        "mercado": " / ".join(mercados),
        "selecao": " / ".join(selecoes),
        "linha": " / ".join(linhas),
        "periodo": " / ".join(periodos)
    }



# ============================================================
# V27 - FIX LINHA EM MÚLTIPLAS
# Ex: "Ambas Marcam / Mais de 10.5 Escanteios"
# mercado: Ambas Marcam / Escanteios
# selecao: sim / over
# linha: - / 10.5
# ============================================================

def extrair_linha_mercado_v27(texto):
    s = str(texto or "").replace(",", ".")

    # Prioriza decimal.
    m = re.search(r"\b(\d{1,3}\.\d+)\b", s)
    if m:
        try:
            return float(m.group(1))
        except:
            pass

    # Depois inteiro, mas evita odds/valores grandes demais.
    m = re.search(r"\b(\d{1,3})\b", s)
    if m:
        try:
            v = float(m.group(1))
            if 0 <= v <= 99:
                return v
        except:
            pass

    return None


def normalizar_direcao_linha_v27(texto):
    direcao = detectar_direcao(texto)
    linha = extrair_linha_mercado_v27(texto)

    # Se tem linha e mercado quantitativo sem direção explícita, assume over.
    t = normalizar_nome(texto)
    if linha is not None and not direcao and texto_tem(t, [
        "gols", "gol", "goals", "escanteios", "escanteio", "cantos", "canto",
        "corner", "corners", "chutes", "shots", "cartoes", "cartões", "cards"
    ]):
        direcao = "over"

    return direcao, linha


def classificar_item_combinada_visual_v27(item, jogo=""):
    item = limpar_linha(item)
    t = normalizar_nome(item)

    out = {
        "texto": item,
        "mercado": "Outro",
        "selecao": "",
        "direcao": "",
        "linha": None,
        "periodo": detectar_periodo(item)
    }

    if not item:
        return out

    if eh_texto_btts(item):
        out["mercado"] = "Ambas Marcam"
        out["selecao"] = detectar_btts_resposta(item) or "sim"
        out["linha"] = None
        return out

    if texto_tem(t, [
        "algum time vence ht", "algum time vence o ht",
        "algum time vence 1 tempo", "algum time vence o 1 tempo",
        "algum time vence primeiro tempo", "algum time vence o primeiro tempo"
    ]):
        out["mercado"] = "HT Resultado"
        out["selecao"] = "sim"
        out["linha"] = None
        out["periodo"] = "1º tempo"
        return out

    direcao, linha = normalizar_direcao_linha_v27(item)

    if texto_tem(t, ["escanteio", "escanteios", "canto", "cantos", "corner", "corners"]):
        out["mercado"] = "Escanteios"
        out["direcao"] = direcao or "over"
        out["selecao"] = out["direcao"]
        out["linha"] = linha
        return out

    if texto_tem(t, ["chutes a gol", "chutes no gol", "shot on target", "shots on target"]):
        out["mercado"] = "Chutes no Gol"
        out["direcao"] = direcao or ("over" if linha is not None else "")
        out["selecao"] = out["direcao"]
        out["linha"] = linha
        return out

    if texto_tem(t, ["chutes", "shots", "finalizacoes", "finalizações"]):
        out["mercado"] = "Chutes"
        out["direcao"] = direcao or ("over" if linha is not None else "")
        out["selecao"] = out["direcao"]
        out["linha"] = linha
        return out

    if texto_tem(t, ["gols", "gol", "goals"]) or direcao:
        out["mercado"] = "Total de Gols" if texto_tem(t, ["gols", "gol", "goals"]) else "Total"
        out["direcao"] = direcao or ("over" if linha is not None else "")
        out["selecao"] = out["direcao"]
        out["linha"] = linha
        return out

    cls = classificar_aposta(item, jogo)
    out["mercado"] = cls.get("mercado", "Outro")
    out["selecao"] = cls.get("selecao", "")
    out["direcao"] = cls.get("direcao", "")
    out["linha"] = cls.get("linha", None)
    out["periodo"] = cls.get("periodo", detectar_periodo(item))
    return out


def aplicar_formatacao_multiplas_combinadas(resultado):
    aposta_txt = str(resultado.get("aposta", ""))
    jogo = resultado.get("jogo", "")

    mercados_txt = aposta_txt.split(" - ", 1)[1] if " - " in aposta_txt else aposta_txt
    itens_txt = dividir_itens_mercados_mesma_linha(mercados_txt)

    if len(itens_txt) < 2:
        return resultado

    itens = [classificar_item_combinada_visual_v27(x, jogo) for x in itens_txt]
    itens_validos = [i for i in itens if i.get("mercado") != "Outro"]

    if len(itens_validos) < 2:
        return resultado

    resumo = resumir_multiplas_para_campos(itens_validos)

    resultado["mercado"] = resumo["mercado"]
    resultado["selecao"] = resumo["selecao"]
    resultado["linha"] = resumo["linha"]
    resultado["periodo"] = resumo["periodo"]
    resultado["direcao"] = ""
    resultado["mercado_api"] = "Múltipla - Combinada"
    resultado["itens_multipla_detalhados"] = itens_validos
    resultado["itens_multipla"] = {
        "jogos": [jogo] if jogo else [],
        "selecoes": [i.get("texto", "") for i in itens_validos],
        "qtd_jogos": 1 if jogo else 0,
        "qtd_selecoes": len(itens_validos)
    }

    return resultado




# ============================================================
# V28 - MOTOR COMPLETO DE COMBINAÇÕES
# ============================================================

def extrair_linha_mercado_v28(texto):
    s = str(texto or "").replace(",", ".")
    m = re.search(r"\b(\d{1,3}(?:\.\d+)?)\s*\+", s)
    if m:
        return float(m.group(1))
    m = re.search(r"\b(\d{1,3}\.\d+)\b", s)
    if m:
        return float(m.group(1))
    m = re.search(r"\b(\d{1,3})\b", s)
    if m:
        v = float(m.group(1))
        if 0 <= v <= 99:
            return v
    return None


def detectar_direcao_v28(texto):
    s = str(texto or "")
    t = normalizar_nome(s)
    d = detectar_direcao(s)
    if d:
        return d
    if re.search(r"\b\d+(?:[,.]\d+)?\s*\+", s):
        return "over"
    if texto_tem(t, ["ou mais", "pelo menos", "no minimo", "no mínimo"]):
        return "over"
    return ""


def expandir_abreviacoes_v28(texto):
    s = str(texto or "")
    trocas = [
        (r"\besc\b", "escanteios"),
        (r"\bescs\b", "escanteios"),
        (r"\bcantos?\b", "escanteios"),
        (r"\bcards?\b", "cartoes"),
        (r"\bcart(ao|ão|oes|ões)\b", "cartoes"),
        (r"\bdc\b", "dupla chance"),
    ]
    for rgx, rep in trocas:
        s = re.sub(rgx, rep, s, flags=re.I)
    return re.sub(r"\s+", " ", s).strip()


def split_inteligente_combinacao_v28(texto):
    s = expandir_abreviacoes_v28(limpar_linha(texto))
    s = re.sub(r"\b(futebol)\b", " ", s, flags=re.I)
    s = re.sub(r"R\$\s*\d+[,.]?\d*", " ", s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip(" /-|")

    direcao_global = detectar_direcao_v28(s)
    partes = re.split(r"\s*(?:/|,|;|\+|\s+e\s+|\s+and\s+)\s*", s, flags=re.I)
    partes = [expandir_abreviacoes_v28(p).strip(" /-|") for p in partes if p.strip(" /-|")]

    saida = []
    for p in partes:
        n = normalizar_nome(p)
        if re.search(r"\d+(?:[,.]\d+)?", p) and not detectar_direcao_v28(p):
            if texto_tem(n, ["gols", "gol", "escanteios", "cartoes", "chutes"]):
                p = (direcao_global or "over") + " " + p
        saida.append(p)

    if len(saida) <= 1:
        tokens = []
        patterns = [
            r"(?:over|under|mais de|menos de)?\s*\d+(?:[,.]\d+)?\+?\s*(?:gols?|goals?)",
            r"(?:over|under|mais de|menos de)?\s*\d+(?:[,.]\d+)?\+?\s*(?:escanteios?|corners?)",
            r"(?:over|under|mais de|menos de)?\s*\d+(?:[,.]\d+)?\+?\s*(?:cartoes|cartões|cards?)",
            r"(?:over|under|mais de|menos de)?\s*\d+(?:[,.]\d+)?\+?\s*(?:chutes(?: a gol| no gol)?|shots(?: on target)?)",
        ]
        for pat in patterns:
            for m in re.finditer(pat, s, flags=re.I):
                tok = m.group(0).strip()
                if tok and tok not in tokens:
                    if not detectar_direcao_v28(tok):
                        tok = (direcao_global or "over") + " " + tok
                    tokens.append(tok)

        if eh_texto_btts(s):
            tokens.append("BTTS")

        m_dc = re.search(r"(dupla chance\s+.+?)(?:$|\s+HT|\s+1[ºo]?\s*tempo)", s, flags=re.I)
        if m_dc:
            tok = m_dc.group(1).strip()
            if re.search(r"\b(HT|1[ºo]?\s*tempo|primeiro tempo)\b", s, flags=re.I):
                tok += " HT"
            tokens.append(tok)

        for m in re.finditer(r"([A-Za-zÀ-ÿ'.\- ]{3,})\s+anytime\b", s, flags=re.I):
            tok = m.group(0).strip()
            if tok not in tokens:
                tokens.append(tok)

        if len(tokens) > 1:
            saida = tokens

    final = []
    vistos = set()
    for p in saida:
        p = re.sub(r"\s+", " ", p).strip(" /-|")
        n = normalizar_nome(p)
        if p and n not in vistos:
            vistos.add(n)
            final.append(p)
    return final


def item_tem_selecao_clara_v28(item):
    t = normalizar_nome(item)
    return (
        bool(detectar_direcao_v28(item)) or
        eh_texto_btts(item) or
        bool(re.search(r"\d+(?:[,.]\d+)?\+", str(item))) or
        texto_tem(t, [
            "vence", "vencem", "vencer", "vencerem", "ml", "moneyline",
            "ou empate", "dupla chance", "chance dupla",
            "marcador", "assistencia", "assistência", "anytime",
            "tem 1 ou mais", "chutes", "algum time vence"
        ]) or
        (bool(re.search(r"\d+[,.]\d+", str(item))) and texto_tem(t, ["gols", "gol", "escanteios", "cartoes", "chutes"]))
    )


def item_e_descricao_mercado_v28(item):
    t = normalizar_nome(item)
    if item_tem_selecao_clara_v28(item):
        return False
    return texto_tem(t, [
        "total de gols", "total gols", "total de escanteios", "total escanteios",
        "total de cartoes", "total de cartões", "total cartoes", "total cards",
        "total de chutes", "resultado final", "mercado final"
    ])


def juntar_descricoes_de_mercado_v28(partes):
    partes = [limpar_linha(p).strip(" /-|") for p in partes if limpar_linha(p).strip(" /-|")]
    if len(partes) < 3:
        return partes
    selecoes = [p for p in partes if item_tem_selecao_clara_v28(p)]
    descricoes = [p for p in partes if item_e_descricao_mercado_v28(p)]
    if len(selecoes) >= 1 and len(descricoes) >= 1 and len(selecoes) + len(descricoes) == len(partes):
        return [sel + (" | " + descricoes[i] if i < len(descricoes) else "") for i, sel in enumerate(selecoes)]
    return partes


def limpar_nome_marcador_anytime_v28(texto):
    s = limpar_linha(texto)
    s = re.sub(r"\b(anytime|a qualquer momento|para marcar|marcador|gol do jogador|to score)\b", " ", s, flags=re.I)
    s = re.sub(r"\d+(?:[,.]\d+)?\+?", " ", s)
    s = re.sub(r"[:/|()\[\]{}+\-]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def classificar_item_combinada_visual_v28(item, jogo=""):
    item_original = expandir_abreviacoes_v28(limpar_linha(item))
    selecao_txt = item_original
    descricao_txt = ""
    if " | " in item_original:
        selecao_txt, descricao_txt = [x.strip() for x in item_original.split(" | ", 1)]

    texto_analise = (selecao_txt + " " + descricao_txt).strip()
    t = normalizar_nome(texto_analise)
    out = {"texto": selecao_txt, "descricao_mercado": descricao_txt, "mercado": "Outro", "selecao": "", "direcao": "", "linha": None, "periodo": detectar_periodo(texto_analise)}

    if texto_tem(t, ["vence de 0 o ht", "vence de zero o ht", "vence sem sofrer o ht", "vence de 0 no ht"]):
        out["mercado"] = "HT Vence sem sofrer"
        out["periodo"] = "1º tempo"
        out["selecao"] = re.sub(r"\b(vence de 0 o ht|vence de zero o ht|vence sem sofrer o ht|vence de 0 no ht|ht)\b", "", selecao_txt, flags=re.I).strip()
        return out

    if texto_tem(t, ["algum time vence ht", "algum time vence o ht", "algum time vence 1 tempo", "algum time vence primeiro tempo"]):
        out["mercado"] = "HT Resultado"
        out["selecao"] = "sim"
        out["periodo"] = "1º tempo"
        return out

    if eh_texto_btts(texto_analise):
        out["mercado"] = "Ambas Marcam"
        out["selecao"] = detectar_btts_resposta(texto_analise) or "sim"
        return out

    if texto_tem(t, ["anytime", "a qualquer momento", "to score"]):
        out["mercado"] = "Marcador"
        out["selecao"] = limpar_nome_marcador_anytime_v28(selecao_txt)
        return out

    if texto_tem(t, ["dupla chance"]):
        out["mercado"] = "Dupla Chance"
        out["periodo"] = "1º tempo" if texto_tem(t, ["ht", "1 tempo", "primeiro tempo"]) else "jogo inteiro"
        txt = re.sub(r"\b(dupla chance|dc|ht|1[ºo]?\s*tempo|primeiro tempo)\b", " ", selecao_txt, flags=re.I)
        txt = re.sub(r"\s+", " ", txt).strip()
        out["selecao"] = detectar_dupla_chance_selecao(txt) or txt
        return out

    if re.search(r"\bML\b", selecao_txt, flags=re.I) or texto_tem(t, ["moneyline", "vence", "vencem", "para vencer"]):
        out["mercado"] = "Moneyline"
        selecao = re.sub(r"\b(ML|moneyline|vence|vencem|vencer|vencerem|para vencer|ganha|ganham)\b", " ", selecao_txt, flags=re.I)
        out["selecao"] = re.sub(r"\s+", " ", selecao).strip()
        return out

    direcao = detectar_direcao_v28(selecao_txt) or detectar_direcao_v28(texto_analise)
    linha = extrair_linha_mercado_v28(selecao_txt)
    if linha is not None and not direcao and texto_tem(t, ["gols", "gol", "escanteios", "cartoes", "chutes"]):
        direcao = "over"

    if texto_tem(t, ["escanteio", "escanteios", "corner", "corners"]):
        out.update({"mercado": "Escanteios", "direcao": direcao or "over", "selecao": direcao or "over", "linha": linha})
        return out
    if texto_tem(t, ["cartoes", "cartões", "cards", "yellow cards", "red cards"]):
        out.update({"mercado": "Cartões", "direcao": direcao or "over", "selecao": direcao or "over", "linha": linha})
        return out
    if texto_tem(t, ["chutes a gol", "chutes no gol", "shot on target", "shots on target"]):
        out.update({"mercado": "Chutes no Gol", "direcao": direcao or ("over" if linha is not None else ""), "selecao": direcao or ("over" if linha is not None else ""), "linha": linha})
        return out
    if texto_tem(t, ["chutes", "shots", "finalizacoes", "finalizações"]):
        out.update({"mercado": "Chutes", "direcao": direcao or ("over" if linha is not None else ""), "selecao": direcao or ("over" if linha is not None else ""), "linha": linha})
        return out
    if texto_tem(t, ["gols", "gol", "goals"]) or direcao:
        out.update({"mercado": "Total de Gols" if texto_tem(t, ["gols", "gol", "goals"]) else "Total", "direcao": direcao or ("over" if linha is not None else ""), "selecao": direcao or ("over" if linha is not None else ""), "linha": linha})
        return out

    cls = classificar_aposta(selecao_txt, jogo)
    out.update({"mercado": cls.get("mercado", "Outro"), "selecao": cls.get("selecao", ""), "direcao": cls.get("direcao", ""), "linha": cls.get("linha", None), "periodo": cls.get("periodo", detectar_periodo(texto_analise))})
    return out


def dividir_itens_mercados_mesma_linha(texto):
    return juntar_descricoes_de_mercado_v28(split_inteligente_combinacao_v28(texto))


def resumir_multiplas_para_campos(itens):
    mercados, selecoes, linhas, periodos = [], [], [], []
    for it in itens:
        mercados.append(it.get("mercado", "Outro") or "Outro")
        selecoes.append(it.get("selecao", "") or it.get("direcao", "") or "-")
        linha = it.get("linha", None)
        linhas.append(str(linha).rstrip("0").rstrip(".") if isinstance(linha, float) else (str(linha) if linha is not None else "-"))
        periodos.append(it.get("periodo", "jogo inteiro") or "jogo inteiro")
    return {"mercado": " / ".join(mercados), "selecao": " / ".join(selecoes), "linha": " / ".join(linhas), "periodo": " / ".join(periodos)}


def aplicar_formatacao_multiplas_combinadas(resultado):
    aposta_txt = str(resultado.get("aposta", ""))
    jogo = resultado.get("jogo", "")
    mercados_txt = aposta_txt.split(" - ", 1)[1] if " - " in aposta_txt else aposta_txt
    itens_txt = dividir_itens_mercados_mesma_linha(mercados_txt)

    if len(itens_txt) < 2:
        item = classificar_item_combinada_visual_v28(mercados_txt, jogo)
        if item.get("mercado") != "Outro":
            resultado["mercado"] = item["mercado"]
            resultado["selecao"] = item["selecao"]
            resultado["linha"] = item["linha"]
            resultado["periodo"] = item["periodo"]
        return resultado

    itens = [classificar_item_combinada_visual_v28(x, jogo) for x in itens_txt]
    itens_validos = [i for i in itens if i.get("mercado") != "Outro"]
    if len(itens_validos) < 2:
        return resultado

    resumo = resumir_multiplas_para_campos(itens_validos)
    resultado.update({"mercado": resumo["mercado"], "selecao": resumo["selecao"], "linha": resumo["linha"], "periodo": resumo["periodo"], "direcao": "", "mercado_api": "Múltipla - Combinada"})
    resultado["itens_multipla_detalhados"] = itens_validos
    resultado["itens_multipla"] = {"jogos": [jogo] if jogo else [], "selecoes": [i.get("texto", "") for i in itens_validos], "qtd_jogos": 1 if jogo else 0, "qtd_selecoes": len(itens_validos)}
    return resultado


def validar_ht_vence_sem_sofrer_v28(aposta, resultado):
    home = resultado.get("home_team", "")
    away = resultado.get("away_team", "")
    selecao = aposta.get("selecao", "")
    ht_home = resultado.get("home_score_ht", resultado.get("home_ht_score"))
    ht_away = resultado.get("away_score_ht", resultado.get("away_ht_score"))
    if ht_home is None or ht_away is None:
        return None
    try:
        ht_home, ht_away = int(ht_home), int(ht_away)
    except:
        return None
    if nome_bate(selecao, home):
        return "ganha" if ht_home > ht_away and ht_away == 0 else "perdida"
    if nome_bate(selecao, away):
        return "ganha" if ht_away > ht_home and ht_home == 0 else "perdida"
    return None





# ============================================================
# V30 - FIX API: buscar_resultado_futebol
# Corrige NameError quando versões anteriores perderam a função.
# ============================================================

def api_headers():
    headers = {}

    if API_KEY:
        headers["x-apisports-key"] = API_KEY

    return headers


def api_get(url, params=None):
    try:
        r = requests.get(url, headers=api_headers(), params=params or {}, timeout=20)

        if r.status_code != 200:
            print("ERRO API:", r.status_code, r.text[:300])
            return None

        return r.json()

    except Exception as e:
        print("ERRO REQUEST API:", e)
        return None


def extrair_data_para_api(aposta):
    dt = parse_data(aposta.get("data", ""))

    if not dt:
        dt = datetime.now()

    return dt.strftime("%Y-%m-%d")


def normalizar_nome_api(txt):
    return normalizar_nome(txt)


def score_match_time_api(nome, team):
    nome_n = normalizar_nome_api(nome)
    team_n = normalizar_nome_api(team)

    if not nome_n or not team_n:
        return 0

    if nome_n == team_n:
        return 100

    if nome_n in team_n or team_n in nome_n:
        return 85

    ratio = difflib.SequenceMatcher(None, nome_n, team_n).ratio()
    return int(ratio * 100)


def escolher_melhor_fixture_futebol(fixtures, aposta):
    jogo = aposta.get("jogo", "")
    selecao = aposta.get("selecao", "")

    casa, fora = extrair_times_jogo(jogo)

    alvo1 = casa or selecao or jogo
    alvo2 = fora

    melhor = None
    melhor_score = -1

    for item in fixtures:
        fixture = item.get("fixture", {})
        teams = item.get("teams", {})
        goals = item.get("goals", {})
        score = item.get("score", {})

        home = teams.get("home", {}).get("name", "")
        away = teams.get("away", {}).get("name", "")

        if alvo2:
            s1 = max(score_match_time_api(alvo1, home), score_match_time_api(alvo1, away))
            s2 = max(score_match_time_api(alvo2, home), score_match_time_api(alvo2, away))
            total = s1 + s2
        else:
            total = max(
                score_match_time_api(alvo1, home),
                score_match_time_api(alvo1, away),
                score_match_time_api(selecao, home),
                score_match_time_api(selecao, away),
            )

        if total > melhor_score:
            melhor_score = total
            melhor = item

    if not melhor or melhor_score < 55:
        return None

    fixture = melhor.get("fixture", {})
    teams = melhor.get("teams", {})
    goals = melhor.get("goals", {})
    score = melhor.get("score", {})

    halftime = score.get("halftime", {}) or {}

    return {
        "fixture_id": fixture.get("id"),
        "status": (fixture.get("status", {}) or {}).get("short", ""),
        "home_team": (teams.get("home", {}) or {}).get("name", ""),
        "away_team": (teams.get("away", {}) or {}).get("name", ""),
        "home_score": goals.get("home"),
        "away_score": goals.get("away"),
        "home_score_ht": halftime.get("home"),
        "away_score_ht": halftime.get("away"),
        "raw": melhor
    }


def buscar_resultado_futebol(aposta):
    """
    Busca resultado de futebol na API-Football.
    Usa endpoint /fixtures e tenta bater pelo nome do jogo/time.
    """
    if not API_KEY:
        print("API_KEY vazia em config.json")
        return None

    data_jogo = extrair_data_para_api(aposta)

    cache_key = json.dumps({
        "data": data_jogo,
        "jogo": normalizar_nome(aposta.get("jogo", "")),
        "selecao": normalizar_nome(aposta.get("selecao", ""))
    }, ensure_ascii=False)

    if cache_key in CACHE_RESULTADOS:
        return CACHE_RESULTADOS[cache_key]

    url = "https://v3.football.api-sports.io/fixtures"
    params = {"date": data_jogo}

    js = api_get(url, params)

    if not js:
        return None

    fixtures = js.get("response", [])

    if not fixtures:
        return None

    resultado = escolher_melhor_fixture_futebol(fixtures, aposta)

    if resultado:
        CACHE_RESULTADOS[cache_key] = resultado

    return resultado





# ============================================================
# V31 - FIX API: validar_aposta_com_resultado
# ============================================================

def validar_moneyline_resultado(aposta, resultado):
    selecao = aposta.get("selecao", "") or aposta.get("aposta", "")
    home = resultado.get("home_team", "")
    away = resultado.get("away_team", "")
    hs = resultado.get("home_score")
    aw = resultado.get("away_score")

    if hs is None or aw is None:
        return None

    if normalizar_nome(selecao) in ["empate", "draw", "x"]:
        return "ganha" if hs == aw else "perdida"

    if nome_bate(selecao, home):
        return "ganha" if hs > aw else "perdida"

    if nome_bate(selecao, away):
        return "ganha" if aw > hs else "perdida"

    return None


def validar_total_gols_resultado(aposta, resultado):
    direcao = aposta.get("direcao", "") or aposta.get("selecao", "")
    linha = aposta.get("linha", None)

    if linha in ["", "-", None]:
        linha = extrair_linha(aposta.get("aposta", ""))

    try:
        linha = float(linha)
    except:
        return None

    hs = resultado.get("home_score")
    aw = resultado.get("away_score")

    if hs is None or aw is None:
        return None

    total = float(hs) + float(aw)

    if direcao == "over":
        if total > linha:
            return "ganha"
        if total < linha:
            return "perdida"
        return "anulada"

    if direcao == "under":
        if total < linha:
            return "ganha"
        if total > linha:
            return "perdida"
        return "anulada"

    return None


def validar_btts_resultado(aposta, resultado):
    resposta = aposta.get("btts_resposta", "") or aposta.get("selecao", "") or detectar_btts_resposta_aposta(aposta)
    hs = resultado.get("home_score")
    aw = resultado.get("away_score")

    if hs is None or aw is None:
        return None

    ambos = int(hs) > 0 and int(aw) > 0

    if resposta == "sim":
        return "ganha" if ambos else "perdida"

    if resposta == "nao":
        return "ganha" if not ambos else "perdida"

    return None


def validar_dupla_chance_resultado(aposta, resultado):
    selecao = aposta.get("selecao", "")
    hs = resultado.get("home_score")
    aw = resultado.get("away_score")

    if hs is None or aw is None:
        return None

    casa_ganha = hs > aw
    fora_ganha = aw > hs
    empate = hs == aw
    s = normalizar_nome(selecao)

    if s == "1x":
        return "ganha" if casa_ganha or empate else "perdida"

    if s == "x2":
        return "ganha" if fora_ganha or empate else "perdida"

    if s == "12":
        return "ganha" if casa_ganha or fora_ganha else "perdida"

    return None


def validar_ht_resultado(aposta, resultado):
    mercado = aposta.get("mercado", "")
    selecao = aposta.get("selecao", "")
    home = resultado.get("home_team", "")
    away = resultado.get("away_team", "")

    ht_home = resultado.get("home_score_ht", resultado.get("home_ht_score"))
    ht_away = resultado.get("away_score_ht", resultado.get("away_ht_score"))

    if ht_home is None or ht_away is None:
        return None

    try:
        ht_home = int(ht_home)
        ht_away = int(ht_away)
    except:
        return None

    if mercado == "HT Resultado":
        if normalizar_nome(selecao) in ["sim", "yes"]:
            return "ganha" if ht_home != ht_away else "perdida"

        if nome_bate(selecao, home):
            return "ganha" if ht_home > ht_away else "perdida"

        if nome_bate(selecao, away):
            return "ganha" if ht_away > ht_home else "perdida"

    if mercado == "HT Vence sem sofrer":
        if nome_bate(selecao, home):
            return "ganha" if ht_home > ht_away and ht_away == 0 else "perdida"

        if nome_bate(selecao, away):
            return "ganha" if ht_away > ht_home and ht_home == 0 else "perdida"

    return None


def validar_aposta_com_resultado(aposta, resultado):
    mercado = aposta.get("mercado", "")
    texto = " ".join([
        str(aposta.get("aposta", "")),
        str(aposta.get("mercado", "")),
        str(aposta.get("selecao", "")),
    ])
    t = normalizar_nome(texto)

    # Sem estatísticas no endpoint básico: não marca errado.
    if mercado in ["Escanteios", "Cartões", "Chutes", "Chutes no Gol", "Marcador", "Assistência"]:
        return None

    if mercado in ["HT Resultado", "HT Vence sem sofrer"]:
        return validar_ht_resultado(aposta, resultado)

    if mercado == "Ambas Marcam" or eh_texto_btts(texto):
        return validar_btts_resultado(aposta, resultado)

    if mercado == "Dupla Chance":
        return validar_dupla_chance_resultado(aposta, resultado)

    if mercado in ["Total", "Total de Gols", "Pontos"] or (
        aposta.get("direcao") in ["over", "under"] and texto_tem(t, ["gols", "gol", "goals"])
    ):
        return validar_total_gols_resultado(aposta, resultado)

    if mercado == "Moneyline" or texto_tem(t, ["moneyline", "resultado final", "vence", "vencem", "ml"]):
        return validar_moneyline_resultado(aposta, resultado)

    return None




# ============================================================
# V32 - API: MERCADOS ESTATÍSTICOS + MÚLTIPLAS
# Valida quando a API retorna estatísticas:
# - Escanteios
# - Cartões
# - Chutes
# - Chutes no Gol
# Continua validando:
# - Moneyline
# - Total de Gols
# - BTTS
# - Dupla Chance
# - HT Resultado / HT vence sem sofrer
# ============================================================

def api_get_fixture_statistics_v32(fixture_id):
    if not fixture_id or not API_KEY:
        return None

    cache_key = f"stats_{fixture_id}"

    if cache_key in CACHE_ESTATISTICAS:
        return CACHE_ESTATISTICAS[cache_key]

    url = "https://v3.football.api-sports.io/fixtures/statistics"
    js = api_get(url, {"fixture": fixture_id})

    if not js:
        return None

    stats = js.get("response", [])

    CACHE_ESTATISTICAS[cache_key] = stats
    return stats


def normalizar_stat_value_v32(valor):
    if valor is None:
        return 0

    if isinstance(valor, (int, float)):
        return float(valor)

    s = str(valor).strip()

    if s.endswith("%"):
        s = s[:-1]

    s = s.replace(",", ".")

    m = re.search(r"-?\d+(?:\.\d+)?", s)

    if not m:
        return 0

    try:
        return float(m.group(0))
    except:
        return 0


def pegar_stat_total_v32(resultado, nomes):
    stats = resultado.get("statistics")

    if stats is None:
        stats = api_get_fixture_statistics_v32(resultado.get("fixture_id"))
        resultado["statistics"] = stats

    if not stats:
        return None

    total = 0
    achou = False

    nomes_norm = [normalizar_nome(n) for n in nomes]

    for team_block in stats:
        for st in team_block.get("statistics", []) or []:
            tipo = normalizar_nome(st.get("type", ""))

            if any(n in tipo or tipo in n for n in nomes_norm):
                total += normalizar_stat_value_v32(st.get("value"))
                achou = True

    return total if achou else None


def validar_over_under_valor_v32(valor, linha, direcao):
    if valor is None or linha in [None, "", "-"] or not direcao:
        return None

    try:
        valor = float(valor)
        linha = float(linha)
    except:
        return None

    if direcao == "over":
        if valor > linha:
            return "ganha"
        if valor < linha:
            return "perdida"
        return "anulada"

    if direcao == "under":
        if valor < linha:
            return "ganha"
        if valor > linha:
            return "perdida"
        return "anulada"

    return None


def validar_escanteios_resultado_v32(aposta, resultado):
    direcao = aposta.get("direcao", "") or aposta.get("selecao", "")
    linha = aposta.get("linha", None)

    if linha in [None, "", "-"]:
        linha = extrair_linha(aposta.get("aposta", ""))

    total = pegar_stat_total_v32(resultado, [
        "Corner Kicks", "Corners", "Escanteios", "Total Corners"
    ])

    return validar_over_under_valor_v32(total, linha, direcao)


def validar_cartoes_resultado_v32(aposta, resultado):
    direcao = aposta.get("direcao", "") or aposta.get("selecao", "")
    linha = aposta.get("linha", None)

    if linha in [None, "", "-"]:
        linha = extrair_linha(aposta.get("aposta", ""))

    amarelos = pegar_stat_total_v32(resultado, ["Yellow Cards"])
    vermelhos = pegar_stat_total_v32(resultado, ["Red Cards"])

    if amarelos is None and vermelhos is None:
        total = pegar_stat_total_v32(resultado, ["Cards", "Cartões", "Cartoes"])
    else:
        total = (amarelos or 0) + (vermelhos or 0)

    return validar_over_under_valor_v32(total, linha, direcao)


def validar_chutes_resultado_v32(aposta, resultado):
    direcao = aposta.get("direcao", "") or aposta.get("selecao", "")
    linha = aposta.get("linha", None)

    if linha in [None, "", "-"]:
        linha = extrair_linha(aposta.get("aposta", ""))

    total = pegar_stat_total_v32(resultado, [
        "Total Shots", "Shots", "Chutes", "Finalizações", "Finalizacoes"
    ])

    return validar_over_under_valor_v32(total, linha, direcao)


def validar_chutes_gol_resultado_v32(aposta, resultado):
    direcao = aposta.get("direcao", "") or aposta.get("selecao", "")
    linha = aposta.get("linha", None)

    if linha in [None, "", "-"]:
        linha = extrair_linha(aposta.get("aposta", ""))

    total = pegar_stat_total_v32(resultado, [
        "Shots on Goal", "Shots on Target", "Chutes no Gol", "Chutes a Gol"
    ])

    return validar_over_under_valor_v32(total, linha, direcao)


def validar_aposta_com_resultado(aposta, resultado):
    mercado = aposta.get("mercado", "")
    texto = " ".join([
        str(aposta.get("aposta", "")),
        str(aposta.get("mercado", "")),
        str(aposta.get("selecao", "")),
    ])
    t = normalizar_nome(texto)

    if mercado == "Escanteios":
        return validar_escanteios_resultado_v32(aposta, resultado)

    if mercado == "Cartões":
        return validar_cartoes_resultado_v32(aposta, resultado)

    if mercado == "Chutes":
        return validar_chutes_resultado_v32(aposta, resultado)

    if mercado == "Chutes no Gol":
        return validar_chutes_gol_resultado_v32(aposta, resultado)

    # Jogador/marcador/assistência precisam de endpoint de eventos/estatísticas de jogador.
    # Para não marcar errado, ficam pendentes quando não houver função específica.
    if mercado in ["Marcador", "Assistência", "Jogador Chutes", "Jogador Chutes no Gol"]:
        return None

    if mercado in ["HT Resultado", "HT Vence sem sofrer"]:
        return validar_ht_resultado(aposta, resultado)

    if mercado == "Ambas Marcam" or eh_texto_btts(texto):
        return validar_btts_resultado(aposta, resultado)

    if mercado == "Dupla Chance":
        return validar_dupla_chance_resultado(aposta, resultado)

    if mercado in ["Total", "Total de Gols", "Pontos"] or (
        aposta.get("direcao") in ["over", "under"] and texto_tem(t, ["gols", "gol", "goals"])
    ):
        return validar_total_gols_resultado(aposta, resultado)

    if mercado == "Moneyline" or texto_tem(t, ["moneyline", "resultado final", "vence", "vencem", "ml"]):
        return validar_moneyline_resultado(aposta, resultado)

    return None


def validar_item_multipla_universal(item_aposta):
    if normalizar_nome(item_aposta.get("esporte", "Futebol")) != "futebol":
        return None, "ignorado: não é futebol"

    resultado = buscar_resultado_futebol(item_aposta)

    if not resultado:
        return None, "resultado não encontrado"

    if resultado.get("status") not in ["FT", "AET", "PEN"]:
        return None, "jogo ainda não finalizado"

    status = validar_aposta_com_resultado(item_aposta, resultado)

    if status:
        return status, "validado"

    return None, "mercado não validado ou estatística indisponível"


def atualizar_resultados_api():
    atualizadas = 0
    ignoradas = 0

    for b in bets_do_usuario():
        if b.get("estado") != "":
            continue

        aposta_validacao = preparar_aposta_para_validacao(b)
        mercado = str(aposta_validacao.get("mercado", ""))

        if mercado.startswith("Múltipla") or "/" in mercado or aposta_validacao.get("mercado_api", "").startswith("Múltipla"):
            status_multi, detalhe_multi = validar_multipla_universal_api(aposta_validacao)

            if status_multi:
                atualizar_resultado_saldo(b, status_multi)
                b["api_status"] = "múltipla atualizada pela API: " + detalhe_multi
                atualizadas += 1
                continue

            b["api_status"] = "múltipla não validada automaticamente: " + str(detalhe_multi)
            ignoradas += 1
            continue

        if normalizar_nome(aposta_validacao.get("esporte", "")) != "futebol":
            b["api_status"] = "ignorado: não é futebol"
            ignoradas += 1
            continue

        resultado = buscar_resultado_futebol(aposta_validacao)

        if not resultado:
            b["api_status"] = "resultado não encontrado"
            ignoradas += 1
            continue

        if resultado.get("status") not in ["FT", "AET", "PEN"]:
            b["api_status"] = "jogo ainda não finalizado"
            ignoradas += 1
            continue

        status = validar_aposta_com_resultado(aposta_validacao, resultado)

        if status:
            atualizar_resultado_saldo(b, status)
            b["api_status"] = "atualizado pela API"
            atualizadas += 1
        else:
            b["api_status"] = "mercado não validado"
            ignoradas += 1

    salvar()
    return atualizadas, ignoradas





# ============================================================
# V37 - Cadastro manual/AJAX sem reset + múltiplas no manual
# ============================================================

def criar_aposta_manual_payload(form):
    jogo = limpar_linha(form.get("jogo", ""))
    aposta_texto = limpar_linha(form.get("aposta", ""))

    classificacao = classificar_aposta(aposta_texto, jogo)

    bet = {
        "id": str(uuid.uuid4()),
        "user_id": usuario_id_atual(),
        "data": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "aposta": aposta_texto,
        "casa": limpar_casa(form.get("casa", "")),
        "esporte": limpar_linha(form.get("esporte", "")),
        "jogo": jogo,
        "odd": float(form.get("odd", 0) or 0),
        "valor": float(form.get("valor", 0) or 0),
        "estado": "",
        "lucro": 0,
        "origem": "manual",
        "mercado": classificacao.get("mercado", "Outro"),
        "direcao": classificacao.get("direcao", ""),
        "linha": classificacao.get("linha", None),
        "periodo": classificacao.get("periodo", "jogo inteiro"),
        "selecao": classificacao.get("selecao", ""),
        "btts_resposta": classificacao.get("btts_resposta", ""),
        "api_status": "",
        "texto_bruto": "",
        "texto_interpretado": f"{jogo} {aposta_texto}".strip(),
        "itens_multipla": {},
        "itens_multipla_detalhados": [],
        "saldo_debitado": False,
        "saldo_creditado_estado": "",
        "saldo_creditado_valor": 0.0,
        "publica": aposta_publica_padrao_usuario()
    }

    # Usa o mesmo motor visual/universal das múltiplas OCR também no manual/cópia.
    if "aplicar_formatacao_multiplas_combinadas" in globals():
        try:
            bet = aplicar_formatacao_multiplas_combinadas(bet)
        except Exception as e:
            print("ERRO formatando múltipla manual:", e)

    return bet





# ============================================================
# V40 - FIX: bets_display_v39 definido antes das rotas
# ============================================================



def carregar_usuarios():
    usuarios_padrao = {
        "users": [
            {
                "id": str(uuid.uuid4()),
                "nome": "Admin",
                "email": "admin@betmanager.com",
                "senha_hash": generate_password_hash("Admin@123"),
                "is_admin": True,
                "ativo": True,
                "assinatura_ativa": True,
                "plano": "admin",
                "apostas_publicas_padrao": False,
                "criado_em": datetime.now().strftime("%d/%m/%Y %H:%M")
            }
        ]
    }

    if banco_ativo():
        migrar_json_para_banco_se_vazio()
        data = db_get_json("usuarios", usuarios_padrao) or usuarios_padrao
    else:
        if not os.path.exists(USUARIOS_PATH):
            with open(USUARIOS_PATH, "w", encoding="utf-8") as f:
                json.dump(usuarios_padrao, f, indent=4, ensure_ascii=False)
            data = usuarios_padrao
        else:
            try:
                with open(USUARIOS_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except:
                data = usuarios_padrao

    data.setdefault("users", [])

    for u in data.get("users", []):
        u.setdefault("ativo", True)
        u.setdefault("assinatura_ativa", bool(u.get("is_admin", False)))
        u.setdefault("plano", "admin" if u.get("is_admin") else "free")
        u.setdefault("apostas_publicas_padrao", False)

    return data

def salvar_usuarios(data):
    if banco_ativo():
        db_set_json("usuarios", data)
        return

    with open(USUARIOS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)



# ============================================================
# V69 - ADMIN AUTOMÁTICO SEGURO
# ============================================================

def garantir_admin():
    try:
        usuarios = carregar_usuarios()
        usuarios.setdefault("users", [])

        admin_email = os.environ.get("ADMIN_EMAIL", "admin@betmanager.com").strip().lower()
        admin_password = os.environ.get("ADMIN_PASSWORD", "Admin@123")

        existe_admin_email = False
        existe_qualquer_admin = False

        for u in usuarios.get("users", []):
            if u.get("is_admin"):
                existe_qualquer_admin = True

            if u.get("email", "").strip().lower() == admin_email:
                existe_admin_email = True
                u["is_admin"] = True
                u["ativo"] = True
                u["assinatura_ativa"] = True
                u["plano"] = "admin"
                u.setdefault("nome", "Admin")
                u.setdefault("apostas_publicas_padrao", False)

        if not existe_admin_email and not existe_qualquer_admin:
            usuarios["users"].append({
                "id": str(uuid.uuid4()),
                "nome": "Admin",
                "email": admin_email,
                "senha_hash": generate_password_hash(admin_password),
                "is_admin": True,
                "ativo": True,
                "assinatura_ativa": True,
                "plano": "admin",
                "apostas_publicas_padrao": False,
                "criado_em": datetime.now().strftime("%d/%m/%Y %H:%M")
            })

        salvar_usuarios(usuarios)
        print("ADMIN GARANTIDO:", admin_email)

    except Exception as e:
        print("ERRO AO GARANTIR ADMIN:", repr(e))

def buscar_usuario_email(email):
    email = (email or "").strip().lower()
    usuarios = carregar_usuarios()

    for u in usuarios.get("users", []):
        if u.get("email", "").strip().lower() == email:
            return u

    return None


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not usuario_logado():
            return redirect("/login")
        return fn(*args, **kwargs)
    return wrapper


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        u = usuario_logado()
        if not u:
            return redirect("/login")
        if not u.get("is_admin"):
            return redirect("/")
        return fn(*args, **kwargs)
    return wrapper


# ============================================================
# V46 - Assinatura e carteira
# ============================================================


def assinatura_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        u = usuario_logado()
        if not u:
            return redirect("/login")
        if u.get("is_admin") or u.get("assinatura_ativa"):
            return fn(*args, **kwargs)
        return redirect("/bloqueado")
    return wrapper






@app.after_request
def aplicar_headers_seguranca(response):
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response



# Garante admin no boot da aplicação
try:
    garantir_admin()
except Exception as e:
    print('BOOT ADMIN ERROR:', repr(e))


@app.route("/bloqueado")
@login_required
def bloqueado():
    return render_template("bloqueado.html")



# ============================================================
# V70 - ADMIN EMERGENCIAL PELO LOGIN
# ============================================================

def criar_ou_atualizar_admin_emergencial(email=None, senha=None):
    admin_email = (email or os.environ.get("ADMIN_EMAIL", "admin@betmanager.com")).strip().lower()
    admin_password = senha or os.environ.get("ADMIN_PASSWORD", "Admin@123")

    usuarios = carregar_usuarios()
    usuarios.setdefault("users", [])

    admin = None

    for u in usuarios.get("users", []):
        if u.get("email", "").strip().lower() == admin_email:
            admin = u
            break

    if not admin:
        admin = {
            "id": str(uuid.uuid4()),
            "nome": "Admin",
            "email": admin_email,
            "senha_hash": generate_password_hash(admin_password),
            "is_admin": True,
            "ativo": True,
            "assinatura_ativa": True,
            "plano": "admin",
            "apostas_publicas_padrao": False,
            "criado_em": datetime.now().strftime("%d/%m/%Y %H:%M")
        }
        usuarios["users"].append(admin)
    else:
        admin["nome"] = admin.get("nome") or "Admin"
        admin["email"] = admin_email
        admin["senha_hash"] = generate_password_hash(admin_password)
        admin["is_admin"] = True
        admin["ativo"] = True
        admin["assinatura_ativa"] = True
        admin["plano"] = "admin"
        admin.setdefault("apostas_publicas_padrao", False)

    salvar_usuarios(usuarios)
    print("ADMIN EMERGENCIAL GARANTIDO:", admin_email)

    return admin

@app.route("/login", methods=["GET", "POST"])
def login():
    erro = ""

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        senha = request.form.get("senha", "")

        print("LOGIN TENTATIVA:", email)

        try:
            admin_email = os.environ.get("ADMIN_EMAIL", "admin@betmanager.com").strip().lower()
            admin_password = os.environ.get("ADMIN_PASSWORD", "Admin@123")

            # Login emergencial: se for o admin padrão/env, cria/atualiza no banco e entra.
            if email == admin_email and senha == admin_password:
                u = criar_ou_atualizar_admin_emergencial(admin_email, admin_password)
                session.clear()
                session["user_id"] = u["id"]
                session.permanent = True
                print("LOGIN ADMIN EMERGENCIAL OK:", email)
                return redirect("/")

            u = buscar_usuario_email(email)

            if not u:
                erro = "E-mail ou senha inválidos."
                print("LOGIN FALHOU: usuário não encontrado")
            elif not u.get("ativo", True):
                erro = "Conta bloqueada. Fale com o administrador."
                print("LOGIN FALHOU: usuário bloqueado")
            elif not check_password_hash(u.get("senha_hash", ""), senha):
                erro = "E-mail ou senha inválidos."
                print("LOGIN FALHOU: senha incorreta")
            else:
                session.clear()
                session["user_id"] = u["id"]
                session.permanent = True
                print("LOGIN OK:", email)
                return redirect("/")

        except Exception as e:
            print("ERRO LOGIN:", repr(e))
            erro = "Erro ao entrar. Veja os logs do servidor."

    return render_template("login.html", erro=erro)


@app.route("/criar-conta", methods=["GET", "POST"])
def criar_conta():
    erro = ""

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        email = request.form.get("email", "").strip().lower()
        senha = request.form.get("senha", "")

        if not nome or not email or not senha:
            erro = "Preencha todos os campos."
        elif buscar_usuario_email(email):
            erro = "Já existe uma conta com esse e-mail."
        elif len(senha) < 6:
            erro = "A senha precisa ter pelo menos 6 caracteres."
        else:
            usuarios = carregar_usuarios()
            usuarios["users"].append({
                "id": str(uuid.uuid4()),
                "nome": nome,
                "email": email,
                "senha_hash": generate_password_hash(senha),
                "is_admin": False,
                "ativo": True,
                "assinatura_ativa": False,
                "plano": "free",
                "apostas_publicas_padrao": False,
                "criado_em": datetime.now().strftime("%d/%m/%Y %H:%M")
            })
            salvar_usuarios(usuarios)

            u = buscar_usuario_email(email)
            session["user_id"] = u["id"]
            return redirect("/")

    return render_template("criar_conta.html", erro=erro)


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.route("/admin")
@admin_required
def admin():
    usuarios = carregar_usuarios().get("users", [])
    return render_template("admin.html", usuarios=usuarios)


@app.route("/admin/toggle/<uid>")
@admin_required
def admin_toggle(uid):
    usuarios = carregar_usuarios()

    for u in usuarios.get("users", []):
        if u.get("id") == uid:
            u["ativo"] = not u.get("ativo", True)
            break

    salvar_usuarios(usuarios)
    return redirect("/admin")


@app.route("/admin/promover/<uid>")
@admin_required
def admin_promover(uid):
    usuarios = carregar_usuarios()

    for u in usuarios.get("users", []):
        if u.get("id") == uid:
            u["is_admin"] = not u.get("is_admin", False)
            break

    salvar_usuarios(usuarios)
    return redirect("/admin")


@app.route("/adicionar_ajax", methods=["POST"])
@login_required
@assinatura_required
def adicionar_ajax():
    try:
        bet = criar_aposta_manual_payload(request.form)
        registrar_nova_aposta_saldo(bet)
        dados["bets"].append(bet)
        salvar()
        recalcular()

        return jsonify({"ok": True, "bet": limpar_aposta_display_v39(bet), "metricas": metricas()})

    except Exception as e:
        print("ERRO /adicionar_ajax:", e)
        return jsonify({"ok": False, "erro": str(e)}), 400


@app.route("/", methods=["GET", "POST"])
@login_required
def index():
    if request.method == "POST":
        bet = criar_aposta_manual_payload(request.form)
        registrar_nova_aposta_saldo(bet)
        dados["bets"].append(bet)
        salvar()
        return redirect("/")

    recalcular()
    salvar()

    labels, valores = grafico()

    return render_template(
        "index.html",
        bets=bets_display_v39(),
        m=metricas(),
        labels=labels,
        valores=valores,
        casas=CASAS_DISPONIVEIS,
        esportes=ESPORTES_DISPONIVEIS
    )


@app.route("/estatisticas")
@login_required
@assinatura_required
def estatisticas():
    recalcular()
    salvar()

    mes = int(request.args.get("mes", datetime.now().month))
    ano = int(request.args.get("ano", datetime.now().year))

    return render_template(
        "estatisticas.html",
        m=metricas(),
        calendario=calendario_historico(ano, mes),
        extras=estatisticas_extras()
    )


@app.route("/atualizar_api")
@login_required
@assinatura_required
@admin_required
def atualizar_api():
    atualizadas, ignoradas = atualizar_resultados_api()
    return redirect(f"/?api=ok&atualizadas={atualizadas}&ignoradas={ignoradas}")


@app.route("/banca", methods=["POST"])
@login_required
def banca():
    dados["banca_inicial"] = float(request.form["banca"])
    salvar()
    return redirect("/")


@app.route("/resultado/<bet_id>/<estado>")
@login_required
@assinatura_required
def resultado(bet_id, estado):
    b = buscar_aposta_segura_v61(bet_id)

    if b:
        atualizar_resultado_saldo(b, estado)
        salvar()

        if request.args.get("ajax") == "1":
            return jsonify({
                "ok": True,
                "bet": limpar_aposta_display_v39(b) if "limpar_aposta_display_v39" in globals() else b,
                "metricas": metricas()
            })

    if request.args.get("ajax") == "1":
        return jsonify({"ok": False}), 404

    return redirect("/")


@app.route("/remover/<bet_id>")
@login_required
@assinatura_required
def remover(bet_id):
    b = buscar_aposta_segura_v61(bet_id)
    if b:
        dados["bets"] = [x for x in dados.get("bets", []) if x.get("id") != bet_id]
        salvar()
    return redirect("/")


@app.route("/editar_ajax", methods=["POST"])
def editar_ajax():
    payload = request.json
    b = buscar_aposta(payload.get("id"))

    if not b:
        return jsonify({"status": "erro"}), 404

    snapshot_saldo = preparar_edicao_saldo_snapshot(b)

    b["aposta"] = limpar_linha(payload.get("aposta", ""))
    b["casa"] = limpar_casa(payload.get("casa", ""))
    b["esporte"] = limpar_linha(payload.get("esporte", ""))
    b["jogo"] = limpar_linha(payload.get("jogo", ""))
    b["odd"] = float(payload.get("odd", 1))
    b["valor"] = float(payload.get("valor", 0))
    b["estado"] = payload.get("estado", b.get("estado", ""))

    classificacao = classificar_aposta(b["aposta"], b["jogo"])
    b["mercado"] = payload.get("mercado") or classificacao["mercado"]
    b["direcao"] = classificacao["direcao"]
    b["linha"] = payload.get("linha") or classificacao["linha"]
    b["periodo"] = payload.get("periodo") or classificacao["periodo"]
    b["selecao"] = payload.get("selecao") or classificacao["selecao"]
    b["btts_resposta"] = payload.get("btts_resposta") or classificacao["btts_resposta"]
    b["lucro"] = calcular_lucro(b)

    reverter_saldo_snapshot(snapshot_saldo)
    reaplicar_saldo_apos_edicao(b)

    salvar()
    return jsonify({"status": "ok"})


@app.route("/colar", methods=["POST"])
@login_required
@assinatura_required
def colar():
    try:
        payload = request.get_json(silent=True) or {}
        imagens = payload.get("images", [])
        resultados = []

        os.makedirs(os.path.join(BASE_DIR, "uploads"), exist_ok=True)

        for img in imagens:
            try:
                caminho = os.path.join(BASE_DIR, "uploads", f"{uuid.uuid4()}.png")

                if "," in img:
                    img_base64 = img.split(",", 1)[1]
                else:
                    img_base64 = img

                with open(caminho, "wb") as f:
                    f.write(base64.b64decode(img_base64))

                texto = ler_imagem(caminho)
                print("===== OCR DEBUG /colar =====")
                print(texto)
                print("===== FIM OCR DEBUG /colar =====")

                aposta_extraida = extrair(texto)

                if not isinstance(aposta_extraida, dict):
                    aposta_extraida = {"aposta": str(aposta_extraida or "")}

                aposta_extraida.setdefault("aposta", "")
                aposta_extraida.setdefault("casa", "")
                aposta_extraida.setdefault("esporte", "")
                aposta_extraida.setdefault("jogo", "")
                aposta_extraida.setdefault("mercado", "")
                aposta_extraida.setdefault("selecao", "")
                aposta_extraida.setdefault("linha", "")
                aposta_extraida.setdefault("periodo", "")
                aposta_extraida.setdefault("odd", "")
                aposta_extraida.setdefault("valor", "")
                aposta_extraida.setdefault("texto_bruto", texto)
                aposta_extraida.setdefault("texto_interpretado", aposta_extraida.get("aposta", ""))

                resultados.append(aposta_extraida)

            except Exception as e:
                print("ERRO EM UMA IMAGEM /colar:", repr(e))
                resultados.append({
                    "aposta": "",
                    "casa": "",
                    "esporte": "",
                    "jogo": "",
                    "mercado": "",
                    "selecao": "",
                    "linha": "",
                    "periodo": "",
                    "odd": "",
                    "valor": "",
                    "texto_bruto": "",
                    "texto_interpretado": "",
                    "erro": str(e)
                })

        return jsonify({"ok": True, "resultados": resultados})

    except Exception as e:
        print("ERRO GERAL /colar:", repr(e))
        return jsonify({"ok": False, "erro": str(e), "resultados": []}), 200


@app.route("/salvar_preview", methods=["POST"])
@login_required
@assinatura_required
def salvar_preview():
    apostas = request.json.get("apostas", [])

    for a in apostas:
        aposta_texto = limpar_linha(a["aposta"])
        jogo = limpar_linha(a.get("jogo", ""))

        texto_bruto_preview = a.get("texto_bruto", "")
        texto_interpretado_preview = a.get("texto_interpretado", "")
        texto_para_classificar = texto_interpretado_preview or texto_bruto_preview or aposta_texto
        texto_para_classificar = f"{jogo} {aposta_texto} {texto_para_classificar}"

        classificacao = classificar_aposta(texto_para_classificar, jogo)

        bet_preview = {
            "id": str(uuid.uuid4()),
            "user_id": usuario_id_atual(),
            "data": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "aposta": aposta_texto,
            "casa": limpar_casa(a.get("casa", "")),
            "esporte": limpar_linha(a.get("esporte", "")),
            "jogo": jogo,
            "odd": float(a["odd"]),
            "valor": float(a["valor"]),
            "estado": "",
            "lucro": 0,
            "origem": "print",
            "mercado": a.get("mercado") or classificacao["mercado"],
            "direcao": a.get("direcao") or classificacao["direcao"],
            "linha": a.get("linha") or classificacao["linha"],
            "periodo": a.get("periodo") or classificacao["periodo"],
            "selecao": a.get("selecao") or classificacao["selecao"],
            "btts_resposta": a.get("btts_resposta") or classificacao["btts_resposta"],
            "api_status": "",
            "texto_bruto": a.get("texto_bruto", ""),
            "texto_interpretado": a.get("texto_interpretado", ""),
            "itens_multipla": a.get("itens_multipla", {}),
            "itens_multipla_detalhados": a.get("itens_multipla_detalhados", []),
            "saldo_debitado": False,
            "saldo_creditado_estado": "",
            "saldo_creditado_valor": 0.0,
            "publica": aposta_publica_padrao_usuario()
        }

        registrar_nova_aposta_saldo(bet_preview)
        dados["bets"].append(bet_preview)

    salvar()
    return jsonify({"status": "ok"})



# ============================================================
# V20 - OCR/PARSER ROBUSTO SEM IA
# ============================================================

def preparar_imagem(caminho):
    img = Image.open(caminho)

    if img.mode in ("RGBA", "LA"):
        fundo = Image.new("RGB", img.size, "white")
        fundo.paste(img, mask=img.split()[-1])
        img = fundo

    largura, altura = img.size
    escala = 3 if max(largura, altura) < 1400 else 2
    img = img.resize((largura * escala, altura * escala))
    img = img.convert("L")
    img = img.point(lambda p: 255 if p > 165 else 0)

    return img


def ler_imagem(caminho):
    img = preparar_imagem(caminho)

    configs = [
        "--oem 3 --psm 6",
        "--oem 3 --psm 4",
        "--oem 3 --psm 11"
    ]

    melhor_texto = ""

    for cfg in configs:
        try:
            texto = pytesseract.image_to_string(img, lang="por+eng", config=cfg)
        except Exception as e:
            print("ERRO TESSERACT:", e)
            texto = ""

        if len(texto.strip()) > len(melhor_texto.strip()):
            melhor_texto = texto

    print("===== OCR BRUTO V20 =====")
    print(melhor_texto)
    print("===== FIM OCR BRUTO V20 =====")

    return melhor_texto


def limpar_valor(texto):
    texto = str(texto).lower()
    texto = texto.replace("r$", "").replace("rs$", "").replace("rs", "").replace("r5", "").replace("r ", "").replace("$", "")
    texto = remover_emojis(texto).replace(" ", "")
    texto = re.sub(r"[^\d,\.]", "", texto)

    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")

    match = re.search(r"\d+\.\d+", texto)
    if match:
        return float(match.group(0))

    match = re.search(r"\d+", texto)
    if match:
        return float(match.group(0))

    return 0.0


def v20_norm(texto):
    return normalizar_nome(texto)


def v20_e_casa(linha):
    ln = v20_norm(linha)
    if not ln:
        return False

    for casa in CASAS_DISPONIVEIS:
        cn = v20_norm(casa)
        if not cn:
            continue

        if ln == cn:
            return True

        if len(cn) >= 4 and re.search(rf"\b{re.escape(cn)}\b", ln):
            return True

    return False


def v20_nome_casa(linha):
    ln = v20_norm(linha)

    for casa in CASAS_DISPONIVEIS:
        cn = v20_norm(casa)
        if not cn:
            continue

        if ln == cn:
            return casa

        if len(cn) >= 4 and re.search(rf"\b{re.escape(cn)}\b", ln):
            return casa

    return limpar_casa(linha)


def v20_esporte(linha):
    n = v20_norm(linha)

    mapa = [
        ("Futebol Americano", ["futebol americano", "nfl"]),
        ("Futebol", ["futebol", "soccer"]),
        ("Basquete", ["basquete", "basketball", "nba"]),
        ("Tênis de Mesa", ["tenis de mesa", "tênis de mesa", "table tennis"]),
        ("Tênis", ["tenis", "tênis", "tennis"]),
        ("Vôlei", ["volei", "vôlei", "volleyball"]),
        ("MMA", ["mma", "ufc"]),
        ("eSports", ["esports", "e sports", "league of legends", "valorant", "cs2"]),
        ("Golfe", ["golfe", "golf"]),
    ]

    for esporte, termos in mapa:
        for termo in termos:
            if n == v20_norm(termo) or termo in n:
                return esporte

    return ""


def v20_e_odd(linha):
    l = str(linha).strip().replace(",", ".")

    if re.search(r"r\$", l, flags=re.I):
        return False

    match = re.search(r"\b(\d{1,3}\.\d{2})\b", l)
    if match:
        val = float(match.group(1))
        return 1.01 <= val <= 100

    return False


def v20_e_lixo_total(linha):
    l = str(linha or "").strip()
    n = v20_norm(l)

    if not l or not n:
        return True

    lixo = [
        "golden boost", "boost", "ganhos aumentados", "ganho aumentado",
        "limite da aposta", "limite", "possivel retorno", "possível retorno",
        "retorno possivel", "retorno possível", "criar aposta", "adicionar aposta",
        "remover selecao", "remover seleção", "remover", "bilhete", "cupom",
        "cashout", "cash out", "turbinada", "casadinha", "stake", "saldo",
        "deposito", "depósito", "compartilhar", "copiar", "fechar",
    ]

    if any(x in n for x in lixo):
        return True

    if re.fullmatch(r"\+?\d+[,.]?\d*\s*%", l):
        return True

    if re.fullmatch(r"\d{1,3}", l):
        return True

    return False


def v20_limpar_linha_sem_destruir(linha):
    l = limpar_linha(linha)

    for termo in [
        "Golden Boost", "Ganhos aumentados", "Ganho aumentado",
        "Limite da aposta", "Possível retorno", "Possivel retorno",
        "Retorno possível", "Retorno possivel", "Criar aposta",
        "Remover seleção", "Remover selecao", "Bilhete", "Cupom",
        "Cash out", "Cashout"
    ]:
        l = re.sub(rf"\b{re.escape(termo)}\b", " ", l, flags=re.I)

    l = re.sub(r"\+?\d+[,.]?\d*\s*%", " ", l)
    l = re.sub(r"\s+", " ", l).strip()

    return l


def v20_valores_linha(linha):
    original = str(linha or "").strip()
    n = v20_norm(original)

    if not original:
        return []

    if "limite" in n:
        return []

    if any(x in n for x in [
        "possivel retorno", "possível retorno", "retorno", "odd", "odds",
        "boost", "ganhos aumentados", "cupom", "bilhete", "cashout", "cash out"
    ]):
        return []

    valores = []

    for m in re.finditer(r"(?:R\$|RS\$|R5\$?|R\s*\$?|RS|BRL)\s*([0-9]+(?:[.,][0-9]{1,2})?)", original, flags=re.I):
        v = limpar_valor(m.group(0))
        if v > 0:
            valores.append(v)

    for m in re.finditer(r"\b([0-9]{1,5}[.,][0-9]{2})\b", original):
        v = limpar_valor(m.group(1))
        if v >= 3:
            valores.append(v)

    if re.fullmatch(r"\d{1,5}", original):
        v = limpar_valor(original)
        if v > 0:
            valores.append(v)

    saida = []
    for v in valores:
        if v not in saida:
            saida.append(v)

    return saida


def v20_detectar_valor(texto, bloco, linhas_originais):
    if len(bloco) > 7:
        vals = v20_valores_linha(bloco[7])
        if vals:
            return vals[-1]

    for idx in [8, 6, 9, 5, 10, 7, 11, 12]:
        if len(bloco) > idx:
            vals = v20_valores_linha(bloco[idx])
            if vals:
                return vals[-1]

    for linha in reversed(bloco):
        vals = v20_valores_linha(linha)
        if vals:
            return vals[-1]

    for linha in reversed(linhas_originais):
        vals = v20_valores_linha(linha)
        if vals:
            return vals[-1]

    return 0.0


def v20_limpar_item(item):
    item = limpar_linha(item)

    item = re.sub(r"\b(futebol|basquete|tenis|tênis|volei|vôlei|mma|esports)\b", " ", item, flags=re.I)
    item = re.sub(r"\b(resultado final|resultado|mercado final)\b", " ", item, flags=re.I)
    item = re.sub(r"R\$\s*\d+[,.]?\d*", " ", item, flags=re.I)
    item = re.sub(r"\b\d+[,.]\d{2}\b$", " ", item)
    item = re.sub(r"\s+", " ", item).strip(" /-|")

    return item


def v20_dividir(texto):
    partes = []

    for p in re.split(r"\s*/\s*", str(texto)):
        p = v20_limpar_item(p)
        if p:
            partes.append(p)

    return partes


def extrair_partes_multipla(jogo, aposta):
    jogos = v20_dividir(jogo)
    selecoes = v20_dividir(aposta)

    return {
        "jogos": jogos,
        "selecoes": selecoes,
        "qtd_jogos": len(jogos),
        "qtd_selecoes": len(selecoes)
    }


def detectar_tipo_multipla(jogo, aposta):
    partes = extrair_partes_multipla(jogo, aposta)
    return (partes["qtd_jogos"] > 1 or partes["qtd_selecoes"] > 1), partes


def v20_classificar_item(item, jogo=""):
    item = v20_limpar_item(item)
    t = v20_norm(item)

    out = {
        "texto": item,
        "mercado": "Outro",
        "selecao": "",
        "direcao": "",
        "linha": None
    }

    if not item:
        return out


    # Jogador chutes/chutes a gol
    if texto_tem(t, [
        "tem 1 ou mais chutes", "tem um ou mais chutes", "1 ou mais chutes",
        "um ou mais chutes", "chutes gol", "chute gol", "chutes a gol",
        "chute a gol", "chutes no gol", "chute no gol",
        "shots on target", "shot on target"
    ]):
        out["mercado"] = "Jogador Chutes no Gol" if ("gol" in t or "target" in t) else "Jogador Chutes"
        out["direcao"] = "over"
        out["selecao"] = limpar_nome_jogador(item)
        out["linha"] = extrair_linha(item) or 0.5
        return out

    # Frase de múltipla de vencedores
    if "vencerem seus jogos" in t or "vencem seus jogos" in t or "vencerem os seus jogos" in t or "vencem os seus jogos" in t:
        out["mercado"] = "Múltipla - Moneyline"
        out["selecao"] = re.sub(r"\b(vencerem seus jogos|vencem seus jogos|vencerem os seus jogos|vencem os seus jogos)\b", "", item, flags=re.I).strip()
        return out

    casa, fora = extrair_times_jogo(jogo)

    if " ou empate" in t or "empate ou " in t or "dupla chance" in t or "chance dupla" in t:
        out["mercado"] = "Dupla Chance"

        if casa and v20_norm(casa) in t:
            out["selecao"] = "1X"
        elif fora and v20_norm(fora) in t:
            out["selecao"] = "X2"
        else:
            out["selecao"] = detectar_dupla_chance_selecao(item) or ""

        return out

    if eh_texto_btts(item):
        out["mercado"] = "Ambas Marcam"
        out["selecao"] = detectar_btts_resposta(item) or "sim"
        return out

    direcao = detectar_direcao(item)
    linha = extrair_linha(item)

    if direcao:
        if texto_tem(t, ["escanteio", "escanteios", "corner", "corners", "cantos"]):
            out["mercado"] = "Escanteios"
        elif texto_tem(t, ["chutes a gol", "chutes no gol", "finalizacoes no gol", "shots on target"]):
            out["mercado"] = "Chutes no Gol"
        elif texto_tem(t, ["chutes", "finalizacoes", "shots", "remates"]):
            out["mercado"] = "Chutes"
        else:
            out["mercado"] = "Total"

        out["direcao"] = direcao
        out["selecao"] = direcao
        out["linha"] = linha
        return out

    mercado_jogador = detectar_jogador_mercado(item) if "detectar_jogador_mercado" in globals() else ""
    if mercado_jogador:
        out["mercado"] = mercado_jogador
        out["selecao"] = limpar_nome_jogador(item)
        return out

    if texto_tem(t, ["vence", "vencem", "resultado final", "moneyline", "para vencer", "ganha o jogo"]):
        out["mercado"] = "Moneyline"
        out["selecao"] = extrair_selecao(item, jogo)
        return out

    return out


def v20_resumo_multipla(itens, partes):
    textos = []

    for i in itens:
        if i.get("mercado") == "Dupla Chance" and i.get("selecao"):
            textos.append(f"{i.get('texto')} ({i.get('selecao')})")
        elif i.get("direcao") and i.get("linha") is not None:
            textos.append(f"{i.get('direcao')} {i.get('linha')}")
        else:
            textos.append(i.get("texto", ""))

    textos = [t for t in textos if t]

    if textos:
        return " / ".join(textos[:6]) + (" ..." if len(textos) > 6 else "")

    if partes.get("selecoes"):
        return " / ".join(partes["selecoes"][:6]) + (" ..." if len(partes["selecoes"]) > 6 else "")

    if partes.get("jogos"):
        return " / ".join(partes["jogos"][:6]) + (" ..." if len(partes["jogos"]) > 6 else "")

    return "múltipla"


def classificar_aposta_multiplas_ou_simples(jogo, tipo_aposta):
    eh_multipla, partes = detectar_tipo_multipla(jogo, tipo_aposta)

    t_aposta = normalizar_nome(tipo_aposta)
    if texto_tem(t_aposta, ["vencerem seus jogos", "vencem seus jogos", "vencerem os seus jogos", "vencem os seus jogos"]):
        eh_multipla = True
        if not partes.get("selecoes"):
            partes["selecoes"] = [tipo_aposta]
            partes["qtd_selecoes"] = 1

    if eh_multipla:
        base = partes.get("selecoes") or partes.get("jogos") or []
        itens = [v20_classificar_item(i, jogo) for i in base if i]

        mercados = [i["mercado"] for i in itens if i["mercado"] != "Outro"]

        if not mercados:
            mercado_base = "Múltipla"
        elif len(set(mercados)) == 1:
            mercado_base = f"Múltipla - {mercados[0]}"
        else:
            mercado_base = "Múltipla - Combinada"

        cls = classificar_aposta(f"{jogo} {tipo_aposta}", jogo)
        cls["mercado"] = mercado_base
        cls["itens_multipla"] = partes
        cls["itens_multipla_detalhados"] = itens
        cls["selecao"] = v20_resumo_multipla(itens, partes)

        if mercado_base == "Múltipla - Combinada":
            cls["direcao"] = ""
            cls["linha"] = None

        return cls

    return classificar_aposta(tipo_aposta, jogo)


def v20_montar_linhas(texto):
    linhas_originais = [l.strip() for l in texto.split("\n") if l.strip()]
    linhas = []

    for linha in linhas_originais:
        limpa = v20_limpar_linha_sem_destruir(linha)
        if not limpa:
            continue

        if v20_e_lixo_total(limpa):
            continue

        linhas.append(limpa)

    return linhas_originais, linhas


def v20_achar_inicio(linhas):
    idx = None

    for i, linha in enumerate(linhas):
        if v20_e_casa(linha):
            idx = i

    return idx if idx is not None else 0


def extrair_v20(texto):
    linhas_originais, linhas = v20_montar_linhas(texto)

    if not linhas:
        raise ValueError("OCR sem linhas úteis")

    idx = v20_achar_inicio(linhas)
    bloco = linhas[idx:]

    print("===== LINHAS LIMPAS V20 =====")
    for i, l in enumerate(bloco):
        print(i, "=>", l)
    print("===== FIM LINHAS LIMPAS V20 =====")

    casa = v20_nome_casa(bloco[0]) if len(bloco) > 0 else ""

    idx_esporte = None
    esporte = "Futebol"

    for i in range(1, len(bloco)):
        e = v20_esporte(bloco[i])
        if e:
            idx_esporte = i
            esporte = e
            break

    if idx_esporte is None:
        jogo = limpar_linha(bloco[1]) if len(bloco) > 1 else ""
        idx_aposta_ini = 3
        if len(bloco) > 2:
            e2 = v20_esporte(bloco[2])
            if e2:
                esporte = e2
    else:
        jogo = " / ".join([v20_limpar_item(x) for x in bloco[1:idx_esporte] if v20_limpar_item(x)])
        idx_aposta_ini = idx_esporte + 1

    idx_odd = None

    for i in range(idx_aposta_ini, len(bloco)):
        if v20_e_odd(bloco[i]):
            idx_odd = i
            break

    if idx_odd is None:
        tipo_aposta = v20_limpar_item(bloco[idx_aposta_ini]) if len(bloco) > idx_aposta_ini else ""
        odd = 1.0
    else:
        tipo_aposta = " / ".join([v20_limpar_item(x) for x in bloco[idx_aposta_ini:idx_odd] if v20_limpar_item(x)])
        odd = limpar_odd(bloco[idx_odd])

    jogo = re.sub(r"\s*/\s*/+\s*", " / ", jogo).strip(" /-|")
    tipo_aposta = re.sub(r"\s*/\s*/+\s*", " / ", tipo_aposta).strip(" /-|")

    valor = v20_detectar_valor(texto, bloco, linhas_originais)

    classificacao = classificar_aposta_multiplas_ou_simples(jogo, tipo_aposta)

    if classificacao.get("mercado") == "Ambas Marcam":
        resposta = classificacao.get("btts_resposta") or detectar_btts_resposta(tipo_aposta) or "sim"
        classificacao["selecao"] = resposta
        classificacao["btts_resposta"] = resposta
        classificacao["linha"] = None

    if classificacao.get("direcao") in ["over", "under"]:
        classificacao["selecao"] = classificacao["direcao"]

    if not str(classificacao.get("mercado", "")).startswith("Múltipla"):
        if len(str(classificacao.get("selecao", "")).split()) > 7:
            classificacao["selecao"] = ""

    aposta_final = f"{jogo} - {tipo_aposta}" if jogo and tipo_aposta else (tipo_aposta or jogo or "Erro OCR - revise manualmente")
    texto_interpretado = f"{jogo} {tipo_aposta}".strip()

    return {
        "casa": casa,
        "esporte": esporte,
        "jogo": jogo,
        "aposta": aposta_final,
        "odd": odd,
        "valor": valor,
        "mercado": classificacao.get("mercado", "Outro"),
        "direcao": classificacao.get("direcao", ""),
        "linha": classificacao.get("linha", None),
        "periodo": classificacao.get("periodo", "jogo inteiro"),
        "selecao": classificacao.get("selecao", ""),
        "btts_resposta": classificacao.get("btts_resposta", ""),
        "texto_bruto": texto,
        "texto_interpretado": texto_interpretado,
        "itens_multipla": classificacao.get("itens_multipla", {}),
        "itens_multipla_detalhados": classificacao.get("itens_multipla_detalhados", [])
    }


def extrair(texto):
    try:
        return extrair_v20(texto)

    except Exception as e:
        print("ERRO OCR/extrair V20:", e)

        texto_completo_limpo = limpar_linha(texto)
        classificacao = classificar_aposta(texto_completo_limpo, "")

        return {
            "casa": "",
            "esporte": "Futebol",
            "jogo": "",
            "aposta": texto_completo_limpo[:180] if texto_completo_limpo else "Erro OCR - revise manualmente",
            "odd": 1.0,
            "valor": 0.0,
            "mercado": classificacao["mercado"],
            "direcao": classificacao["direcao"],
            "linha": classificacao["linha"],
            "periodo": classificacao["periodo"],
            "selecao": classificacao["selecao"],
            "btts_resposta": classificacao["btts_resposta"],
            "texto_bruto": texto,
            "texto_interpretado": texto_completo_limpo,
            "itens_multipla": {},
            "itens_multipla_detalhados": []
        }



# ============================================================
# V23 - VALIDAÇÃO DE MÚLTIPLAS SIMPLES PELA API
# Ex: "Flamengo e Palmeiras vencem" -> só ganha se Flamengo E Palmeiras ganharem.
# ============================================================

def separar_times_vencedores_texto(texto):
    bruto = limpar_linha(texto)

    bruto = re.sub(r"\b(vencerem seus jogos|vencem seus jogos|vencerem os seus jogos|vencem os seus jogos)\b", "", bruto, flags=re.I)
    bruto = re.sub(r"\b(vence|vencem|vencer|vencerem|para vencer|ganha|ganham|resultado final|moneyline)\b", "", bruto, flags=re.I)
    bruto = re.sub(r"\b(futebol|basquete|tenis|tênis|volei|vôlei)\b", "", bruto, flags=re.I)
    bruto = re.sub(r"\s+", " ", bruto).strip(" /-|")

    partes = re.split(r"\s*(?:/|,|\+|\be\b|\band\b)\s*", bruto, flags=re.I)

    times = []
    vistos = set()

    for p in partes:
        p = limpar_linha(p)
        p = re.sub(r"\b(de|do|da|dos|das)\s+jogos?\b", "", p, flags=re.I)
        p = re.sub(r"\s+", " ", p).strip(" /-|")

        if len(p) < 3:
            continue

        n = normalizar_nome(p)

        if n in ["resultado", "final", "vencedor", "vencedores", "time", "times"]:
            continue

        if n and n not in vistos:
            vistos.add(n)
            times.append(p)

    return times


def detectar_multipla_moneyline_times(aposta):
    mercado = str(aposta.get("mercado", ""))
    texto_total = " ".join([
        str(aposta.get("aposta", "")),
        str(aposta.get("selecao", "")),
        str(aposta.get("texto_interpretado", ""))
    ])

    t = normalizar_nome(texto_total)

    if mercado.startswith("Múltipla") and texto_tem(t, [
        "vencem", "vencerem", "vence", "para vencer", "moneyline", "resultado final"
    ]):
        times = separar_times_vencedores_texto(texto_total)

        if len(times) < 2:
            times = separar_times_vencedores_texto(aposta.get("selecao", ""))

        if len(times) < 2:
            times = separar_times_vencedores_texto(aposta.get("aposta", ""))

        return times if len(times) >= 2 else []

    if texto_tem(t, ["vencem", "vencerem", "vencerem seus jogos", "vencem seus jogos"]):
        times = separar_times_vencedores_texto(texto_total)
        return times if len(times) >= 2 else []

    return []


def buscar_resultado_time_simples(nome_time, aposta_base):
    temp = dict(aposta_base)
    temp["jogo"] = nome_time
    temp["selecao"] = nome_time
    temp["mercado"] = "Moneyline"
    temp["esporte"] = aposta_base.get("esporte", "Futebol") or "Futebol"

    return buscar_resultado_futebol(temp)


def validar_time_venceu_no_resultado(nome_time, resultado):
    home = resultado.get("home_team", "")
    away = resultado.get("away_team", "")
    hs = resultado.get("home_score")
    aw = resultado.get("away_score")

    if hs is None or aw is None:
        return None

    if nome_bate(nome_time, home):
        return hs > aw

    if nome_bate(nome_time, away):
        return aw > hs

    return None


def validar_multipla_moneyline_api(aposta):
    times = detectar_multipla_moneyline_times(aposta)

    if len(times) < 2:
        return None, "múltipla sem times suficientes"

    detalhes = []

    for time_nome in times:
        resultado = buscar_resultado_time_simples(time_nome, aposta)

        if not resultado:
            return None, f"resultado não encontrado para {time_nome}"

        if resultado.get("status") not in ["FT", "AET", "PEN"]:
            return None, f"jogo ainda não finalizado para {time_nome}"

        venceu = validar_time_venceu_no_resultado(time_nome, resultado)

        if venceu is None:
            return None, f"não consegui confirmar o time {time_nome} no jogo encontrado"

        detalhes.append(f"{time_nome}: {'ganhou' if venceu else 'não ganhou'}")

        if not venceu:
            return "perdida", " | ".join(detalhes)

    return "ganha", " | ".join(detalhes)




# ============================================================
# V24 - MOTOR UNIVERSAL DE MÚLTIPLAS
# ============================================================

def dividir_itens_multipla_universal(texto):
    bruto = limpar_linha(texto)
    bruto = re.sub(r"\b(resultado final|moneyline)\s*[:\-]?", " ", bruto, flags=re.I)
    bruto = re.sub(r"\b(futebol|basquete|tenis|tênis|volei|vôlei)\b", " ", bruto, flags=re.I)
    bruto = re.sub(r"R\$\s*\d+[,.]?\d*", " ", bruto, flags=re.I)
    bruto = re.sub(r"\s+", " ", bruto).strip(" /-|")

    partes = re.split(r"\s*(?:/|\+|;|\n)\s*", bruto)
    itens = []

    for parte in partes:
        parte = limpar_linha(parte).strip(" /-|")
        if not parte:
            continue
        n = normalizar_nome(parte)

        if re.search(r"\b(e|and)\b", n) and texto_tem(n, ["vencem", "vencerem", "vence", "para vencer"]):
            frase = parte
            frase = re.sub(r"\b(vencerem seus jogos|vencem seus jogos|vencerem os seus jogos|vencem os seus jogos)\b", "", frase, flags=re.I)
            frase = re.sub(r"\b(vence|vencem|vencer|vencerem|para vencer|ganha|ganham)\b", "", frase, flags=re.I)
            subs = re.split(r"\s+\b(?:e|and)\b\s+", frase, flags=re.I)
            for sp in subs:
                sp = limpar_linha(sp).strip(" /-|")
                if len(sp) >= 3:
                    itens.append(sp + " vence")
            continue

        itens.append(parte)

    saida = []
    vistos = set()
    for item in itens:
        item = re.sub(r"\s+", " ", item).strip(" /-|")
        n = normalizar_nome(item)
        if n and n not in vistos:
            vistos.add(n)
            saida.append(item)
    return saida


def extrair_itens_multipla_universal(aposta):
    candidatos = []

    det = aposta.get("itens_multipla_detalhados", [])
    if isinstance(det, list):
        for it in det:
            if isinstance(it, dict) and it.get("texto"):
                candidatos.append(str(it.get("texto")))

    im = aposta.get("itens_multipla", {})
    if isinstance(im, dict):
        for campo in ["selecoes", "jogos"]:
            val = im.get(campo, [])
            if isinstance(val, list):
                candidatos.extend([str(x) for x in val if str(x).strip()])

    for campo in ["selecao", "aposta", "texto_interpretado"]:
        val = str(aposta.get(campo, "") or "")
        if val:
            candidatos.extend(dividir_itens_multipla_universal(val))

    texto_total = " ".join([str(aposta.get("aposta", "")), str(aposta.get("selecao", "")), str(aposta.get("texto_interpretado", ""))])
    candidatos.extend(dividir_itens_multipla_universal(texto_total))

    saida = []
    vistos = set()
    for c in candidatos:
        c = limpar_linha(c)
        c = re.sub(r"\b(multipla|múltipla|dupla|tripla)\b", " ", c, flags=re.I)
        c = re.sub(r"\s+", " ", c).strip(" /-|")
        if len(c) < 3:
            continue
        n = normalizar_nome(c)
        if n in vistos:
            continue
        if len(c.split()) > 14 and len(saida) >= 2:
            continue
        vistos.add(n)
        saida.append(c)

    if len(saida) == 1:
        div = dividir_itens_multipla_universal(saida[0])
        if len(div) > 1:
            saida = div
    return saida


def montar_item_aposta_para_validar(item_texto, aposta_base):
    jogo_base = aposta_base.get("jogo", "")
    item_limpo = limpar_linha(item_texto)
    n = normalizar_nome(item_limpo)

    if (not texto_tem(n, ["vence", "vencem", "vencer", "empate", "over", "under", "mais de", "menos de", "ambas", "btts", "escanteio", "corner", "chute", "marcador", "assistencia", "assistência", "dupla chance", "chance dupla"]) and len(item_limpo.split()) <= 4):
        item_limpo = item_limpo + " vence"

    cls = classificar_item_combinada_visual_v28(item_limpo, jogo_base) if "classificar_item_combinada_visual_v28" in globals() else classificar_aposta(item_limpo, jogo_base)
    item = dict(aposta_base)
    item["aposta"] = item_limpo
    item["texto_interpretado"] = item_limpo
    item["mercado"] = cls.get("mercado", "Outro")
    item["direcao"] = cls.get("direcao", "")
    item["linha"] = cls.get("linha", None)
    item["periodo"] = cls.get("periodo", "jogo inteiro")
    item["selecao"] = cls.get("selecao", "")
    item["btts_resposta"] = cls.get("btts_resposta", "")

    if item["mercado"] == "Moneyline":
        sel = cls.get("selecao", "")
        if not sel or normalizar_nome(sel) in ["resultado final", "resultado", "final"]:
            sel = re.sub(r"\b(vence|vencem|vencer|vencerem|para vencer|ganha|ganham)\b", "", item_limpo, flags=re.I)
            sel = re.sub(r"\s+", " ", sel).strip()
        item["selecao"] = sel
        if not jogo_base or " x " not in normalizar_nome(jogo_base):
            item["jogo"] = sel
    item = corrigir_item_quantitativo_v27(item)

    return item



def corrigir_item_quantitativo_v27(item):
    mercado = str(item.get("mercado", ""))
    texto = " ".join([
        str(item.get("aposta", "")),
        str(item.get("selecao", "")),
        str(item.get("texto_interpretado", ""))
    ])

    if mercado in ["Escanteios", "Chutes", "Chutes no Gol", "Total", "Total de Gols", "Cartões"]:
        direcao, linha = normalizar_direcao_linha_v27(texto)

        if direcao:
            item["direcao"] = direcao
            item["selecao"] = direcao

        if linha is not None:
            item["linha"] = linha

    return item


def validar_item_multipla_universal(item_aposta):
    if normalizar_nome(item_aposta.get("esporte", "Futebol")) != "futebol":
        return None, "ignorado: não é futebol"

    resultado = buscar_resultado_futebol(item_aposta)
    if not resultado:
        return None, "resultado não encontrado"
    if resultado.get("status") not in ["FT", "AET", "PEN"]:
        return None, "jogo ainda não finalizado"

    if item_aposta.get("mercado") == "HT Vence sem sofrer":
        status = validar_ht_vence_sem_sofrer_v28(item_aposta, resultado)
    else:
        status = validar_aposta_com_resultado(item_aposta, resultado)

    if status:
        return status, "validado"
    return None, "mercado não validado"


def validar_multipla_universal_api(aposta):
    itens = extrair_itens_multipla_universal(aposta)
    if len(itens) < 2:
        return None, "múltipla sem itens suficientes"

    detalhes = []
    for item_texto in itens:
        item_aposta = montar_item_aposta_para_validar(item_texto, aposta)
        mercado = item_aposta.get("mercado", "Outro")
        if mercado == "Outro":
            detalhes.append(f"{item_texto}: mercado não identificado")
            return None, " | ".join(detalhes)

        status, msg = validar_item_multipla_universal(item_aposta)
        detalhes.append(f"{item_texto} [{mercado}]: {status or msg}")

        if status == "perdida":
            return "perdida", " | ".join(detalhes)
        if status != "ganha":
            return None, " | ".join(detalhes)

    return "ganha", " | ".join(detalhes)






# ============================================================
# V25 - FORMATAÇÃO INTELIGENTE DE MÚLTIPLAS COMBINADAS
# ============================================================

def dividir_itens_mercados_mesma_linha(texto):
    bruto = limpar_linha(texto)
    bruto = re.sub(r"\b(resultado final|futebol)\b", " ", bruto, flags=re.I)
    bruto = re.sub(r"\s+", " ", bruto).strip(" /-|")
    partes = re.split(r"\s*(?:/|,|\+|;|\s+e\s+|\s+and\s+)\s*", bruto, flags=re.I)

    saida = []
    for p in partes:
        p = limpar_linha(p).strip(" /-|")
        if not p:
            continue
        n = normalizar_nome(p)

        if re.search(r"\d+[,.]\d+", p) and texto_tem(n, ["cantos", "canto", "escanteios", "escanteio", "corners", "corner"]):
            if not detectar_direcao(p):
                p = "Over " + p

        if re.search(r"\d+[,.]\d+", p) and texto_tem(n, ["gols", "gol", "goals"]):
            if not detectar_direcao(p) and texto_tem(normalizar_nome(bruto), ["over", "mais de"]):
                p = "Over " + p

        saida.append(p)

    if len(saida) == 1:
        s = saida[0]
        tokens = []

        m_gols = re.search(r"(over|mais de|under|menos de)?\s*(\d+[,.]\d+)\s*(gols?|goals?)", s, flags=re.I)
        if m_gols:
            dire = m_gols.group(1) or "over"
            tokens.append(f"{dire} {m_gols.group(2)} gols")

        if eh_texto_btts(s):
            tokens.append("BTTS")

        m_cantos = re.search(r"(over|mais de|under|menos de)?\s*(\d+[,.]\d+)\s*(cantos?|escanteios?|corners?)", s, flags=re.I)
        if m_cantos:
            dire = m_cantos.group(1) or "over"
            tokens.append(f"{dire} {m_cantos.group(2)} cantos")

        if len(tokens) > 1:
            return tokens

    return saida


def classificar_item_combinada_visual(item, jogo=""):
    item = limpar_linha(item)
    t = normalizar_nome(item)

    out = {"texto": item, "mercado": "Outro", "selecao": "", "direcao": "", "linha": None}

    if not item:
        return out

    if eh_texto_btts(item):
        out["mercado"] = "Ambas Marcam"
        out["selecao"] = detectar_btts_resposta(item) or "sim"
        return out

    direcao = detectar_direcao(item)
    linha = extrair_linha(item)

    if texto_tem(t, ["cantos", "canto", "escanteios", "escanteio", "corner", "corners"]):
        out["mercado"] = "Escanteios"
        out["direcao"] = direcao or "over"
        out["selecao"] = out["direcao"]
        out["linha"] = linha
        return out

    if texto_tem(t, ["chutes a gol", "chutes no gol", "shot on target", "shots on target"]):
        out["mercado"] = "Chutes no Gol"
        out["direcao"] = direcao or ("over" if linha is not None else "")
        out["selecao"] = out["direcao"]
        out["linha"] = linha
        return out

    if texto_tem(t, ["chutes", "shots", "finalizacoes", "finalizações"]):
        out["mercado"] = "Chutes"
        out["direcao"] = direcao or ("over" if linha is not None else "")
        out["selecao"] = out["direcao"]
        out["linha"] = linha
        return out

    if texto_tem(t, ["gols", "gol", "goals"]) or direcao:
        out["mercado"] = "Total"
        out["direcao"] = direcao or ("over" if linha is not None else "")
        out["selecao"] = out["direcao"]
        out["linha"] = linha
        return out

    cls = classificar_aposta(item, jogo)
    out["mercado"] = cls.get("mercado", "Outro")
    out["selecao"] = cls.get("selecao", "")
    out["direcao"] = cls.get("direcao", "")
    out["linha"] = cls.get("linha", None)
    return out


def resumir_multiplas_para_campos(itens):
    mercados, selecoes, linhas = [], [], []
    for it in itens:
        mercados.append(it.get("mercado", "Outro") or "Outro")
        sel = it.get("selecao", "") or it.get("direcao", "")
        selecoes.append(sel if sel else "-")
        linha = it.get("linha", None)
        if isinstance(linha, float):
            linhas.append(str(linha).rstrip("0").rstrip("."))
        elif linha is None:
            linhas.append("-")
        else:
            linhas.append(str(linha))
    return {"mercado": " / ".join(mercados), "selecao": " / ".join(selecoes), "linha": " / ".join(linhas)}



# ============================================================
# V27 - FIX LINHA EM MÚLTIPLAS
# Ex: "Ambas Marcam / Mais de 10.5 Escanteios"
# mercado: Ambas Marcam / Escanteios
# selecao: sim / over
# linha: - / 10.5
# ============================================================

def extrair_linha_mercado_v27(texto):
    s = str(texto or "").replace(",", ".")

    # Prioriza decimal.
    m = re.search(r"\b(\d{1,3}\.\d+)\b", s)
    if m:
        try:
            return float(m.group(1))
        except:
            pass

    # Depois inteiro, mas evita odds/valores grandes demais.
    m = re.search(r"\b(\d{1,3})\b", s)
    if m:
        try:
            v = float(m.group(1))
            if 0 <= v <= 99:
                return v
        except:
            pass

    return None


def normalizar_direcao_linha_v27(texto):
    direcao = detectar_direcao(texto)
    linha = extrair_linha_mercado_v27(texto)

    # Se tem linha e mercado quantitativo sem direção explícita, assume over.
    t = normalizar_nome(texto)
    if linha is not None and not direcao and texto_tem(t, [
        "gols", "gol", "goals", "escanteios", "escanteio", "cantos", "canto",
        "corner", "corners", "chutes", "shots", "cartoes", "cartões", "cards"
    ]):
        direcao = "over"

    return direcao, linha


def classificar_item_combinada_visual_v27(item, jogo=""):
    item = limpar_linha(item)
    t = normalizar_nome(item)

    out = {
        "texto": item,
        "mercado": "Outro",
        "selecao": "",
        "direcao": "",
        "linha": None,
        "periodo": detectar_periodo(item)
    }

    if not item:
        return out

    if eh_texto_btts(item):
        out["mercado"] = "Ambas Marcam"
        out["selecao"] = detectar_btts_resposta(item) or "sim"
        out["linha"] = None
        return out

    if texto_tem(t, [
        "algum time vence ht", "algum time vence o ht",
        "algum time vence 1 tempo", "algum time vence o 1 tempo",
        "algum time vence primeiro tempo", "algum time vence o primeiro tempo"
    ]):
        out["mercado"] = "HT Resultado"
        out["selecao"] = "sim"
        out["linha"] = None
        out["periodo"] = "1º tempo"
        return out

    direcao, linha = normalizar_direcao_linha_v27(item)

    if texto_tem(t, ["escanteio", "escanteios", "canto", "cantos", "corner", "corners"]):
        out["mercado"] = "Escanteios"
        out["direcao"] = direcao or "over"
        out["selecao"] = out["direcao"]
        out["linha"] = linha
        return out

    if texto_tem(t, ["chutes a gol", "chutes no gol", "shot on target", "shots on target"]):
        out["mercado"] = "Chutes no Gol"
        out["direcao"] = direcao or ("over" if linha is not None else "")
        out["selecao"] = out["direcao"]
        out["linha"] = linha
        return out

    if texto_tem(t, ["chutes", "shots", "finalizacoes", "finalizações"]):
        out["mercado"] = "Chutes"
        out["direcao"] = direcao or ("over" if linha is not None else "")
        out["selecao"] = out["direcao"]
        out["linha"] = linha
        return out

    if texto_tem(t, ["gols", "gol", "goals"]) or direcao:
        out["mercado"] = "Total de Gols" if texto_tem(t, ["gols", "gol", "goals"]) else "Total"
        out["direcao"] = direcao or ("over" if linha is not None else "")
        out["selecao"] = out["direcao"]
        out["linha"] = linha
        return out

    cls = classificar_aposta(item, jogo)
    out["mercado"] = cls.get("mercado", "Outro")
    out["selecao"] = cls.get("selecao", "")
    out["direcao"] = cls.get("direcao", "")
    out["linha"] = cls.get("linha", None)
    out["periodo"] = cls.get("periodo", detectar_periodo(item))
    return out


def aplicar_formatacao_multiplas_combinadas(resultado):
    aposta_txt = str(resultado.get("aposta", ""))
    jogo = resultado.get("jogo", "")
    mercados_txt = aposta_txt.split(" - ", 1)[1] if " - " in aposta_txt else aposta_txt

    itens_txt = dividir_itens_mercados_mesma_linha(mercados_txt)
    if len(itens_txt) < 2:
        return resultado

    itens = [classificar_item_combinada_visual_v27(x, jogo) for x in itens_txt]
    itens_validos = [i for i in itens if i.get("mercado") != "Outro"]

    if len(itens_validos) < 2:
        return resultado

    resumo = resumir_multiplas_para_campos(itens_validos)

    resultado["mercado"] = resumo["mercado"]
    resultado["selecao"] = resumo["selecao"]
    resultado["linha"] = resumo["linha"]
    resultado["direcao"] = ""
    resultado["mercado_api"] = "Múltipla - Combinada"
    resultado["itens_multipla_detalhados"] = itens_validos
    resultado["itens_multipla"] = {
        "jogos": [jogo] if jogo else [],
        "selecoes": [i.get("texto", "") for i in itens_validos],
        "qtd_jogos": 1 if jogo else 0,
        "qtd_selecoes": len(itens_validos)
    }
    return resultado




# ============================================================
# V26 - MULTIPLAS COM DESCRIÇÃO DE MERCADO NO FINAL
# ============================================================

def item_tem_selecao_clara_v26(item):
    t = normalizar_nome(item)

    if detectar_direcao(item):
        return True

    if eh_texto_btts(item):
        return True

    if texto_tem(t, [
        "vence", "vencem", "vencer", "vencerem", "ml", "moneyline",
        "ou empate", "dupla chance", "chance dupla",
        "marcador", "assistencia", "assistência",
        "tem 1 ou mais", "chutes", "chutes a gol",
        "algum time vence"
    ]):
        return True

    if re.search(r"\d+[,.]\d+", str(item)) and texto_tem(t, [
        "gols", "gol", "escanteios", "escanteio", "cantos", "canto",
        "chutes", "cartoes", "cartões", "cards"
    ]):
        return True

    return False


def item_e_descricao_mercado_v26(item):
    t = normalizar_nome(item)

    if item_tem_selecao_clara_v26(item):
        return False

    descricoes = [
        "total de gols", "total gols", "total de gol",
        "total de escanteios", "total escanteios", "total de cantos", "total cantos",
        "resultado final", "mercado final",
        "total de chutes", "total chutes",
        "total de cartoes", "total de cartões"
    ]

    return any(d in t for d in descricoes)


def juntar_descricoes_de_mercado_v26(partes):
    partes = [limpar_linha(p).strip(" /-|") for p in partes if limpar_linha(p).strip(" /-|")]

    if len(partes) < 3:
        return partes

    selecoes = [p for p in partes if item_tem_selecao_clara_v26(p)]
    descricoes = [p for p in partes if item_e_descricao_mercado_v26(p)]

    if len(selecoes) >= 1 and len(descricoes) >= 1 and len(selecoes) + len(descricoes) == len(partes):
        saida = []
        for i, sel in enumerate(selecoes):
            desc = descricoes[i] if i < len(descricoes) else ""
            saida.append(sel + (" | " + desc if desc else ""))
        return saida

    return partes


def classificar_item_combinada_visual_v26(item, jogo=""):
    item_original = limpar_linha(item)
    selecao_txt = item_original
    descricao_txt = ""

    if " | " in item_original:
        selecao_txt, descricao_txt = [x.strip() for x in item_original.split(" | ", 1)]

    texto_analise = (selecao_txt + " " + descricao_txt).strip()
    t = normalizar_nome(texto_analise)

    out = {
        "texto": selecao_txt,
        "descricao_mercado": descricao_txt,
        "mercado": "Outro",
        "selecao": "",
        "direcao": "",
        "linha": None,
        "periodo": detectar_periodo(texto_analise)
    }

    if not selecao_txt:
        return out

    if texto_tem(t, [
        "algum time vence ht", "algum time vence o ht",
        "algum time vence 1 tempo", "algum time vence o 1 tempo",
        "algum time vence primeiro tempo", "algum time vence o primeiro tempo"
    ]):
        out["mercado"] = "HT Resultado"
        out["selecao"] = "sim"
        out["linha"] = None
        out["periodo"] = "1º tempo"
        return out

    if eh_texto_btts(texto_analise):
        out["mercado"] = "Ambas Marcam"
        out["selecao"] = detectar_btts_resposta(texto_analise) or "sim"
        out["linha"] = None
        return out

    # ML / time vence
    if texto_tem(t, [" ml", "ml ", "vence", "vencem", "para vencer", "moneyline"]):
        cls = classificar_aposta(selecao_txt, jogo)
        if cls.get("mercado") == "Moneyline" or texto_tem(t, ["ml", "vence", "vencem", "para vencer"]):
            out["mercado"] = "Moneyline"
            selecao = cls.get("selecao", "")
            if not selecao or normalizar_nome(selecao) in ["resultado final", "resultado", "final"]:
                selecao = re.sub(r"\b(ml|vence|vencem|vencer|vencerem|para vencer|ganha|ganham)\b", "", selecao_txt, flags=re.I)
                selecao = re.sub(r"\s+", " ", selecao).strip()
            out["selecao"] = selecao
            return out

    direcao = detectar_direcao(selecao_txt) or detectar_direcao(texto_analise)
    linha = extrair_linha(selecao_txt)

    if linha is not None and not direcao and texto_tem(t, [
        "gols", "gol", "escanteios", "escanteio", "cantos", "canto",
        "chutes", "cartoes", "cartões"
    ]):
        direcao = "over"

    if texto_tem(t, ["escanteio", "escanteios", "canto", "cantos", "corner", "corners"]):
        out["mercado"] = "Escanteios"
        out["direcao"] = direcao or "over"
        out["selecao"] = out["direcao"]
        out["linha"] = linha
        return out

    if texto_tem(t, ["chutes a gol", "chutes no gol", "shot on target", "shots on target"]):
        out["mercado"] = "Chutes no Gol"
        out["direcao"] = direcao or ("over" if linha is not None else "")
        out["selecao"] = out["direcao"]
        out["linha"] = linha
        return out

    if texto_tem(t, ["chutes", "shots", "finalizacoes", "finalizações"]):
        out["mercado"] = "Chutes"
        out["direcao"] = direcao or ("over" if linha is not None else "")
        out["selecao"] = out["direcao"]
        out["linha"] = linha
        return out

    if texto_tem(t, ["gols", "gol", "goals"]) or direcao:
        out["mercado"] = "Total de Gols" if texto_tem(t, ["gols", "gol", "goals"]) else "Total"
        out["direcao"] = direcao or ("over" if linha is not None else "")
        out["selecao"] = out["direcao"]
        out["linha"] = linha
        return out

    cls = classificar_aposta(selecao_txt, jogo)
    out["mercado"] = cls.get("mercado", "Outro")
    out["selecao"] = cls.get("selecao", "")
    out["direcao"] = cls.get("direcao", "")
    out["linha"] = cls.get("linha", None)
    out["periodo"] = cls.get("periodo", detectar_periodo(texto_analise))
    return out


def dividir_itens_mercados_mesma_linha(texto):
    bruto = limpar_linha(texto)
    bruto = re.sub(r"\b(futebol)\b", " ", bruto, flags=re.I)
    bruto = re.sub(r"\s+", " ", bruto).strip(" /-|")

    partes = re.split(r"\s*(?:/|,|\+|;|\s+e\s+|\s+and\s+)\s*", bruto, flags=re.I)
    partes = [limpar_linha(p).strip(" /-|") for p in partes if limpar_linha(p).strip(" /-|")]

    partes = juntar_descricoes_de_mercado_v26(partes)

    saida = []
    for p in partes:
        n = normalizar_nome(p)

        if re.search(r"\d+[,.]\d+", p) and texto_tem(n, ["cantos", "canto", "escanteios", "escanteio", "corners", "corner"]):
            if not detectar_direcao(p):
                p = "Over " + p

        if re.search(r"\d+[,.]\d+", p) and texto_tem(n, ["gols", "gol", "goals"]):
            if not detectar_direcao(p) and texto_tem(normalizar_nome(bruto), ["over", "mais de"]):
                p = "Over " + p

        saida.append(p)

    if len(saida) == 1:
        s = saida[0]
        tokens = []

        m_gols = re.search(r"(over|mais de|under|menos de)?\s*(\d+[,.]\d+)\s*(gols?|goals?)(?:\s*no\s*1[ºo]?\s*tempo)?", s, flags=re.I)
        if m_gols:
            dire = m_gols.group(1) or "over"
            extra = " no 1º tempo" if re.search(r"1[ºo]?\s*tempo", s, flags=re.I) else ""
            tokens.append(f"{dire} {m_gols.group(2)} gols{extra}")

        if eh_texto_btts(s):
            tokens.append("BTTS")

        m_cantos = re.search(r"(over|mais de|under|menos de)?\s*(\d+[,.]\d+)\s*(cantos?|escanteios?|corners?)", s, flags=re.I)
        if m_cantos:
            dire = m_cantos.group(1) or "over"
            tokens.append(f"{dire} {m_cantos.group(2)} cantos")

        if len(tokens) > 1:
            return tokens

    return saida


def resumir_multiplas_para_campos(itens):
    mercados, selecoes, linhas, periodos = [], [], [], []

    for it in itens:
        mercado = it.get("mercado", "Outro") or "Outro"
        selecao = it.get("selecao", "") or it.get("direcao", "")
        linha = it.get("linha", None)
        periodo = it.get("periodo", "jogo inteiro") or "jogo inteiro"

        mercados.append(mercado)
        selecoes.append(selecao if selecao else "-")
        linhas.append(str(linha).rstrip("0").rstrip(".") if isinstance(linha, float) else (str(linha) if linha is not None else "-"))
        periodos.append(periodo)

    return {
        "mercado": " / ".join(mercados),
        "selecao": " / ".join(selecoes),
        "linha": " / ".join(linhas),
        "periodo": " / ".join(periodos)
    }



# ============================================================
# V27 - FIX LINHA EM MÚLTIPLAS
# Ex: "Ambas Marcam / Mais de 10.5 Escanteios"
# mercado: Ambas Marcam / Escanteios
# selecao: sim / over
# linha: - / 10.5
# ============================================================

def extrair_linha_mercado_v27(texto):
    s = str(texto or "").replace(",", ".")

    # Prioriza decimal.
    m = re.search(r"\b(\d{1,3}\.\d+)\b", s)
    if m:
        try:
            return float(m.group(1))
        except:
            pass

    # Depois inteiro, mas evita odds/valores grandes demais.
    m = re.search(r"\b(\d{1,3})\b", s)
    if m:
        try:
            v = float(m.group(1))
            if 0 <= v <= 99:
                return v
        except:
            pass

    return None


def normalizar_direcao_linha_v27(texto):
    direcao = detectar_direcao(texto)
    linha = extrair_linha_mercado_v27(texto)

    # Se tem linha e mercado quantitativo sem direção explícita, assume over.
    t = normalizar_nome(texto)
    if linha is not None and not direcao and texto_tem(t, [
        "gols", "gol", "goals", "escanteios", "escanteio", "cantos", "canto",
        "corner", "corners", "chutes", "shots", "cartoes", "cartões", "cards"
    ]):
        direcao = "over"

    return direcao, linha


def classificar_item_combinada_visual_v27(item, jogo=""):
    item = limpar_linha(item)
    t = normalizar_nome(item)

    out = {
        "texto": item,
        "mercado": "Outro",
        "selecao": "",
        "direcao": "",
        "linha": None,
        "periodo": detectar_periodo(item)
    }

    if not item:
        return out

    if eh_texto_btts(item):
        out["mercado"] = "Ambas Marcam"
        out["selecao"] = detectar_btts_resposta(item) or "sim"
        out["linha"] = None
        return out

    if texto_tem(t, [
        "algum time vence ht", "algum time vence o ht",
        "algum time vence 1 tempo", "algum time vence o 1 tempo",
        "algum time vence primeiro tempo", "algum time vence o primeiro tempo"
    ]):
        out["mercado"] = "HT Resultado"
        out["selecao"] = "sim"
        out["linha"] = None
        out["periodo"] = "1º tempo"
        return out

    direcao, linha = normalizar_direcao_linha_v27(item)

    if texto_tem(t, ["escanteio", "escanteios", "canto", "cantos", "corner", "corners"]):
        out["mercado"] = "Escanteios"
        out["direcao"] = direcao or "over"
        out["selecao"] = out["direcao"]
        out["linha"] = linha
        return out

    if texto_tem(t, ["chutes a gol", "chutes no gol", "shot on target", "shots on target"]):
        out["mercado"] = "Chutes no Gol"
        out["direcao"] = direcao or ("over" if linha is not None else "")
        out["selecao"] = out["direcao"]
        out["linha"] = linha
        return out

    if texto_tem(t, ["chutes", "shots", "finalizacoes", "finalizações"]):
        out["mercado"] = "Chutes"
        out["direcao"] = direcao or ("over" if linha is not None else "")
        out["selecao"] = out["direcao"]
        out["linha"] = linha
        return out

    if texto_tem(t, ["gols", "gol", "goals"]) or direcao:
        out["mercado"] = "Total de Gols" if texto_tem(t, ["gols", "gol", "goals"]) else "Total"
        out["direcao"] = direcao or ("over" if linha is not None else "")
        out["selecao"] = out["direcao"]
        out["linha"] = linha
        return out

    cls = classificar_aposta(item, jogo)
    out["mercado"] = cls.get("mercado", "Outro")
    out["selecao"] = cls.get("selecao", "")
    out["direcao"] = cls.get("direcao", "")
    out["linha"] = cls.get("linha", None)
    out["periodo"] = cls.get("periodo", detectar_periodo(item))
    return out


def aplicar_formatacao_multiplas_combinadas(resultado):
    aposta_txt = str(resultado.get("aposta", ""))
    jogo = resultado.get("jogo", "")

    mercados_txt = aposta_txt.split(" - ", 1)[1] if " - " in aposta_txt else aposta_txt
    itens_txt = dividir_itens_mercados_mesma_linha(mercados_txt)

    if len(itens_txt) < 2:
        return resultado

    itens = [classificar_item_combinada_visual_v27(x, jogo) for x in itens_txt]
    itens_validos = [i for i in itens if i.get("mercado") != "Outro"]

    if len(itens_validos) < 2:
        return resultado

    resumo = resumir_multiplas_para_campos(itens_validos)

    resultado["mercado"] = resumo["mercado"]
    resultado["selecao"] = resumo["selecao"]
    resultado["linha"] = resumo["linha"]
    resultado["periodo"] = resumo["periodo"]
    resultado["direcao"] = ""
    resultado["mercado_api"] = "Múltipla - Combinada"
    resultado["itens_multipla_detalhados"] = itens_validos
    resultado["itens_multipla"] = {
        "jogos": [jogo] if jogo else [],
        "selecoes": [i.get("texto", "") for i in itens_validos],
        "qtd_jogos": 1 if jogo else 0,
        "qtd_selecoes": len(itens_validos)
    }

    return resultado




# ============================================================
# V28 - MOTOR COMPLETO DE COMBINAÇÕES
# ============================================================

def extrair_linha_mercado_v28(texto):
    s = str(texto or "").replace(",", ".")
    m = re.search(r"\b(\d{1,3}(?:\.\d+)?)\s*\+", s)
    if m:
        return float(m.group(1))
    m = re.search(r"\b(\d{1,3}\.\d+)\b", s)
    if m:
        return float(m.group(1))
    m = re.search(r"\b(\d{1,3})\b", s)
    if m:
        v = float(m.group(1))
        if 0 <= v <= 99:
            return v
    return None


def detectar_direcao_v28(texto):
    s = str(texto or "")
    t = normalizar_nome(s)
    d = detectar_direcao(s)
    if d:
        return d
    if re.search(r"\b\d+(?:[,.]\d+)?\s*\+", s):
        return "over"
    if texto_tem(t, ["ou mais", "pelo menos", "no minimo", "no mínimo"]):
        return "over"
    return ""


def expandir_abreviacoes_v28(texto):
    s = str(texto or "")
    trocas = [
        (r"\besc\b", "escanteios"),
        (r"\bescs\b", "escanteios"),
        (r"\bcantos?\b", "escanteios"),
        (r"\bcards?\b", "cartoes"),
        (r"\bcart(ao|ão|oes|ões)\b", "cartoes"),
        (r"\bdc\b", "dupla chance"),
    ]
    for rgx, rep in trocas:
        s = re.sub(rgx, rep, s, flags=re.I)
    return re.sub(r"\s+", " ", s).strip()


def split_inteligente_combinacao_v28(texto):
    s = expandir_abreviacoes_v28(limpar_linha(texto))
    s = re.sub(r"\b(futebol)\b", " ", s, flags=re.I)
    s = re.sub(r"R\$\s*\d+[,.]?\d*", " ", s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip(" /-|")

    direcao_global = detectar_direcao_v28(s)
    partes = re.split(r"\s*(?:/|,|;|\+|\s+e\s+|\s+and\s+)\s*", s, flags=re.I)
    partes = [expandir_abreviacoes_v28(p).strip(" /-|") for p in partes if p.strip(" /-|")]

    saida = []
    for p in partes:
        n = normalizar_nome(p)
        if re.search(r"\d+(?:[,.]\d+)?", p) and not detectar_direcao_v28(p):
            if texto_tem(n, ["gols", "gol", "escanteios", "cartoes", "chutes"]):
                p = (direcao_global or "over") + " " + p
        saida.append(p)

    if len(saida) <= 1:
        tokens = []
        patterns = [
            r"(?:over|under|mais de|menos de)?\s*\d+(?:[,.]\d+)?\+?\s*(?:gols?|goals?)",
            r"(?:over|under|mais de|menos de)?\s*\d+(?:[,.]\d+)?\+?\s*(?:escanteios?|corners?)",
            r"(?:over|under|mais de|menos de)?\s*\d+(?:[,.]\d+)?\+?\s*(?:cartoes|cartões|cards?)",
            r"(?:over|under|mais de|menos de)?\s*\d+(?:[,.]\d+)?\+?\s*(?:chutes(?: a gol| no gol)?|shots(?: on target)?)",
        ]
        for pat in patterns:
            for m in re.finditer(pat, s, flags=re.I):
                tok = m.group(0).strip()
                if tok and tok not in tokens:
                    if not detectar_direcao_v28(tok):
                        tok = (direcao_global or "over") + " " + tok
                    tokens.append(tok)

        if eh_texto_btts(s):
            tokens.append("BTTS")

        m_dc = re.search(r"(dupla chance\s+.+?)(?:$|\s+HT|\s+1[ºo]?\s*tempo)", s, flags=re.I)
        if m_dc:
            tok = m_dc.group(1).strip()
            if re.search(r"\b(HT|1[ºo]?\s*tempo|primeiro tempo)\b", s, flags=re.I):
                tok += " HT"
            tokens.append(tok)

        for m in re.finditer(r"([A-Za-zÀ-ÿ'.\- ]{3,})\s+anytime\b", s, flags=re.I):
            tok = m.group(0).strip()
            if tok not in tokens:
                tokens.append(tok)

        if len(tokens) > 1:
            saida = tokens

    final = []
    vistos = set()
    for p in saida:
        p = re.sub(r"\s+", " ", p).strip(" /-|")
        n = normalizar_nome(p)
        if p and n not in vistos:
            vistos.add(n)
            final.append(p)
    return final


def item_tem_selecao_clara_v28(item):
    t = normalizar_nome(item)
    return (
        bool(detectar_direcao_v28(item)) or
        eh_texto_btts(item) or
        bool(re.search(r"\d+(?:[,.]\d+)?\+", str(item))) or
        texto_tem(t, [
            "vence", "vencem", "vencer", "vencerem", "ml", "moneyline",
            "ou empate", "dupla chance", "chance dupla",
            "marcador", "assistencia", "assistência", "anytime",
            "tem 1 ou mais", "chutes", "algum time vence"
        ]) or
        (bool(re.search(r"\d+[,.]\d+", str(item))) and texto_tem(t, ["gols", "gol", "escanteios", "cartoes", "chutes"]))
    )


def item_e_descricao_mercado_v28(item):
    t = normalizar_nome(item)
    if item_tem_selecao_clara_v28(item):
        return False
    return texto_tem(t, [
        "total de gols", "total gols", "total de escanteios", "total escanteios",
        "total de cartoes", "total de cartões", "total cartoes", "total cards",
        "total de chutes", "resultado final", "mercado final"
    ])


def juntar_descricoes_de_mercado_v28(partes):
    partes = [limpar_linha(p).strip(" /-|") for p in partes if limpar_linha(p).strip(" /-|")]
    if len(partes) < 3:
        return partes
    selecoes = [p for p in partes if item_tem_selecao_clara_v28(p)]
    descricoes = [p for p in partes if item_e_descricao_mercado_v28(p)]
    if len(selecoes) >= 1 and len(descricoes) >= 1 and len(selecoes) + len(descricoes) == len(partes):
        return [sel + (" | " + descricoes[i] if i < len(descricoes) else "") for i, sel in enumerate(selecoes)]
    return partes


def limpar_nome_marcador_anytime_v28(texto):
    s = limpar_linha(texto)
    s = re.sub(r"\b(anytime|a qualquer momento|para marcar|marcador|gol do jogador|to score)\b", " ", s, flags=re.I)
    s = re.sub(r"\d+(?:[,.]\d+)?\+?", " ", s)
    s = re.sub(r"[:/|()\[\]{}+\-]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def classificar_item_combinada_visual_v28(item, jogo=""):
    item_original = expandir_abreviacoes_v28(limpar_linha(item))
    selecao_txt = item_original
    descricao_txt = ""
    if " | " in item_original:
        selecao_txt, descricao_txt = [x.strip() for x in item_original.split(" | ", 1)]

    texto_analise = (selecao_txt + " " + descricao_txt).strip()
    t = normalizar_nome(texto_analise)
    out = {"texto": selecao_txt, "descricao_mercado": descricao_txt, "mercado": "Outro", "selecao": "", "direcao": "", "linha": None, "periodo": detectar_periodo(texto_analise)}

    if texto_tem(t, ["vence de 0 o ht", "vence de zero o ht", "vence sem sofrer o ht", "vence de 0 no ht"]):
        out["mercado"] = "HT Vence sem sofrer"
        out["periodo"] = "1º tempo"
        out["selecao"] = re.sub(r"\b(vence de 0 o ht|vence de zero o ht|vence sem sofrer o ht|vence de 0 no ht|ht)\b", "", selecao_txt, flags=re.I).strip()
        return out

    if texto_tem(t, ["algum time vence ht", "algum time vence o ht", "algum time vence 1 tempo", "algum time vence primeiro tempo"]):
        out["mercado"] = "HT Resultado"
        out["selecao"] = "sim"
        out["periodo"] = "1º tempo"
        return out

    if eh_texto_btts(texto_analise):
        out["mercado"] = "Ambas Marcam"
        out["selecao"] = detectar_btts_resposta(texto_analise) or "sim"
        return out

    if texto_tem(t, ["anytime", "a qualquer momento", "to score"]):
        out["mercado"] = "Marcador"
        out["selecao"] = limpar_nome_marcador_anytime_v28(selecao_txt)
        return out

    if texto_tem(t, ["dupla chance"]):
        out["mercado"] = "Dupla Chance"
        out["periodo"] = "1º tempo" if texto_tem(t, ["ht", "1 tempo", "primeiro tempo"]) else "jogo inteiro"
        txt = re.sub(r"\b(dupla chance|dc|ht|1[ºo]?\s*tempo|primeiro tempo)\b", " ", selecao_txt, flags=re.I)
        txt = re.sub(r"\s+", " ", txt).strip()
        out["selecao"] = detectar_dupla_chance_selecao(txt) or txt
        return out

    if re.search(r"\bML\b", selecao_txt, flags=re.I) or texto_tem(t, ["moneyline", "vence", "vencem", "para vencer"]):
        out["mercado"] = "Moneyline"
        selecao = re.sub(r"\b(ML|moneyline|vence|vencem|vencer|vencerem|para vencer|ganha|ganham)\b", " ", selecao_txt, flags=re.I)
        out["selecao"] = re.sub(r"\s+", " ", selecao).strip()
        return out

    direcao = detectar_direcao_v28(selecao_txt) or detectar_direcao_v28(texto_analise)
    linha = extrair_linha_mercado_v28(selecao_txt)
    if linha is not None and not direcao and texto_tem(t, ["gols", "gol", "escanteios", "cartoes", "chutes"]):
        direcao = "over"

    if texto_tem(t, ["escanteio", "escanteios", "corner", "corners"]):
        out.update({"mercado": "Escanteios", "direcao": direcao or "over", "selecao": direcao or "over", "linha": linha})
        return out
    if texto_tem(t, ["cartoes", "cartões", "cards", "yellow cards", "red cards"]):
        out.update({"mercado": "Cartões", "direcao": direcao or "over", "selecao": direcao or "over", "linha": linha})
        return out
    if texto_tem(t, ["chutes a gol", "chutes no gol", "shot on target", "shots on target"]):
        out.update({"mercado": "Chutes no Gol", "direcao": direcao or ("over" if linha is not None else ""), "selecao": direcao or ("over" if linha is not None else ""), "linha": linha})
        return out
    if texto_tem(t, ["chutes", "shots", "finalizacoes", "finalizações"]):
        out.update({"mercado": "Chutes", "direcao": direcao or ("over" if linha is not None else ""), "selecao": direcao or ("over" if linha is not None else ""), "linha": linha})
        return out
    if texto_tem(t, ["gols", "gol", "goals"]) or direcao:
        out.update({"mercado": "Total de Gols" if texto_tem(t, ["gols", "gol", "goals"]) else "Total", "direcao": direcao or ("over" if linha is not None else ""), "selecao": direcao or ("over" if linha is not None else ""), "linha": linha})
        return out

    cls = classificar_aposta(selecao_txt, jogo)
    out.update({"mercado": cls.get("mercado", "Outro"), "selecao": cls.get("selecao", ""), "direcao": cls.get("direcao", ""), "linha": cls.get("linha", None), "periodo": cls.get("periodo", detectar_periodo(texto_analise))})
    return out


def dividir_itens_mercados_mesma_linha(texto):
    return juntar_descricoes_de_mercado_v28(split_inteligente_combinacao_v28(texto))


def resumir_multiplas_para_campos(itens):
    mercados, selecoes, linhas, periodos = [], [], [], []
    for it in itens:
        mercados.append(it.get("mercado", "Outro") or "Outro")
        selecoes.append(it.get("selecao", "") or it.get("direcao", "") or "-")
        linha = it.get("linha", None)
        linhas.append(str(linha).rstrip("0").rstrip(".") if isinstance(linha, float) else (str(linha) if linha is not None else "-"))
        periodos.append(it.get("periodo", "jogo inteiro") or "jogo inteiro")
    return {"mercado": " / ".join(mercados), "selecao": " / ".join(selecoes), "linha": " / ".join(linhas), "periodo": " / ".join(periodos)}


def aplicar_formatacao_multiplas_combinadas(resultado):
    aposta_txt = str(resultado.get("aposta", ""))
    jogo = resultado.get("jogo", "")
    mercados_txt = aposta_txt.split(" - ", 1)[1] if " - " in aposta_txt else aposta_txt
    itens_txt = dividir_itens_mercados_mesma_linha(mercados_txt)

    if len(itens_txt) < 2:
        item = classificar_item_combinada_visual_v28(mercados_txt, jogo)
        if item.get("mercado") != "Outro":
            resultado["mercado"] = item["mercado"]
            resultado["selecao"] = item["selecao"]
            resultado["linha"] = item["linha"]
            resultado["periodo"] = item["periodo"]
        return resultado

    itens = [classificar_item_combinada_visual_v28(x, jogo) for x in itens_txt]
    itens_validos = [i for i in itens if i.get("mercado") != "Outro"]
    if len(itens_validos) < 2:
        return resultado

    resumo = resumir_multiplas_para_campos(itens_validos)
    resultado.update({"mercado": resumo["mercado"], "selecao": resumo["selecao"], "linha": resumo["linha"], "periodo": resumo["periodo"], "direcao": "", "mercado_api": "Múltipla - Combinada"})
    resultado["itens_multipla_detalhados"] = itens_validos
    resultado["itens_multipla"] = {"jogos": [jogo] if jogo else [], "selecoes": [i.get("texto", "") for i in itens_validos], "qtd_jogos": 1 if jogo else 0, "qtd_selecoes": len(itens_validos)}
    return resultado


def validar_ht_vence_sem_sofrer_v28(aposta, resultado):
    home = resultado.get("home_team", "")
    away = resultado.get("away_team", "")
    selecao = aposta.get("selecao", "")
    ht_home = resultado.get("home_score_ht", resultado.get("home_ht_score"))
    ht_away = resultado.get("away_score_ht", resultado.get("away_ht_score"))
    if ht_home is None or ht_away is None:
        return None
    try:
        ht_home, ht_away = int(ht_home), int(ht_away)
    except:
        return None
    if nome_bate(selecao, home):
        return "ganha" if ht_home > ht_away and ht_away == 0 else "perdida"
    if nome_bate(selecao, away):
        return "ganha" if ht_away > ht_home and ht_home == 0 else "perdida"
    return None





# ============================================================
# V30 - FIX API: buscar_resultado_futebol
# Corrige NameError quando versões anteriores perderam a função.
# ============================================================

def api_headers():
    headers = {}

    if API_KEY:
        headers["x-apisports-key"] = API_KEY

    return headers


def api_get(url, params=None):
    try:
        r = requests.get(url, headers=api_headers(), params=params or {}, timeout=20)

        if r.status_code != 200:
            print("ERRO API:", r.status_code, r.text[:300])
            return None

        return r.json()

    except Exception as e:
        print("ERRO REQUEST API:", e)
        return None


def extrair_data_para_api(aposta):
    dt = parse_data(aposta.get("data", ""))

    if not dt:
        dt = datetime.now()

    return dt.strftime("%Y-%m-%d")


def normalizar_nome_api(txt):
    return normalizar_nome(txt)


def score_match_time_api(nome, team):
    nome_n = normalizar_nome_api(nome)
    team_n = normalizar_nome_api(team)

    if not nome_n or not team_n:
        return 0

    if nome_n == team_n:
        return 100

    if nome_n in team_n or team_n in nome_n:
        return 85

    ratio = difflib.SequenceMatcher(None, nome_n, team_n).ratio()
    return int(ratio * 100)


def escolher_melhor_fixture_futebol(fixtures, aposta):
    jogo = aposta.get("jogo", "")
    selecao = aposta.get("selecao", "")

    casa, fora = extrair_times_jogo(jogo)

    alvo1 = casa or selecao or jogo
    alvo2 = fora

    melhor = None
    melhor_score = -1

    for item in fixtures:
        fixture = item.get("fixture", {})
        teams = item.get("teams", {})
        goals = item.get("goals", {})
        score = item.get("score", {})

        home = teams.get("home", {}).get("name", "")
        away = teams.get("away", {}).get("name", "")

        if alvo2:
            s1 = max(score_match_time_api(alvo1, home), score_match_time_api(alvo1, away))
            s2 = max(score_match_time_api(alvo2, home), score_match_time_api(alvo2, away))
            total = s1 + s2
        else:
            total = max(
                score_match_time_api(alvo1, home),
                score_match_time_api(alvo1, away),
                score_match_time_api(selecao, home),
                score_match_time_api(selecao, away),
            )

        if total > melhor_score:
            melhor_score = total
            melhor = item

    if not melhor or melhor_score < 55:
        return None

    fixture = melhor.get("fixture", {})
    teams = melhor.get("teams", {})
    goals = melhor.get("goals", {})
    score = melhor.get("score", {})

    halftime = score.get("halftime", {}) or {}

    return {
        "fixture_id": fixture.get("id"),
        "status": (fixture.get("status", {}) or {}).get("short", ""),
        "home_team": (teams.get("home", {}) or {}).get("name", ""),
        "away_team": (teams.get("away", {}) or {}).get("name", ""),
        "home_score": goals.get("home"),
        "away_score": goals.get("away"),
        "home_score_ht": halftime.get("home"),
        "away_score_ht": halftime.get("away"),
        "raw": melhor
    }


def buscar_resultado_futebol(aposta):
    """
    Busca resultado de futebol na API-Football.
    Usa endpoint /fixtures e tenta bater pelo nome do jogo/time.
    """
    if not API_KEY:
        print("API_KEY vazia em config.json")
        return None

    data_jogo = extrair_data_para_api(aposta)

    cache_key = json.dumps({
        "data": data_jogo,
        "jogo": normalizar_nome(aposta.get("jogo", "")),
        "selecao": normalizar_nome(aposta.get("selecao", ""))
    }, ensure_ascii=False)

    if cache_key in CACHE_RESULTADOS:
        return CACHE_RESULTADOS[cache_key]

    url = "https://v3.football.api-sports.io/fixtures"
    params = {"date": data_jogo}

    js = api_get(url, params)

    if not js:
        return None

    fixtures = js.get("response", [])

    if not fixtures:
        return None

    resultado = escolher_melhor_fixture_futebol(fixtures, aposta)

    if resultado:
        CACHE_RESULTADOS[cache_key] = resultado

    return resultado





# ============================================================
# V31 - FIX API: validar_aposta_com_resultado
# ============================================================

def validar_moneyline_resultado(aposta, resultado):
    selecao = aposta.get("selecao", "") or aposta.get("aposta", "")
    home = resultado.get("home_team", "")
    away = resultado.get("away_team", "")
    hs = resultado.get("home_score")
    aw = resultado.get("away_score")

    if hs is None or aw is None:
        return None

    if normalizar_nome(selecao) in ["empate", "draw", "x"]:
        return "ganha" if hs == aw else "perdida"

    if nome_bate(selecao, home):
        return "ganha" if hs > aw else "perdida"

    if nome_bate(selecao, away):
        return "ganha" if aw > hs else "perdida"

    return None


def validar_total_gols_resultado(aposta, resultado):
    direcao = aposta.get("direcao", "") or aposta.get("selecao", "")
    linha = aposta.get("linha", None)

    if linha in ["", "-", None]:
        linha = extrair_linha(aposta.get("aposta", ""))

    try:
        linha = float(linha)
    except:
        return None

    hs = resultado.get("home_score")
    aw = resultado.get("away_score")

    if hs is None or aw is None:
        return None

    total = float(hs) + float(aw)

    if direcao == "over":
        if total > linha:
            return "ganha"
        if total < linha:
            return "perdida"
        return "anulada"

    if direcao == "under":
        if total < linha:
            return "ganha"
        if total > linha:
            return "perdida"
        return "anulada"

    return None


def validar_btts_resultado(aposta, resultado):
    resposta = aposta.get("btts_resposta", "") or aposta.get("selecao", "") or detectar_btts_resposta_aposta(aposta)
    hs = resultado.get("home_score")
    aw = resultado.get("away_score")

    if hs is None or aw is None:
        return None

    ambos = int(hs) > 0 and int(aw) > 0

    if resposta == "sim":
        return "ganha" if ambos else "perdida"

    if resposta == "nao":
        return "ganha" if not ambos else "perdida"

    return None


def validar_dupla_chance_resultado(aposta, resultado):
    selecao = aposta.get("selecao", "")
    hs = resultado.get("home_score")
    aw = resultado.get("away_score")

    if hs is None or aw is None:
        return None

    casa_ganha = hs > aw
    fora_ganha = aw > hs
    empate = hs == aw
    s = normalizar_nome(selecao)

    if s == "1x":
        return "ganha" if casa_ganha or empate else "perdida"

    if s == "x2":
        return "ganha" if fora_ganha or empate else "perdida"

    if s == "12":
        return "ganha" if casa_ganha or fora_ganha else "perdida"

    return None


def validar_ht_resultado(aposta, resultado):
    mercado = aposta.get("mercado", "")
    selecao = aposta.get("selecao", "")
    home = resultado.get("home_team", "")
    away = resultado.get("away_team", "")

    ht_home = resultado.get("home_score_ht", resultado.get("home_ht_score"))
    ht_away = resultado.get("away_score_ht", resultado.get("away_ht_score"))

    if ht_home is None or ht_away is None:
        return None

    try:
        ht_home = int(ht_home)
        ht_away = int(ht_away)
    except:
        return None

    if mercado == "HT Resultado":
        if normalizar_nome(selecao) in ["sim", "yes"]:
            return "ganha" if ht_home != ht_away else "perdida"

        if nome_bate(selecao, home):
            return "ganha" if ht_home > ht_away else "perdida"

        if nome_bate(selecao, away):
            return "ganha" if ht_away > ht_home else "perdida"

    if mercado == "HT Vence sem sofrer":
        if nome_bate(selecao, home):
            return "ganha" if ht_home > ht_away and ht_away == 0 else "perdida"

        if nome_bate(selecao, away):
            return "ganha" if ht_away > ht_home and ht_home == 0 else "perdida"

    return None


def validar_aposta_com_resultado(aposta, resultado):
    mercado = aposta.get("mercado", "")
    texto = " ".join([
        str(aposta.get("aposta", "")),
        str(aposta.get("mercado", "")),
        str(aposta.get("selecao", "")),
    ])
    t = normalizar_nome(texto)

    # Sem estatísticas no endpoint básico: não marca errado.
    if mercado in ["Escanteios", "Cartões", "Chutes", "Chutes no Gol", "Marcador", "Assistência"]:
        return None

    if mercado in ["HT Resultado", "HT Vence sem sofrer"]:
        return validar_ht_resultado(aposta, resultado)

    if mercado == "Ambas Marcam" or eh_texto_btts(texto):
        return validar_btts_resultado(aposta, resultado)

    if mercado == "Dupla Chance":
        return validar_dupla_chance_resultado(aposta, resultado)

    if mercado in ["Total", "Total de Gols", "Pontos"] or (
        aposta.get("direcao") in ["over", "under"] and texto_tem(t, ["gols", "gol", "goals"])
    ):
        return validar_total_gols_resultado(aposta, resultado)

    if mercado == "Moneyline" or texto_tem(t, ["moneyline", "resultado final", "vence", "vencem", "ml"]):
        return validar_moneyline_resultado(aposta, resultado)

    return None




# ============================================================
# V32 - API: MERCADOS ESTATÍSTICOS + MÚLTIPLAS
# Valida quando a API retorna estatísticas:
# - Escanteios
# - Cartões
# - Chutes
# - Chutes no Gol
# Continua validando:
# - Moneyline
# - Total de Gols
# - BTTS
# - Dupla Chance
# - HT Resultado / HT vence sem sofrer
# ============================================================

def api_get_fixture_statistics_v32(fixture_id):
    if not fixture_id or not API_KEY:
        return None

    cache_key = f"stats_{fixture_id}"

    if cache_key in CACHE_ESTATISTICAS:
        return CACHE_ESTATISTICAS[cache_key]

    url = "https://v3.football.api-sports.io/fixtures/statistics"
    js = api_get(url, {"fixture": fixture_id})

    if not js:
        return None

    stats = js.get("response", [])

    CACHE_ESTATISTICAS[cache_key] = stats
    return stats


def normalizar_stat_value_v32(valor):
    if valor is None:
        return 0

    if isinstance(valor, (int, float)):
        return float(valor)

    s = str(valor).strip()

    if s.endswith("%"):
        s = s[:-1]

    s = s.replace(",", ".")

    m = re.search(r"-?\d+(?:\.\d+)?", s)

    if not m:
        return 0

    try:
        return float(m.group(0))
    except:
        return 0


def pegar_stat_total_v32(resultado, nomes):
    stats = resultado.get("statistics")

    if stats is None:
        stats = api_get_fixture_statistics_v32(resultado.get("fixture_id"))
        resultado["statistics"] = stats

    if not stats:
        return None

    total = 0
    achou = False

    nomes_norm = [normalizar_nome(n) for n in nomes]

    for team_block in stats:
        for st in team_block.get("statistics", []) or []:
            tipo = normalizar_nome(st.get("type", ""))

            if any(n in tipo or tipo in n for n in nomes_norm):
                total += normalizar_stat_value_v32(st.get("value"))
                achou = True

    return total if achou else None


def validar_over_under_valor_v32(valor, linha, direcao):
    if valor is None or linha in [None, "", "-"] or not direcao:
        return None

    try:
        valor = float(valor)
        linha = float(linha)
    except:
        return None

    if direcao == "over":
        if valor > linha:
            return "ganha"
        if valor < linha:
            return "perdida"
        return "anulada"

    if direcao == "under":
        if valor < linha:
            return "ganha"
        if valor > linha:
            return "perdida"
        return "anulada"

    return None


def validar_escanteios_resultado_v32(aposta, resultado):
    direcao = aposta.get("direcao", "") or aposta.get("selecao", "")
    linha = aposta.get("linha", None)

    if linha in [None, "", "-"]:
        linha = extrair_linha(aposta.get("aposta", ""))

    total = pegar_stat_total_v32(resultado, [
        "Corner Kicks", "Corners", "Escanteios", "Total Corners"
    ])

    return validar_over_under_valor_v32(total, linha, direcao)


def validar_cartoes_resultado_v32(aposta, resultado):
    direcao = aposta.get("direcao", "") or aposta.get("selecao", "")
    linha = aposta.get("linha", None)

    if linha in [None, "", "-"]:
        linha = extrair_linha(aposta.get("aposta", ""))

    amarelos = pegar_stat_total_v32(resultado, ["Yellow Cards"])
    vermelhos = pegar_stat_total_v32(resultado, ["Red Cards"])

    if amarelos is None and vermelhos is None:
        total = pegar_stat_total_v32(resultado, ["Cards", "Cartões", "Cartoes"])
    else:
        total = (amarelos or 0) + (vermelhos or 0)

    return validar_over_under_valor_v32(total, linha, direcao)


def validar_chutes_resultado_v32(aposta, resultado):
    direcao = aposta.get("direcao", "") or aposta.get("selecao", "")
    linha = aposta.get("linha", None)

    if linha in [None, "", "-"]:
        linha = extrair_linha(aposta.get("aposta", ""))

    total = pegar_stat_total_v32(resultado, [
        "Total Shots", "Shots", "Chutes", "Finalizações", "Finalizacoes"
    ])

    return validar_over_under_valor_v32(total, linha, direcao)


def validar_chutes_gol_resultado_v32(aposta, resultado):
    direcao = aposta.get("direcao", "") or aposta.get("selecao", "")
    linha = aposta.get("linha", None)

    if linha in [None, "", "-"]:
        linha = extrair_linha(aposta.get("aposta", ""))

    total = pegar_stat_total_v32(resultado, [
        "Shots on Goal", "Shots on Target", "Chutes no Gol", "Chutes a Gol"
    ])

    return validar_over_under_valor_v32(total, linha, direcao)


def validar_aposta_com_resultado(aposta, resultado):
    mercado = aposta.get("mercado", "")
    texto = " ".join([
        str(aposta.get("aposta", "")),
        str(aposta.get("mercado", "")),
        str(aposta.get("selecao", "")),
    ])
    t = normalizar_nome(texto)

    if mercado == "Escanteios":
        return validar_escanteios_resultado_v32(aposta, resultado)

    if mercado == "Cartões":
        return validar_cartoes_resultado_v32(aposta, resultado)

    if mercado == "Chutes":
        return validar_chutes_resultado_v32(aposta, resultado)

    if mercado == "Chutes no Gol":
        return validar_chutes_gol_resultado_v32(aposta, resultado)

    # Jogador/marcador/assistência precisam de endpoint de eventos/estatísticas de jogador.
    # Para não marcar errado, ficam pendentes quando não houver função específica.
    if mercado in ["Marcador", "Assistência", "Jogador Chutes", "Jogador Chutes no Gol"]:
        return None

    if mercado in ["HT Resultado", "HT Vence sem sofrer"]:
        return validar_ht_resultado(aposta, resultado)

    if mercado == "Ambas Marcam" or eh_texto_btts(texto):
        return validar_btts_resultado(aposta, resultado)

    if mercado == "Dupla Chance":
        return validar_dupla_chance_resultado(aposta, resultado)

    if mercado in ["Total", "Total de Gols", "Pontos"] or (
        aposta.get("direcao") in ["over", "under"] and texto_tem(t, ["gols", "gol", "goals"])
    ):
        return validar_total_gols_resultado(aposta, resultado)

    if mercado == "Moneyline" or texto_tem(t, ["moneyline", "resultado final", "vence", "vencem", "ml"]):
        return validar_moneyline_resultado(aposta, resultado)

    return None


def validar_item_multipla_universal(item_aposta):
    if normalizar_nome(item_aposta.get("esporte", "Futebol")) != "futebol":
        return None, "ignorado: não é futebol"

    resultado = buscar_resultado_futebol(item_aposta)

    if not resultado:
        return None, "resultado não encontrado"

    if resultado.get("status") not in ["FT", "AET", "PEN"]:
        return None, "jogo ainda não finalizado"

    status = validar_aposta_com_resultado(item_aposta, resultado)

    if status:
        return status, "validado"

    return None, "mercado não validado ou estatística indisponível"


def atualizar_resultados_api():
    atualizadas = 0
    ignoradas = 0

    for b in bets_do_usuario():
        if b.get("estado") != "":
            continue

        aposta_validacao = preparar_aposta_para_validacao(b)
        mercado = str(aposta_validacao.get("mercado", ""))

        if mercado.startswith("Múltipla") or "/" in mercado or aposta_validacao.get("mercado_api", "").startswith("Múltipla"):
            status_multi, detalhe_multi = validar_multipla_universal_api(aposta_validacao)

            if status_multi:
                atualizar_resultado_saldo(b, status_multi)
                b["api_status"] = "múltipla atualizada pela API: " + detalhe_multi
                atualizadas += 1
                continue

            b["api_status"] = "múltipla não validada automaticamente: " + str(detalhe_multi)
            ignoradas += 1
            continue

        if normalizar_nome(aposta_validacao.get("esporte", "")) != "futebol":
            b["api_status"] = "ignorado: não é futebol"
            ignoradas += 1
            continue

        resultado = buscar_resultado_futebol(aposta_validacao)

        if not resultado:
            b["api_status"] = "resultado não encontrado"
            ignoradas += 1
            continue

        if resultado.get("status") not in ["FT", "AET", "PEN"]:
            b["api_status"] = "jogo ainda não finalizado"
            ignoradas += 1
            continue

        status = validar_aposta_com_resultado(aposta_validacao, resultado)

        if status:
            atualizar_resultado_saldo(b, status)
            b["api_status"] = "atualizado pela API"
            atualizadas += 1
        else:
            b["api_status"] = "mercado não validado"
            ignoradas += 1

    salvar()
    return atualizadas, ignoradas





# ============================================================
# V29 - PLANILHA + EMOJIS + ABREVIAÇÕES DE CASAS
# - Remove emojis/ícones no começo das linhas e no meio do OCR.
# - u2.5 / U 2.5 = under 2.5
# - o2.5 / O 2.5 = over 2.5
# - ML Wolfsburg e u2.5 gols = Moneyline / Total de Gols
# - Over 4.5 gols e 4.5 cards = Total de Gols / Cartões
# ============================================================

def remover_emojis(texto):
    s = str(texto or "")
    saida = []

    for ch in s:
        o = ord(ch)
        cat = unicodedata.category(ch)

        # remove emojis, pictogramas, variation selectors e símbolos decorativos
        if (
            cat.startswith("So")
            or 0x1F000 <= o <= 0x1FAFF
            or 0x2600 <= o <= 0x27BF
            or 0xFE00 <= o <= 0xFE0F
            or 0x200D == o
        ):
            continue

        saida.append(ch)

    s = "".join(saida)

    # remove ícones soltos/ruídos comuns no começo de linha
    s = re.sub(r"^[^\wÀ-ÿ\d]+", "", s)
    s = re.sub(r"[^\w\sÀ-ÿ.,:%/+\-$xX&º°]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalizar_abreviacoes_mercado_v29(texto):
    s = str(texto or "")

    # u2.5 / u 2.5 / U2,5 = under 2.5
    s = re.sub(r"\b[uU]\s*(\d+(?:[,.]\d+)?)", r"under \1", s)

    # o2.5 / o 2.5 / O2,5 = over 2.5
    s = re.sub(r"\b[oO]\s*(\d+(?:[,.]\d+)?)", r"over \1", s)

    # 3+ gols / 10+ esc / 5+ cards continuam, mas padroniza abreviações.
    trocas = [
        (r"\bescs?\b", "escanteios"),
        (r"\bcantos?\b", "escanteios"),
        (r"\bcorners?\b", "escanteios"),
        (r"\bcards?\b", "cartoes"),
        (r"\bcart(ao|ão|oes|ões)\b", "cartoes"),
        (r"\bdc\b", "dupla chance"),
        (r"\bbtts\b", "ambas marcam"),
        (r"\bambos os times marcarem\b", "ambas marcam"),
        (r"\bpara ambos os times marcarem\b", "ambas marcam"),
    ]

    for rgx, rep in trocas:
        s = re.sub(rgx, rep, s, flags=re.I)

    s = re.sub(r"\s+", " ", s).strip()
    return s


def expandir_abreviacoes_v28(texto):
    return normalizar_abreviacoes_mercado_v29(texto)


def split_inteligente_combinacao_v28(texto):
    s = normalizar_abreviacoes_mercado_v29(limpar_linha(texto))
    s = re.sub(r"\b(futebol)\b", " ", s, flags=re.I)
    s = re.sub(r"R\$\s*\d+[,.]?\d*", " ", s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip(" /-|")

    # Protege "dupla chance Inter ou Flu HT" para não quebrar no "ou".
    direcao_global = detectar_direcao_v28(s) if "detectar_direcao_v28" in globals() else detectar_direcao(s)

    partes = re.split(r"\s*(?:/|,|;|\+|\s+e\s+|\s+and\s+)\s*", s, flags=re.I)
    partes = [normalizar_abreviacoes_mercado_v29(p).strip(" /-|") for p in partes if p.strip(" /-|")]

    saida = []

    for p in partes:
        n = normalizar_nome(p)

        # "ML Wolfsburg" é item próprio.
        if re.search(r"\bML\b", p, flags=re.I):
            saida.append(p)
            continue

        # "4.5 cartoes", "10.5 escanteios", "3 gols" sem direção herda over.
        if re.search(r"\d+(?:[,.]\d+)?", p) and not detectar_direcao_v28(p):
            if texto_tem(n, ["gols", "gol", "escanteios", "cartoes", "chutes"]):
                p = (direcao_global or "over") + " " + p

        saida.append(p)

    if len(saida) <= 1:
        tokens = []

        # ML + time
        for m in re.finditer(r"\bML\s+([A-Za-zÀ-ÿ'.\- ]{2,})(?=$|\s+(?:e|and|,|/)|\s+over|\s+under)", s, flags=re.I):
            tok = "ML " + m.group(1).strip()
            if tok not in tokens:
                tokens.append(tok)

        patterns = [
            r"(?:over|under|mais de|menos de)?\s*\d+(?:[,.]\d+)?\+?\s*(?:gols?|goals?)",
            r"(?:over|under|mais de|menos de)?\s*\d+(?:[,.]\d+)?\+?\s*(?:escanteios?)",
            r"(?:over|under|mais de|menos de)?\s*\d+(?:[,.]\d+)?\+?\s*(?:cartoes)",
            r"(?:over|under|mais de|menos de)?\s*\d+(?:[,.]\d+)?\+?\s*(?:chutes(?: a gol| no gol)?|shots(?: on target)?)",
        ]

        for pat in patterns:
            for m in re.finditer(pat, s, flags=re.I):
                tok = m.group(0).strip()
                if tok and tok not in tokens:
                    if not detectar_direcao_v28(tok):
                        tok = (direcao_global or "over") + " " + tok
                    tokens.append(tok)

        if eh_texto_btts(s):
            tokens.append("ambas marcam")

        for m in re.finditer(r"([A-Za-zÀ-ÿ'.\- ]{3,})\s+anytime\b", s, flags=re.I):
            tok = m.group(0).strip()
            if tok not in tokens:
                tokens.append(tok)

        if len(tokens) > 1:
            saida = tokens

    final = []
    vistos = set()

    for p in saida:
        p = re.sub(r"\s+", " ", p).strip(" /-|")
        n = normalizar_nome(p)

        if p and n not in vistos:
            vistos.add(n)
            final.append(p)

    return final


def classificar_item_combinada_visual_v28(item, jogo=""):
    item_original = normalizar_abreviacoes_mercado_v29(limpar_linha(item))
    selecao_txt = item_original
    descricao_txt = ""

    if " | " in item_original:
        selecao_txt, descricao_txt = [x.strip() for x in item_original.split(" | ", 1)]

    texto_analise = (selecao_txt + " " + descricao_txt).strip()
    t = normalizar_nome(texto_analise)

    out = {
        "texto": selecao_txt,
        "descricao_mercado": descricao_txt,
        "mercado": "Outro",
        "selecao": "",
        "direcao": "",
        "linha": None,
        "periodo": detectar_periodo(texto_analise)
    }

    if not selecao_txt:
        return out

    if texto_tem(t, ["vence de 0 o ht", "vence de zero o ht", "vence sem sofrer o ht", "vence de 0 no ht"]):
        out["mercado"] = "HT Vence sem sofrer"
        out["periodo"] = "1º tempo"
        out["selecao"] = re.sub(r"\b(vence de 0 o ht|vence de zero o ht|vence sem sofrer o ht|vence de 0 no ht|ht)\b", "", selecao_txt, flags=re.I).strip()
        return out

    if texto_tem(t, ["algum time vence ht", "algum time vence o ht", "algum time vence 1 tempo", "algum time vence primeiro tempo"]):
        out["mercado"] = "HT Resultado"
        out["selecao"] = "sim"
        out["periodo"] = "1º tempo"
        return out

    if eh_texto_btts(texto_analise):
        out["mercado"] = "Ambas Marcam"
        out["selecao"] = detectar_btts_resposta(texto_analise) or "sim"
        return out

    if texto_tem(t, ["anytime", "a qualquer momento", "to score"]):
        out["mercado"] = "Marcador"
        out["selecao"] = limpar_nome_marcador_anytime_v28(selecao_txt) if "limpar_nome_marcador_anytime_v28" in globals() else limpar_nome_jogador(selecao_txt)
        return out

    if texto_tem(t, ["dupla chance"]):
        out["mercado"] = "Dupla Chance"
        out["periodo"] = "1º tempo" if texto_tem(t, ["ht", "1 tempo", "primeiro tempo"]) else "jogo inteiro"
        txt = re.sub(r"\b(dupla chance|dc|ht|1[ºo]?\s*tempo|primeiro tempo)\b", " ", selecao_txt, flags=re.I)
        txt = re.sub(r"\s+", " ", txt).strip()
        out["selecao"] = detectar_dupla_chance_selecao(txt) or txt
        return out

    if re.search(r"\bML\b", selecao_txt, flags=re.I) or texto_tem(t, ["moneyline", "vence", "vencem", "para vencer"]):
        out["mercado"] = "Moneyline"
        selecao = re.sub(r"\b(ML|moneyline|vence|vencem|vencer|vencerem|para vencer|ganha|ganham)\b", " ", selecao_txt, flags=re.I)
        out["selecao"] = re.sub(r"\s+", " ", selecao).strip()
        return out

    direcao = detectar_direcao_v28(selecao_txt) if "detectar_direcao_v28" in globals() else detectar_direcao(selecao_txt)
    linha = extrair_linha_mercado_v28(selecao_txt) if "extrair_linha_mercado_v28" in globals() else extrair_linha(selecao_txt)

    if linha is not None and not direcao and texto_tem(t, ["gols", "gol", "escanteios", "cartoes", "chutes"]):
        direcao = "over"

    if texto_tem(t, ["escanteio", "escanteios"]):
        out.update({"mercado": "Escanteios", "direcao": direcao or "over", "selecao": direcao or "over", "linha": linha})
        return out

    if texto_tem(t, ["cartoes", "cartões", "cards"]):
        out.update({"mercado": "Cartões", "direcao": direcao or "over", "selecao": direcao or "over", "linha": linha})
        return out

    if texto_tem(t, ["chutes a gol", "chutes no gol", "shot on target", "shots on target"]):
        out.update({"mercado": "Chutes no Gol", "direcao": direcao or ("over" if linha is not None else ""), "selecao": direcao or ("over" if linha is not None else ""), "linha": linha})
        return out

    if texto_tem(t, ["chutes", "shots", "finalizacoes", "finalizações"]):
        out.update({"mercado": "Chutes", "direcao": direcao or ("over" if linha is not None else ""), "selecao": direcao or ("over" if linha is not None else ""), "linha": linha})
        return out

    if texto_tem(t, ["gols", "gol", "goals"]) or direcao:
        out.update({"mercado": "Total de Gols" if texto_tem(t, ["gols", "gol", "goals"]) else "Total", "direcao": direcao or ("over" if linha is not None else ""), "selecao": direcao or ("over" if linha is not None else ""), "linha": linha})
        return out

    cls = classificar_aposta(selecao_txt, jogo)
    out.update({
        "mercado": cls.get("mercado", "Outro"),
        "selecao": cls.get("selecao", ""),
        "direcao": cls.get("direcao", ""),
        "linha": cls.get("linha", None),
        "periodo": cls.get("periodo", detectar_periodo(texto_analise))
    })
    return out





# ============================================================
# V35 - Feed de últimas apostas da comunidade
# ============================================================

@app.route("/ultimas_apostas")
@login_required
def ultimas_apostas():
    exemplos = [
        {"casa":"Superbet","esporte":"Futebol","jogo":"Manchester City x Arsenal","aposta":"Man City ML, over 2.5 gols e Haaland anytime","odd":3.20,"valor":50.00},
        {"casa":"Esportiva","esporte":"Futebol","jogo":"Internacional x Fluminense","aposta":"10+ esc, 5+ cartoes, DC Inter ou Flu HT","odd":5.75,"valor":23.00},
        {"casa":"Betbra","esporte":"Futebol","jogo":"Freiburg x Wolfsburg","aposta":"ML Wolfsburg e u2.5 gols","odd":8.62,"valor":38.00},
        {"casa":"Lottu","esporte":"Futebol","jogo":"Aston Villa x Tottenham / Lyon x Rennes / Inter x Parma","aposta":"Aston Villa, Lyon e Inter de Milão vencem","odd":7.40,"valor":35.00},
        {"casa":"Betano","esporte":"Futebol","jogo":"Chapecoense x Bragantino","aposta":"Bragantino vence de 0 o HT","odd":3.50,"valor":103.00}
    ]

    ultimas = ultimas_apostas_comunidade_base(8)

    for ex in exemplos:
        if len(ultimas) >= 10:
            break
        ultimas.append(ex)

    return jsonify(ultimas[:10])





# ============================================================
# V42 - Rotas da página de saldos por casa
# ============================================================

@app.route("/saldos")
@login_required
@assinatura_required
def saldos():
    saldos = [
        {"casa": casa, "saldo": float(valor or 0)}
        for casa, valor in sorted(saldo_casas_usuario().items(), key=lambda x: x[0].lower())
    ]

    return render_template(
        "saldos.html",
        saldos=saldos,
        total_saldos=total_saldos_casas(),
        casas=CASAS_DISPONIVEIS,
        movimentacoes=list(reversed(movimentacoes_usuario()))[:80]
    )


@app.route("/saldos/salvar", methods=["POST"])
@login_required
@assinatura_required
def salvar_saldo_casa():
    casa = limpar_casa(request.form.get("casa", ""))
    saldo = float(request.form.get("saldo", 0) or 0)

    if casa:
        set_saldo_casa(casa, saldo)
        salvar()

    return redirect("/saldos")



@app.route("/saldos/movimento", methods=["POST"])
@assinatura_required
def saldo_movimento():
    casa = request.form.get("casa", "")
    destino = request.form.get("destino", "")
    tipo = request.form.get("tipo", "deposito")
    valor = float(request.form.get("valor", 0) or 0)

    aplicar_movimento_manual_casa(casa, tipo, valor, destino)
    salvar()

    return redirect("/saldos")


@app.route("/saldos/remover/<path:casa>")
@login_required
@assinatura_required
def remover_saldo_casa(casa):
    chave = encontrar_chave_saldo_casa(casa)

    if chave in saldo_casas_usuario():
        del saldo_casas_usuario()[chave]
        salvar()

    return redirect("/saldos")




@app.route("/admin/assinatura/<uid>")
@admin_required
def admin_assinatura(uid):
    usuarios = carregar_usuarios()

    for u in usuarios.get("users", []):
        if u.get("id") == uid:
            u["assinatura_ativa"] = not u.get("assinatura_ativa", False)
            if u.get("assinatura_ativa"):
                u["plano"] = "pro"
            elif not u.get("is_admin"):
                u["plano"] = "free"
            break

    salvar_usuarios(usuarios)
    return redirect("/admin")


@app.route("/admin/plano/<uid>/<plano>")
@admin_required
def admin_plano(uid, plano):
    if plano not in ["free", "pro", "premium", "admin"]:
        plano = "free"

    usuarios = carregar_usuarios()

    for u in usuarios.get("users", []):
        if u.get("id") == uid:
            u["plano"] = plano
            u["assinatura_ativa"] = plano in ["pro", "premium", "admin"]
            break

    salvar_usuarios(usuarios)
    return redirect("/admin")




@app.route("/configuracoes", methods=["GET", "POST"])
@login_required
def configuracoes():
    usuarios = carregar_usuarios()
    uid = usuario_id_atual() if "usuario_id_atual" in globals() else session.get("user_id")
    user = None

    for u in usuarios.get("users", []):
        if u.get("id") == uid:
            user = u
            break

    if not user:
        return redirect("/login")

    ok = ""
    erro = ""

    if request.method == "POST":
        acao = request.form.get("acao", "preferencias")

        if acao == "perfil":
            nome = request.form.get("nome", "").strip()
            if not nome:
                erro = "Informe um nome válido."
            else:
                user["nome"] = nome
                salvar_usuarios(usuarios)
                ok = "Perfil atualizado."

        elif acao == "senha":
            atual = request.form.get("senha_atual", "")
            nova = request.form.get("nova_senha", "")
            confirmar = request.form.get("confirmar_senha", "")

            if not check_password_hash(user.get("senha_hash", ""), atual):
                erro = "Senha atual incorreta."
            elif len(nova) < 6:
                erro = "A nova senha precisa ter pelo menos 6 caracteres."
            elif nova != confirmar:
                erro = "A confirmação da senha não confere."
            else:
                user["senha_hash"] = generate_password_hash(nova)
                salvar_usuarios(usuarios)
                ok = "Senha alterada com sucesso."

        else:
            user["apostas_publicas_padrao"] = request.form.get("apostas_publicas_padrao") == "on"
            salvar_usuarios(usuarios)
            ok = "Configurações salvas."

    return render_template("configuracoes.html", user=user, ok=ok, erro=erro)


@app.route("/calculadora")
@login_required
@assinatura_required
def calculadora():
    return render_template("calculadora.html", casas=CASAS_DISPONIVEIS)




@app.route("/calculadora/planilhar", methods=["POST"])
@login_required
@assinatura_required
def calculadora_planilhar():
    payload = request.get_json(silent=True) or {}
    apostas = payload.get("apostas", [])

    salvas = 0

    for a in apostas:
        try:
            casa = limpar_casa(a.get("casa", ""))
            selecao = limpar_linha(a.get("selecao", ""))
            jogo = limpar_linha(a.get("jogo", "Calculadora de Arbitragem"))
            odd = float(a.get("odd", 0) or 0)
            valor = float(a.get("valor", 0) or 0)

            if not casa or not selecao or odd <= 1 or valor <= 0:
                continue

            aposta_texto = limpar_linha(a.get("aposta", selecao))
            classificacao = classificar_aposta(aposta_texto, jogo)

            bet = {
                "id": str(uuid.uuid4()),
                "user_id": usuario_id_atual(),
                "data": datetime.now().strftime("%d/%m/%Y %H:%M"),
                "aposta": aposta_texto,
                "casa": casa,
                "esporte": limpar_linha(a.get("esporte", "Arbitragem")),
                "jogo": jogo,
                "odd": odd,
                "valor": valor,
                "estado": "",
                "lucro": 0,
                "origem": "calculadora",
                "mercado": classificacao.get("mercado", "Arbitragem"),
                "direcao": classificacao.get("direcao", ""),
                "linha": classificacao.get("linha", None),
                "periodo": classificacao.get("periodo", "jogo inteiro"),
                "selecao": classificacao.get("selecao", selecao),
                "btts_resposta": classificacao.get("btts_resposta", ""),
                "api_status": "Calculadora",
                "texto_bruto": "",
                "texto_interpretado": "",
                "itens_multipla": {},
                "itens_multipla_detalhados": [],
                "saldo_debitado": False,
                "saldo_creditado_estado": "",
                "saldo_creditado_valor": 0.0,
                "publica": False
            }

            registrar_nova_aposta_saldo(bet)
            dados["bets"].append(bet)
            salvas += 1

        except Exception as e:
            print("ERRO PLANILHAR CALCULADORA:", e)

    salvar()
    return jsonify({"ok": True, "salvas": salvas})



# ============================================================
# V61 - OVERRIDES FINAIS DE ISOLAMENTO
# ============================================================

def bets_do_usuario():
    return bets_do_usuario_v61()


def buscar_aposta(bet_id):
    return buscar_aposta_segura_v61(bet_id)


def saldo_casas_usuario():
    return saldo_casas_usuario_v61()


def movimentacoes_usuario():
    return movimentacoes_usuario_v61()


def total_saldos_casas():
    return total_saldos_casas_v61()


def ultimas_apostas_comunidade_base(limit=10):
    saida = []
    for b in list(reversed(dados.get("bets", []))):
        if len(saida) >= limit:
            break
        if not b.get("publica", False) or not b.get("user_id"):
            continue
        bd = limpar_aposta_display_v39(b) if "limpar_aposta_display_v39" in globals() else dict(b)
        saida.append({
            "id": bd.get("id", ""),
            "data": bd.get("data", ""),
            "casa": bd.get("casa", ""),
            "esporte": bd.get("esporte", ""),
            "jogo": bd.get("jogo", ""),
            "aposta": bd.get("aposta_display") or bd.get("aposta", ""),
            "odd": bd.get("odd", ""),
            "valor": bd.get("valor", "")
        })
    return saida


if __name__ == "__main__":
    app.run(debug=True)