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
_INSTRUCOES_GRUPO = """Você extrai apostas de mensagens de um grupo de tips de apostas.
A mensagem pode ter emojis ou não, e pode ser uma APOSTA (simples ou múltipla) ou só um COMENTÁRIO.
Responda SOMENTE com um JSON:
{
 "eh_aposta": true ou false,
 "casa": "casa de apostas" ou "",
 "esporte": "Futebol"/"Basquete"/... ou "",
 "jogos": ["Time A x Time B", ...],
 "odd": número ou null,
 "valor_reais": número (valor em R$ da entrada) ou null,
 "stake_pct": número (% da banca) ou null,
 "fora_escopo": true se o esporte NÃO for Futebol nem Basquete (senão false),
 "eh_multipla": true ou false,
 "pernas": [{"mercado": "...", "selecao": "...", "linha": número ou null, "direcao": "over"/"under"/"", "periodo": "jogo"/"1º tempo"/"2º tempo"/"1º quarto"/"2º quarto"/"3º quarto"/"4º quarto", "alvo": "jogo" ou nome do time}]
}
mercado é um de: Moneyline, DNB, Total de Gols, Ambas Marcam, Dupla Chance, Handicap, Intervalo/Final, Escanteios, Cartões, Chutes, Chutes no Gol, HT Resultado, Vencer pelo menos um tempo, Marcador, Assistência, Outro.

FOCO: só FUTEBOL e BASQUETE. Se o esporte for outro (tênis, beisebol, vôlei...), preencha mas marque "fora_escopo": true.

REGRA CRÍTICA — "E" entre times/atletas = JOGOS SEPARADOS:
Quando a mensagem une dois times ou atletas com "e", "e também", "&" no contexto de "vencer", "ML", "Moneyline", ou cada um tem sua odd separada, são APOSTAS EM JOGOS DISTINTOS — NUNCA um jogo entre eles. Exemplos:
- "Tailândia e Omã para vencer" → 2 jogos: "Tailândia x ?" e "Omã x ?", 2 pernas ML separadas. NÃO "Tailândia x Omã".
- "Panamá e Suíça vencerem" → 2 jogos: "Panamá x ?" e "Suíça x ?". NÃO "Panamá x Suíça".
- "ML Zverev e ML Mensik" → 2 jogos: "Zverev x ?" e "Mensik x ?". NÃO "Mensik x Zverev".
- "Coventry e Middlesbrough vencendo" → 2 jogos separados.
ARGUMENTO LÓGICO: numa múltipla, ML do Time A + ML do Time B adversário NO MESMO JOGO é matematicamente impossível (só um pode vencer). Se duas pernas têm ML de times diferentes, são jogos DISTINTOS — mesmo que esses times joguem entre si na vida real. Cada perna deve ter seu próprio jogo em jogos[].
Exceção: só escreva "A x B" no jogos[] se a mensagem deixar EXPLÍCITO que é um confronto direto ("A enfrenta B", "A vs B hoje", placar "2-1").

ESPORTES INDIVIDUAIS (tênis, MMA, boxe, atletismo):
Em tênis/MMA, dois atletas listados com "e"/"&"/"|" = DOIS JOGOS DIFERENTES, não um confronto entre eles. Cada atleta tem seu próprio jogo. Use "Atleta x ?" no jogos[].

Se vier uma IMAGEM (print do bilhete da aposta), ela é a fonte PRINCIPAL: leia dela os CONFRONTOS REAIS (quem joga contra quem), mercados, seleções, linhas e odds. Em múltiplas de vários jogos, cada perna tem o SEU confronto real — NUNCA pareie times de jogos diferentes (ex: se "Itália" e "Albânia" estão em jogos distintos, é ERRADO escrever "Itália x Albânia"; use o confronto verdadeiro de cada uma, ex: "Luxemburgo x Itália").

Cada perna = uma seleção REAL e DISTINTA. NUNCA funda pernas nem omita nenhuma.
- "Mais de 2.5 gols na partida" -> Total de Gols, over, 2.5, periodo "jogo", alvo "jogo".
- "Itália - Mais de 2.5 gols" -> Total de Gols de um TIME: over, 2.5, alvo "Itália" (DIFERENTE do total do jogo — OUTRA perna).
- "Londrina - Menos de 0.5 escanteios" -> Escanteios, under, 0.5, alvo "Londrina". REGRA GERAL: "Time - Menos/Mais de X [mercado]" com qualquer mercado (Escanteios, Cartões, Chutes...) -> alvo = nome do time (NÃO "jogo").
- "Mais de 0.5 Gols no 1º Tempo" -> Total de Gols, over, 0.5, periodo "1º tempo".
- "Mais de 5.5 Cartões" -> Cartões, over, 5.5.
- INTERVALO/FINAL (HT/FT): quando a selecao tem DOIS resultados separados por barra (ex: "Brasil/Brasil", "Empate/Brasil", "X/2", "Casa/Casa"), OU aparece sob um rotulo tipo "Intervalo/Final", "Resultado Intervalo/Final", "HT/FT", "Intervalo e Final" -> mercado "Intervalo/Final"; selecao = o par exato (ex: "Brasil/Brasil" = vence o 1º tempo E vence no final). ISSO NUNCA É Moneyline.
  Regra pratica: UM time sozinho ("Brasil") = Moneyline; o MESMO time repetido com barra ("Brasil/Brasil") = Intervalo/Final.
- "Vencer em qualquer um dos tempos" / "Vencer pelo menos um tempo" / "Vence em algum período" -> mercado "Vencer pelo menos um tempo", selecao = nome do time. DIFERENTE de Intervalo/Final (que exige resultado em AMBOS os tempos com barra). NÃO escreva "Time/Time".
- "Empate ou devolve" / "Empate devolve" / "DNB" -> mercado "DNB" (Draw No Bet), selecao = nome do time que deve vencer. NÃO é Moneyline. Se vier com período ("no 1º tempo"), use periodo "1º tempo".
- "over 2.5 do jogo" e "over 2.5 da Itália" são DUAS pernas separadas.
- "França Total de Gols no 1º tempo" / "1º tempo: França Total de gols" -> Total de Gols, alvo "França", periodo "1º tempo". A linha é de GOLS DO TIME, não da partida toda.

BASQUETE — QUARTOS: "1º quarto", "2º quarto", "3º quarto", "4º quarto" são períodos válidos. "Total do 1º quarto" = Total de Gols, periodo "1º quarto", alvo "jogo" (pontos totais do quarto de AMBAS as equipes — NÃO alvo de um time). "Moneyline no 1º quarto" = Moneyline, selecao = nome do time, periodo "1º quarto". NUNCA use "1º tempo" para quartos de basquete.

GOL MAIS RÁPIDO / PRIMEIRO A MARCAR: mercado "Outro", selecao "Gol mais Rápido". É UMA ÚNICA perna independente de quantos times aparecem. NÃO crie uma perna por time.

Ignore rótulos soltos que só repetem o tipo (ex: "Resultado Final", "Total de Gols" sem valor).
Se for só comentário (ex: "Valendo 0,5%", "aproveitem"), eh_aposta=false.

FORMATO BOT BetPontoBet — quando a mensagem seguir esse padrão de emojis-chave:
  🏠 = nome da casa de apostas
  🆚 = confronto (Time A x Time B)
  ⚽/🏀 = esporte
  🚀 = seleção da perna (ex: "🚀 Ceará ML" → mercado Moneyline, seleção Ceará)
  🎰 = odd
  🍊 = stake em % da banca
  💰 = valor em R$
  🔒 Limite da aposta = limite máximo permitido (IGNORAR — não é o valor apostado)
  👤 ADM: = nome do admin (ignorar)
Nesses casos, "ML" após o nome do time = Moneyline do time. Sempre eh_aposta=true.

IMAGEM SEMPRE PREVALECE: se houver imagem de bilhete de aposta, retorne eh_aposta=true e extraia os dados DA IMAGEM, independente do texto dizer "não será planilhada", "somente discord", "sobrecarga", etc. Esses são avisos operacionais, não mudam o fato de ser uma aposta."""

# Trechos de "lixo" (links/propaganda) removidos antes de enviar -> menos tokens
_LIXO_LINHA = ("http", "não tem cadastro", "nao tem cadastro", "nos ajuda", "odd justa",
               "odd mudou", "clique aqui", "calcule quanto vale", "ta dando pra pegar",
               "não será planilhada", "nao sera planilhada", "somente discord",
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
