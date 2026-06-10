# -*- coding: utf-8 -*-
"""
Interpretacao HIBRIDA do texto de uma aposta.

Fluxo:
  1) As REGRAS do app (rapidas, gratis) tentam interpretar.
  2) Se o resultado ficar INCERTO (mercado "Outro", selecao vazia onde precisa,
     ou conflito tipico tipo handicap lido como under), a IA (Claude) resolve.
  3) Cache em memoria por texto, para nao chamar a IA 2x pelo mesmo texto.

Mantem as funcoes puras/testaveis: a chamada de rede e isolada e pode ser
mockada nos testes; a decisao "precisa de IA?" e' uma funcao pura.

Campos do dict de interpretacao:
  mercado, selecao, linha (float|None), direcao ("over"/"under"/""),
  periodo, btts_resposta ("sim"/"nao"/"")
"""
import json
import re

MERCADOS_VALIDOS = [
    "Moneyline", "DNB", "Total de Gols", "Ambas Marcam", "Dupla Chance", "Handicap",
    "Escanteios", "Cartões", "Chutes", "Chutes no Gol", "HT Resultado",
    "HT Vence sem sofrer", "Intervalo/Final", "Vencer pelo menos um tempo",
    "Marcador", "Assistência", "Outro",
]

_cache_ia = {}


# ============================================================
# Decisao: o resultado das regras esta' incerto? (funcao pura)
# ============================================================

def precisa_de_ia(info, texto):
    """Decide se vale chamar a IA para refinar a interpretacao das regras."""
    if not info:
        return True
    mercado = info.get("mercado", "")
    t = (texto or "").lower()

    # Regras nao classificaram
    if mercado in ("", "Outro"):
        return True

    # Handicap escrito como "Time -1.5" costuma ser lido errado como Total/under.
    # Se ha um sinal +/- colado a um numero e NAO ha palavra de gols/over/under explicita,
    # pode ser handicap mal classificado.
    tem_sinal_linha = bool(re.search(r"[+\-]\s*\d+(\.\d+)?", t))
    fala_gols = any(p in t for p in ("gol", "gols", "goals", "over", "under", "mais de", "menos de"))
    if mercado in ("Total", "Total de Gols") and tem_sinal_linha and not fala_gols:
        return True

    # Moneyline sem selecao definida
    if mercado == "Moneyline" and not (info.get("selecao") or "").strip():
        return True

    return False


# ============================================================
# Interpretacao por IA (Claude) — isolada (rede)
# ============================================================

_PROMPT = """Você interpreta apostas esportivas (futebol) escritas de formas variadas.
Dado o JOGO (times) e o TEXTO da aposta, devolva SOMENTE um JSON com:
- "mercado": um de [Moneyline, Total de Gols, Ambas Marcam, Dupla Chance, Handicap, Escanteios, Cartões, Chutes, Chutes no Gol, HT Resultado, HT Vence sem sofrer, Marcador, Assistência, Outro]
- "selecao": para Moneyline = nome do time ou "Empate"; Dupla Chance = "1X"/"X2"/"12"; Ambas Marcam = "sim"/"nao"; over/under = "over"/"under"; Handicap = nome do time; Marcador/Assistência = nome do jogador; senão "".
- "linha": número da linha (ex: 2.5, -1.5) ou null
- "direcao": "over", "under" ou ""
- "periodo": "jogo", "1º tempo" ou "2º tempo"
- "btts_resposta": "sim", "nao" ou ""

Regras importantes:
- "Time -1.5" / "Time +1" = Handicap (NÃO é total de gols). linha leva o sinal.
- "Over 2.5" / "mais de 2.5 gols" = Total de Gols, direcao "over", linha 2.5.
- "9.5 escanteios" = Escanteios. "4.5 cartões" = Cartões.
- "ML Time" / "Time vence" = Moneyline.
JOGO: {jogo}
TEXTO: {texto}
JSON:"""


def interpretar_ia(texto, jogo="", api_key=None, modelo="claude-haiku-4-5-20251001",
                   _requests=None):
    """Chama a API da Anthropic para interpretar o texto. Devolve dict ou None.
    `_requests` permite injetar um mock nos testes."""
    if not api_key or not (texto or "").strip():
        return None
    req = _requests
    if req is None:
        import requests as req
    try:
        r = req.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": modelo, "max_tokens": 400,
                  "messages": [{"role": "user",
                                "content": _PROMPT.format(jogo=jogo or "?", texto=texto)}]},
            timeout=30,
        )
        if r.status_code != 200:
            return None
        conteudo = r.json().get("content", [])
        txt = "".join(b.get("text", "") for b in conteudo if b.get("type") == "text")
        return _parse_json_resposta(txt)
    except Exception:
        return None


def _parse_json_resposta(txt):
    """Extrai o primeiro objeto JSON da resposta da IA e normaliza os campos."""
    if not txt:
        return None
    m = re.search(r"\{.*\}", txt, re.DOTALL)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except Exception:
        return None
    if d.get("mercado") not in MERCADOS_VALIDOS:
        # tenta casar ignorando caixa/acento simples
        return None
    linha = d.get("linha")
    try:
        linha = float(linha) if linha not in (None, "", "null") else None
    except Exception:
        linha = None
    return {
        "mercado": d.get("mercado", "Outro"),
        "selecao": str(d.get("selecao") or ""),
        "linha": linha,
        "direcao": (d.get("direcao") or "") if d.get("direcao") in ("over", "under") else "",
        "periodo": d.get("periodo") or "jogo",
        "btts_resposta": (d.get("btts_resposta") or "") if d.get("btts_resposta") in ("sim", "nao") else "",
        "fonte": "ia",
    }


# ============================================================
# Interpretacao de MENSAGEM DE GRUPO DE TIPS (IA, sem depender de emojis)
# ============================================================

# Instrucoes FIXAS (vao no "system" -> sao cacheadas pela API, baratendo as repeticoes)
_INSTRUCOES_GRUPO = """Extrai apostas de mensagens de um grupo de tips. Responda SOMENTE com JSON:
{"eh_aposta":bool,"casa":"","esporte":"","jogos":["A x B"],"odd":num|null,"valor_reais":num|null,"stake_pct":num|null,"fora_escopo":bool,"eh_multipla":bool,"pernas":[{"mercado":"","selecao":"","linha":num|null,"direcao":"over"/"under"/"","periodo":"jogo"/"1º tempo"/"2º tempo"/"1º quarto"/"2º quarto"/"3º quarto"/"4º quarto","alvo":"jogo"|nome}]}

mercado: Moneyline, DNB, Total de Gols, Ambas Marcam, Dupla Chance, Handicap, Intervalo/Final, Escanteios, Cartões, Chutes, Chutes no Gol, HT Resultado, Vencer pelo menos um tempo, Marcador, Assistência, Outro.

FOCO: Futebol e Basquete. Outro esporte: preencha + fora_escopo=true.

"E"/"&" ENTRE TIMES = JOGOS SEPARADOS (nunca um confronto entre eles):
"Tailândia e Omã para vencer" → 2 pernas ML: "Tailândia x ?" e "Omã x ?". "ML Zverev e ML Mensik" → "Zverev x ?" e "Mensik x ?". Numa múltipla, dois times com ML no MESMO jogo é impossível — são jogos distintos. Só escreva "A x B" se a mensagem deixar EXPLÍCITO que é confronto direto.
Em tênis/MMA/esportes individuais: dois atletas com "e"/"&"/"|" = dois jogos separados ("Atleta x ?").

IMAGEM (print do bilhete): é a fonte PRINCIPAL. Leia confrontos reais, mercados e odds da imagem. NUNCA pareie times de jogos diferentes. Cada perna tem seu confronto real.
Cada perna = seleção REAL e DISTINTA. NUNCA funda pernas nem omita nenhuma.

MERCADOS ESPECÍFICOS:
- Total de Gols: "Mais de 2.5 gols" → over,2.5,alvo"jogo". "Itália - Mais de 2.5 gols" → over,2.5,alvo"Itália" (gols do time ≠ gols do jogo — pernas distintas).
- "Time - Menos/Mais de X [mercado]" com Escanteios/Cartões/Chutes → alvo = nome do time.
- INTERVALO/FINAL: seleção com barra ("Brasil/Brasil","Empate/Brasil","X/2") OU rótulo HT/FT → mercado "Intervalo/Final". Um time sozinho ("Brasil") = Moneyline. "Time/Time" = Intervalo/Final.
- "Vencer pelo menos um tempo"/"vencer em qualquer período" → mercado "Vencer pelo menos um tempo" (≠ Intervalo/Final que exige resultado nos DOIS tempos).
- DNB / "Empate devolve" → mercado "DNB", selecao = time que deve vencer.
- Basquete — quartos: periodo "1º/2º/3º/4º quarto" (NUNCA "1º tempo"). "Total do 1º quarto" = alvo"jogo".
- Gol mais rápido / Primeiro a marcar → mercado "Outro", selecao "Gol mais Rápido". UMA perna só.
- Qualificação/Outright ("X se classifica","X avança","X campeão") → mercado "Outro", selecao = descrição exata, jogo = "X x ?".
- "over 2.5 do jogo" e "over 2.5 da Itália" são DUAS pernas separadas.

FORMATO BOT BetPontoBet (emojis-chave): 🏠=casa 🆚=confronto ⚽/🏀=esporte 🚀=seleção ("🚀 Ceará ML"→Moneyline Ceará) 🎰=odd 🍊=stake% 💰=R$ 🔒Limite=ignorar 👤ADM=ignorar. Sempre eh_aposta=true.
Casa por domínio de link: jogajunto.bet.br → "JogaJunto".

IMAGEM SEMPRE PREVALECE: com imagem de bilhete → eh_aposta=true e extrai da imagem, mesmo que texto diga "não será planilhada"/"somente discord"/"sobrecarga".
Só comentário (ex: "Valendo 0,5%","aproveitem") → eh_aposta=false."""

# Trechos de "lixo" (links/propaganda) removidos antes de enviar -> menos tokens
_LIXO_LINHA = ("http", "não tem cadastro", "nao tem cadastro", "nos ajuda", "odd justa",
               "odd mudou", "clique aqui", "calcule quanto vale", "ta dando pra pegar",
               "não será planilhada", "nao sera planilhada", "somente discord",
               "tu bota fé", "zebraça", "zebrinha", "bota fe",
               "👨‍💻", "🆓", "🔮", "📊")


def _limpar_msg(texto):
    out = []
    for ln in str(texto or "").splitlines():
        l = ln.strip()
        if not l:
            continue
        low = l.lower()
        if any(p in low for p in _LIXO_LINHA):
            continue
        out.append(l)
    return "\n".join(out)[:1500]


_cache_grupo = {}
_CACHE_GRUPO_MAX = 1000  # entradas máximas salvas no banco


def load_grupo_cache(data: dict):
    """Carrega cache persistido (dados['cache_ia_grupo']) na memória."""
    if isinstance(data, dict):
        _cache_grupo.update(data)


def dump_grupo_cache() -> dict:
    """Retorna snapshot do cache (últimas _CACHE_GRUPO_MAX entradas) para persistir."""
    if len(_cache_grupo) <= _CACHE_GRUPO_MAX:
        return dict(_cache_grupo)
    keys = list(_cache_grupo.keys())[-_CACHE_GRUPO_MAX:]
    return {k: _cache_grupo[k] for k in keys}


def interpretar_mensagem_grupo(texto, api_key=None, modelo="claude-haiku-4-5-20251001",
                               _requests=None, usar_cache=True,
                               imagem_b64=None, media_type="image/jpeg"):
    """Interpreta uma mensagem do grupo -> dict (ou None). Economiza com:
    prompt caching (instrucoes no 'system'), limpeza da mensagem e cache local.
    Se `imagem_b64` vier, manda o print do bilhete junto (visao) -> a IA usa a
    imagem pra pegar os confrontos REAIS (mata os pareamentos inventados)."""
    if not api_key or not (texto or "").strip():
        return None
    chave = texto.strip() + ("|IMG" if imagem_b64 else "")   # cache separado p/ com-imagem
    if usar_cache and chave in _cache_grupo:
        return _cache_grupo[chave]
    req = _requests
    if req is None:
        import requests as req

    conteudo = []
    if imagem_b64:
        conteudo.append({"type": "image", "source": {
            "type": "base64", "media_type": media_type, "data": imagem_b64}})
    conteudo.append({"type": "text", "text": f"MENSAGEM:\n{_limpar_msg(texto)}\nJSON:"})
    try:
        r = req.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                     "anthropic-beta": "prompt-caching-2024-07-31",
                     "content-type": "application/json"},
            json={
                "model": modelo,
                "max_tokens": 700,
                "system": [{"type": "text", "text": _INSTRUCOES_GRUPO,
                            "cache_control": {"type": "ephemeral"}}],
                "messages": [{"role": "user", "content": conteudo}],
            },
            timeout=60 if imagem_b64 else 40,
        )
        if r.status_code != 200:
            return None
        conteudo_r = r.json().get("content", [])
        txt = "".join(b.get("text", "") for b in conteudo_r if b.get("type") == "text")
        m = re.search(r"\{.*\}", txt, re.DOTALL)
        if not m:
            return None
        res = json.loads(m.group(0))
        if usar_cache:
            _cache_grupo[chave] = res
        return res
    except Exception:
        return None


def precisa_de_imagem(interp):
    """A interpretacao SO-TEXTO ficou arriscada? (vale gastar a imagem/visao).
    Caso classico: multipla de varios jogos -> a IA pode inventar confrontos."""
    if not interp:
        return False
    if not interp.get("eh_aposta"):
        return False
    jogos = interp.get("jogos") or []
    pernas = interp.get("pernas") or []
    if interp.get("eh_multipla") and len(jogos) >= 2:
        return True
    if len(pernas) >= 2 and len(jogos) < len(pernas):
        return True
    if not jogos:
        return True
    return False


def interpretar_grupo_hibrido(texto, api_key=None, baixar_imagem_fn=None,
                              modelo="claude-haiku-4-5-20251001", _requests=None,
                              usar_cache=True):
    """SO-TEXTO primeiro; se ficar arriscado e houver imagem, re-interpreta COM a
    imagem (visao). `baixar_imagem_fn() -> (b64, media_type) | None` e' lazy: so'
    baixa/encoda o print se for realmente necessario (controla custo)."""
    interp = interpretar_mensagem_grupo(texto, api_key=api_key, modelo=modelo,
                                        _requests=_requests, usar_cache=usar_cache)
    if interp and interp.get("eh_aposta") and precisa_de_imagem(interp) and baixar_imagem_fn:
        try:
            img = baixar_imagem_fn()
        except Exception:
            img = None
        if img:
            b64, mt = img
            interp2 = interpretar_mensagem_grupo(
                texto, api_key=api_key, modelo=modelo, _requests=_requests,
                usar_cache=usar_cache, imagem_b64=b64, media_type=mt or "image/jpeg")
            if interp2 and interp2.get("eh_aposta"):
                interp2["_usou_imagem"] = True
                return interp2
    return interp


# ============================================================
# Hibrido: regras -> (se incerto) IA
# ============================================================

def interpretar_hibrido(texto, jogo="", regras_fn=None, api_key=None, usar_cache=True):
    """regras_fn(texto, jogo) -> dict (a interpretacao por regras do app).
    Se o resultado for incerto e houver api_key, refina com a IA."""
    info = regras_fn(texto, jogo) if regras_fn else None
    if info:
        info = dict(info)
        info.setdefault("fonte", "regras")

    if not precisa_de_ia(info, texto):
        return info

    chave = (texto or "").strip().lower()
    if usar_cache and chave in _cache_ia:
        return _cache_ia[chave]

    ia = interpretar_ia(texto, jogo, api_key=api_key)
    resultado = ia if ia else info
    if usar_cache and ia:
        _cache_ia[chave] = resultado
    return resultado
