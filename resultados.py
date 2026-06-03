# -*- coding: utf-8 -*-
"""
Resolucao automatica de apostas (Bet Manager) — logica LIMPA e TESTAVEL.

Substitui o emaranhado duplicado de validar_aposta_com_resultado/validar_*
espalhado pelo app.py (havia ~1800 linhas de codigo morto, funcoes definidas
2-4 vezes).

Cada validador e' uma FUNCAO PURA: recebe `aposta` (dict) e `resultado` (dict)
e devolve o estado da aposta:
    "ganha" | "perdida" | "anulada" | None  (None = nao da' pra resolver ainda)

Isso permite testar com placares reais (test_resultados.py) e pegar resolucoes
erradas sem precisar de banco nem da API.

Formato esperado de `resultado` (montado a partir da API-Football):
    {
      "status": "FT"|"AET"|"PEN"|...,
      "home_team", "away_team": str,
      "home_score", "away_score": int (placar final),
      "home_score_ht", "away_score_ht": int|None (placar do 1o tempo),
      "stats": {                      # opcional, p/ escanteios/cartoes/chutes
         "home_corners","away_corners","home_cards","away_cards",
         "home_shots","away_shots","home_shots_on","away_shots_on": int
      }
    }

Formato de `aposta`:
    {"mercado", "selecao", "direcao"("over"/"under"), "linha", "aposta"(texto),
     "btts_resposta", "esporte"}
"""
import re
import unicodedata

JOGO_ENCERRADO = ("FT", "AET", "PEN")


# ============================================================
# Helpers puros (replicados do app.py, sem dependencias externas)
# ============================================================

def normalizar_nome(texto):
    texto = str(texto or "").lower()
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(ch for ch in texto if unicodedata.category(ch) != "Mn")
    texto = re.sub(r"[^a-z0-9\s]", "", texto)
    return re.sub(r"\s+", " ", texto).strip()


def nome_bate(a, b):
    a, b = normalizar_nome(a), normalizar_nome(b)
    if not a or not b:
        return False
    return a in b or b in a


def extrair_linha(texto):
    s = str(texto or "").lower().replace(",", ".")
    m = re.search(r"-?\d+(\.\d+)?", s)
    return float(m.group(0)) if m else None


def _num(v):
    """Converte para float com seguranca; devolve None se nao der."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _placar(resultado):
    return _num(resultado.get("home_score")), _num(resultado.get("away_score"))


# ============================================================
# Validadores por mercado (funcoes puras)
# ============================================================

def validar_moneyline(aposta, resultado):
    """1X2 / vencedor. selecao = time ou empate."""
    selecao = aposta.get("selecao") or aposta.get("aposta") or ""
    hs, aw = _placar(resultado)
    if hs is None or aw is None:
        return None
    if normalizar_nome(selecao) in ("empate", "draw", "x"):
        return "ganha" if hs == aw else "perdida"
    if nome_bate(selecao, resultado.get("home_team", "")):
        return "ganha" if hs > aw else "perdida"
    if nome_bate(selecao, resultado.get("away_team", "")):
        return "ganha" if aw > hs else "perdida"
    return None


def validar_total_gols(aposta, resultado):
    """Over/Under de gols. anulada quando total == linha (push)."""
    direcao = (aposta.get("direcao") or aposta.get("selecao") or "").lower()
    linha = aposta.get("linha")
    if linha in ("", "-", None):
        linha = extrair_linha(aposta.get("aposta", ""))
    linha = _num(linha)
    hs, aw = _placar(resultado)
    if linha is None or hs is None or aw is None:
        return None
    total = hs + aw
    return _over_under(total, linha, direcao)


def _over_under(valor, linha, direcao):
    """Resolve over/under de um valor numerico contra a linha."""
    if direcao not in ("over", "under"):
        return None
    if valor == linha:
        return "anulada"
    if direcao == "over":
        return "ganha" if valor > linha else "perdida"
    return "ganha" if valor < linha else "perdida"


def validar_btts(aposta, resultado):
    """Ambas marcam (sim/nao)."""
    resposta = normalizar_nome(aposta.get("btts_resposta") or aposta.get("selecao") or "")
    hs, aw = _placar(resultado)
    if hs is None or aw is None:
        return None
    ambos = hs > 0 and aw > 0
    if resposta in ("sim", "yes"):
        return "ganha" if ambos else "perdida"
    if resposta in ("nao", "no"):
        return "ganha" if not ambos else "perdida"
    return None


def validar_dupla_chance(aposta, resultado):
    """Dupla chance: 1X / X2 / 12."""
    hs, aw = _placar(resultado)
    if hs is None or aw is None:
        return None
    casa, fora, empate = hs > aw, aw > hs, hs == aw
    s = normalizar_nome(aposta.get("selecao", "")).replace(" ", "")
    if s == "1x":
        return "ganha" if casa or empate else "perdida"
    if s == "x2":
        return "ganha" if fora or empate else "perdida"
    if s in ("12", "1ou2"):
        return "ganha" if casa or fora else "perdida"
    return None


def validar_ht(aposta, resultado):
    """Resultado do 1o tempo (HT)."""
    mercado = aposta.get("mercado", "")
    selecao = aposta.get("selecao", "")
    hh = _num(resultado.get("home_score_ht", resultado.get("home_ht_score")))
    ah = _num(resultado.get("away_score_ht", resultado.get("away_ht_score")))
    if hh is None or ah is None:
        return None
    home, away = resultado.get("home_team", ""), resultado.get("away_team", "")
    if mercado == "HT Resultado":
        if normalizar_nome(selecao) in ("sim", "yes"):  # alguem marca no HT? (interpretacao antiga)
            return "ganha" if hh != ah else "perdida"
        if nome_bate(selecao, home):
            return "ganha" if hh > ah else "perdida"
        if nome_bate(selecao, away):
            return "ganha" if ah > hh else "perdida"
    if mercado == "HT Vence sem sofrer":
        if nome_bate(selecao, home):
            return "ganha" if hh > ah and ah == 0 else "perdida"
        if nome_bate(selecao, away):
            return "ganha" if ah > hh and hh == 0 else "perdida"
    return None


def validar_handicap(aposta, resultado):
    """Handicap europeu (linha inteira, 3-way) e asiatico (.0/.5/.25/.75).
    selecao = time; linha = handicap (ex: -1, +1.5, -0.75). NOVO mercado."""
    selecao = aposta.get("selecao") or aposta.get("aposta") or ""
    linha = _num(aposta.get("linha"))
    if linha is None:
        linha = extrair_linha(aposta.get("aposta", ""))
    linha = _num(linha)
    hs, aw = _placar(resultado)
    if linha is None or hs is None or aw is None:
        return None

    # diferenca de gols do ponto de vista do time apostado
    if nome_bate(selecao, resultado.get("home_team", "")):
        diff = hs - aw
    elif nome_bate(selecao, resultado.get("away_team", "")):
        diff = aw - hs
    else:
        return None

    margem = diff + linha  # >0 ganha, <0 perde, ==0 push

    # Handicap asiatico de quarto de linha (.25/.75): meia aposta em cada lado
    frac = abs(linha - round(linha))
    if abs(frac - 0.25) < 1e-9 or abs(frac - 0.75) < 1e-9:
        baixa = linha - 0.25 if (linha > 0) else linha - 0.25
        # avalia nas duas meias-linhas (linha-0.25 e linha+0.25)
        r1 = _resolver_margem(diff + (linha - 0.25))
        r2 = _resolver_margem(diff + (linha + 0.25))
        return _combinar_meia_aposta(r1, r2)

    return _resolver_margem(margem)


def _resolver_margem(margem):
    if margem > 0:
        return "ganha"
    if margem < 0:
        return "perdida"
    return "anulada"  # push (linha inteira/meia exata)


def _combinar_meia_aposta(r1, r2):
    """Quarter-line: metade do valor em cada meia-linha."""
    if r1 == r2:
        return r1
    # uma metade ganha e outra anula -> meia-vitoria (tratado como ganha parcial)
    if "ganha" in (r1, r2) and "anulada" in (r1, r2):
        return "ganha"
    if "perdida" in (r1, r2) and "anulada" in (r1, r2):
        return "perdida"
    return "anulada"


# ── mercados de estatistica (precisam de resultado["stats"]) ──

def _stat_total(resultado, chave_home, chave_away):
    stats = resultado.get("stats") or {}
    h, a = _num(stats.get(chave_home)), _num(stats.get(chave_away))
    if h is None or a is None:
        return None
    return h + a


def validar_estatistica(aposta, resultado, chave_home, chave_away):
    """Over/under generico sobre uma estatistica (escanteios, cartoes, chutes)."""
    total = _stat_total(resultado, chave_home, chave_away)
    if total is None:
        return None
    direcao = (aposta.get("direcao") or aposta.get("selecao") or "").lower()
    linha = _num(aposta.get("linha"))
    if linha is None:
        linha = extrair_linha(aposta.get("aposta", ""))
    linha = _num(linha)
    if linha is None:
        return None
    return _over_under(total, linha, direcao)


# ============================================================
# Dispatcher
# ============================================================

# Mercados que dependem de stats de jogador (marcador/assistencia) — sem fonte
# confiavel hoje, ficam pendentes (None) para nao marcar errado.
MERCADOS_PENDENTES = {"Marcador", "Assistência", "Jogador Chutes", "Jogador Chutes no Gol"}


def validar(aposta, resultado):
    """Distribuidor principal: decide qual validador usar pelo mercado da aposta.
    Devolve 'ganha'|'perdida'|'anulada'|None."""
    if resultado.get("status") not in JOGO_ENCERRADO:
        return None

    mercado = aposta.get("mercado", "")

    if mercado in MERCADOS_PENDENTES:
        return None
    if mercado == "Escanteios":
        return validar_estatistica(aposta, resultado, "home_corners", "away_corners")
    if mercado == "Cartões":
        return validar_estatistica(aposta, resultado, "home_cards", "away_cards")
    if mercado == "Chutes":
        return validar_estatistica(aposta, resultado, "home_shots", "away_shots")
    if mercado == "Chutes no Gol":
        return validar_estatistica(aposta, resultado, "home_shots_on", "away_shots_on")
    if mercado in ("HT Resultado", "HT Vence sem sofrer"):
        return validar_ht(aposta, resultado)
    if mercado == "Ambas Marcam":
        return validar_btts(aposta, resultado)
    if mercado == "Dupla Chance":
        return validar_dupla_chance(aposta, resultado)
    if mercado == "Handicap":
        return validar_handicap(aposta, resultado)
    if mercado in ("Total", "Total de Gols", "Pontos"):
        return validar_total_gols(aposta, resultado)
    if mercado in ("Moneyline", "Resultado", "1X2"):
        return validar_moneyline(aposta, resultado)

    # Fallback por conteudo (apostas sem mercado bem definido)
    texto = normalizar_nome(" ".join(str(aposta.get(k, "")) for k in ("aposta", "mercado", "selecao")))
    if (aposta.get("direcao") in ("over", "under")) and any(p in texto for p in ("gol", "gols", "goals")):
        return validar_total_gols(aposta, resultado)
    if any(p in texto for p in ("ambas", "btts", "both teams")):
        return validar_btts(aposta, resultado)
    if any(p in texto for p in ("moneyline", "vence", "resultado final", " ml")):
        return validar_moneyline(aposta, resultado)
    return None
