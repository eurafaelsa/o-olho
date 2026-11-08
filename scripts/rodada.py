#!/usr/bin/env python3
"""Rodada diária do O Olho.

Pede ao Claude (API com busca na web) os sinais novos desde a última rodada, valida cada ficha
pela metodologia, grava as bases em data/, registra as leituras do dia no histórico e escreve
o resumo usado no pedido de aprovação do GitHub.
"""
import datetime as dt
import json
import math
import os
import re
import sys
import unicodedata
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DADOS = RAIZ / "data"
MODELO = os.environ.get("MODELO") or "claude-sonnet-5-5"
MAX_BUSCAS = int(os.environ.get("MAX_BUSCAS") or "20")
RESUMO = Path(os.environ.get("RESUMO") or "/tmp/resumo-rodada.md")
FUSO = dt.timezone(dt.timedelta(hours=-3))  # Fortaleza

FAMILIAS = {"militar": "Militar", "diplomatico": "Diplomático", "violencia": "Violência em curso",
            "defesa_civil": "Defesa civil", "economico": "Econômico", "informacional": "Informacional"}
ESCALAS = {"local": "Local", "continental": "Continental", "mundial": "Mundial"}
NIVEL = {"local": 0, "continental": 1, "mundial": 2}
HORIZONTES = (("curto", "meia_vida_curto"), ("medio", "meia_vida_medio"), ("longo", "meia_vida_longo"))
TIPOS = ("Aliança", "Diálogo", "Atrito", "Hostilidade")


def ler(nome):
    return json.loads((DADOS / f"{nome}.json").read_text(encoding="utf-8"))


def gravar(nome, dado):
    (DADOS / f"{nome}.json").write_text(json.dumps(dado, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def dia(valor):
    return dt.date.fromisoformat(str(valor)[:10])


def arred(x):
    return math.floor(x + 0.5)  # mesmo arredondamento do painel


def limpar(texto):
    texto = re.sub(r"\s*[\u2014\u2013]\s*", ", ", str(texto or "")).strip()
    return re.sub(r"\s+", " ", texto)


def faixa(v):
    return "Calmo" if v <= 20 else "Atenção" if v <= 40 else "Tensão" if v <= 60 else "Alerta" if v <= 80 else "Crítico"


# ---------- fórmula do índice (igual ao painel, por país) ----------
EXTRA = {"MLT": ("Malta", "Europa"), "BHR": ("Bahrein", "Ásia"), "SGP": ("Singapura", "Ásia")}


def paises_do(s):
    return [c for c in str(s.get("paises") or "").split(",") if c]


def indice(sinais, iso, escala, meia_vida, hoje, p):
    sel = [s for s in sinais if iso in paises_do(s) and NIVEL[s["escala"]] >= NIVEL[escala] and dia(s["data"]) <= hoje]
    total = 0.0
    for f in FAMILIAS:
        soma = sum((s["intensidade"] / 3) * p["fonte_" + s["fonte_letra"]] * p["info_" + str(s["info_num"])]
                   * 2 ** (-((hoje - dia(s["data"])).days) / meia_vida) for s in sel if s["familia"] == f)
        total += p["peso_" + f] * max(0.0, min(1.0, soma / p["k"]))
    return arred(100 * total)


def leituras_do_dia(sinais, nomes, p, hoje):
    isos = sorted({c for s in sinais for c in paises_do(s)})
    linhas = []
    for escala in ESCALAS:
        for horizonte, chave in HORIZONTES:
            melhor, empatados = 0, []
            for iso in isos:
                v = indice(sinais, iso, escala, p[chave], hoje, p)
                if v > melhor:
                    melhor, empatados = v, [nomes.get(iso, iso)]
                elif v == melhor and v > 0:
                    empatados.append(nomes.get(iso, iso))
            n = sorted(empatados, key=lambda t: "".join(c for c in unicodedata.normalize("NFD", t) if not unicodedata.combining(c)).lower())
            foco = (", ".join(n[:3]) + (f" e mais {len(n) - 3}" if len(n) > 3 else "")) if melhor > 0 else None
            linhas.append({"chave": f"{hoje}|{escala}|{horizonte}", "data": str(hoje), "escala": escala,
                           "horizonte": horizonte, "indice": melhor, "foco": foco})
    return linhas


# ---------- conversa com o Claude ----------
def montar_pedido(hoje, rodada, regioes, sinais, aliancas):
    desde = dia(rodada["data"])
    recentes = [s for s in sinais if (hoje - dia(s["data"])).days <= 21]
    recentes.sort(key=lambda s: s["data"], reverse=True)
    linhas = [f"Data de hoje: {hoje}. Última rodada: {desde}.", "", "Focos monitorados (id, nome, situação):"]
    linhas += [f"- {r['regiao']}: {r['nome']} ({r['situacao']})" for r in regioes]
    linhas += ["", "Sinais já registrados nas últimas três semanas (não repita):"]
    linhas += [f"- {s['data']} | {s['regiao']} | {s['titulo']}" for s in recentes[:120]]
    linhas += ["", "Relações já registradas:"]
    linhas += [f"- {a['ator_a']} e {a['ator_b']}: {a['tipo']}" for a in aliancas]
    try:
        boletins = [b for b in ler("boletins") if b.get("fala_de_guerra")][:25]
    except Exception:
        boletins = []
    if boletins:
        linhas += ["", "Boletins de rádio recentes que falaram de guerra (use para conferir e buscar confirmação):"]
        linhas += [f"- {b['data_hora'][:16]} | {b['radio']} | {b['resumo']}" for b in boletins]
    linhas += ["", "Pesquise o que mudou desde a última rodada e responda no formato combinado."]
    return "\n".join(linhas)


def perguntar_ao_claude(sistema, pedido):
    teste = os.environ.get("OLHO_TESTE_RESPOSTA")
    if teste:  # usado só para testar o script sem gastar a API
        return Path(teste).read_text(encoding="utf-8")
    import anthropic
    cliente = anthropic.Anthropic()
    mensagens = [{"role": "user", "content": pedido}]
    ferramentas = [{"type": "web_search_20250305", "name": "web_search", "max_uses": MAX_BUSCAS}]
    resposta = None
    for _ in range(6):
        with cliente.messages.stream(model=MODELO, max_tokens=16000, system=sistema,
                                     messages=mensagens, tools=ferramentas) as fluxo:
            resposta = fluxo.get_final_message()
        if resposta.stop_reason != "pause_turn":
            break
        mensagens = mensagens + [{"role": "assistant", "content": resposta.content}]
    return "".join(b.text for b in resposta.content if getattr(b, "type", "") == "text")


def extrair_json(texto):
    m = re.search(r"<json>(.*?)</json>", texto, re.S)
    bruto = m.group(1) if m else texto[texto.find("{"): texto.rfind("}") + 1]
    return json.loads(bruto)


# ---------- validação das fichas ----------
def validar_sinal(s, hoje, focos, validos, problemas):
    try:
        data = min(dia(s["data"]), hoje)
        if (hoje - data).days > 10:
            raise ValueError("data fora da janela")
        regiao = str(s["regiao"]).strip()
        familia = str(s["familia"]).strip()
        escala = str(s["escala"]).strip()
        intensidade = int(s["intensidade"])
        letra = str(s["fonte_letra"]).strip().upper()
        info = int(s["info_num"])
        url = str(s["url"]).strip()
        titulo = limpar(s["titulo"])
        if regiao not in focos or familia not in FAMILIAS or escala not in ESCALAS:
            raise ValueError("foco, família ou escala inválidos")
        if not -3 <= intensidade <= 3 or letra not in "ABCDEF" or len(letra) != 1 or not 1 <= info <= 6:
            raise ValueError("intensidade ou nota fora da escala")
        if not url.startswith("https://") or not titulo:
            raise ValueError("sem url https ou sem título")
        if s.get("alternativa"):
            letra = max(letra, "C")
            info = max(info, 3)
        brutos = s.get("paises") or []
        brutos = brutos.split(",") if isinstance(brutos, str) else brutos
        paises = ",".join(dict.fromkeys(c.strip().upper() for c in brutos if c.strip().upper() in validos))
        contraditor = limpar(s.get("contraditor"))
        if abs(intensidade) >= 2 and not contraditor:
            contraditor = "Sem argumento contrário encontrado nesta rodada [VERIFICAR]."
        return {"data": str(data), "regiao": regiao, "familia": familia, "escala": escala, "intensidade": intensidade,
                "fonte_letra": letra, "info_num": info, "admiralty": f"{letra}{info}", "titulo": titulo,
                "fonte_nome": limpar(s.get("fonte_nome")) or "Fonte sem nome", "url": url, "contraditor": contraditor,
                "familia_nome": FAMILIAS[familia], "foco": focos[regiao], "escala_nome": ESCALAS[escala], "paises": paises,
                **({"origem": str(s["origem"])} if s.get("origem") else {})}
    except Exception as erro:  # ficha fora do padrão não entra
        problemas.append(f"Ficha descartada ({erro}): {limpar(s.get('titulo', ''))[:90]}")
        return None


TIPOS_KIT = ("Orientação oficial", "Procura em alta", "Notícia")
MOTIVOS = ("Guerra ou ataque", "Todos os riscos", "Clima ou desastre")


def nota_admiralty(valor):
    v = str(valor or "").strip().upper()
    return v if len(v) == 2 and v[0] in "ABCDEF" and v[1] in "123456" else "F6"


def proximo_id(lista, prefixo):
    numeros = [int(re.sub(r"\D", "", str(x.get("id", ""))) or 0) for x in lista]
    return f"{prefixo}{max(numeros + [0]) + 1:02d}"


def camadas_novas(resposta, hoje, nomes, problemas):
    kits, ciber, manif = ler("kits"), ler("ciber"), ler("manifestacoes")
    novos = {"kits": 0, "ciber": 0, "manifestacoes": 0}
    for k in resposta.get("kits_novos") or []:
        try:
            url = str(k["url"]).strip()
            lat, lon = float(k["lat"]), float(k["lon"])
            if k.get("tipo") not in TIPOS_KIT or not url.startswith("https://") or not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError("tipo, url ou coordenadas inválidos")
            if any(x["url"] == url and x["local"] == limpar(k["local"]) for x in kits):
                continue
            kits.append({"id": proximo_id(kits, "K"), "tipo": k["tipo"], "local": limpar(k["local"]), "nivel": limpar(k.get("nivel")) or "País",
                         "iso3": str(k.get("iso3") or "").upper() if str(k.get("iso3") or "").upper() in nomes else "", "lat": lat, "lon": lon,
                         "data": str(min(dia(k["data"]), hoje)), "resumo": limpar(k["resumo"]),
                         "motivo": k.get("motivo") if k.get("motivo") in MOTIVOS else "Todos os riscos",
                         "fonte_nome": limpar(k.get("fonte_nome")) or "Fonte sem nome", "url": url, "admiralty": nota_admiralty(k.get("admiralty"))})
            novos["kits"] += 1
        except Exception as erro:
            problemas.append(f"Kit descartado ({erro}): {limpar(k.get('local', ''))[:60]}")
    for c in resposta.get("ciber_novos") or []:
        try:
            iso, url = str(c["iso3"]).upper(), str(c["url"]).strip()
            if iso not in nomes or c.get("papel") not in ("Alvo", "Origem atribuída") or not url.startswith("https://"):
                raise ValueError("país, papel ou url inválidos")
            valor = float(c["valor"]) if c.get("valor") not in (None, "") else None
            ciber.append({"id": proximo_id(ciber, "C"), "iso3": iso, "pais": nomes[iso], "papel": c["papel"], "valor": valor,
                          "unidade": limpar(c.get("unidade")), "data": str(min(dia(c["data"]), hoje)), "resumo": limpar(c["resumo"]),
                          "fonte_nome": limpar(c.get("fonte_nome")) or "Fonte sem nome", "url": url, "admiralty": nota_admiralty(c.get("admiralty"))})
            novos["ciber"] += 1
        except Exception as erro:
            problemas.append(f"Registro de ciber descartado ({erro})")
    for m in resposta.get("manifestacoes_novas") or []:
        try:
            iso, url = str(m["iso3"]).upper(), str(m["url"]).strip()
            if iso not in nomes or not url.startswith("https://"):
                raise ValueError("país ou url inválidos")
            manif.append({"id": proximo_id(manif, "MF"), "iso3": iso, "pais": nomes[iso], "data": str(min(dia(m["data"]), hoje)),
                          "resumo": limpar(m["resumo"]), "intensidade": max(1, min(3, int(m.get("intensidade") or 1))),
                          "fonte_nome": limpar(m.get("fonte_nome")) or "Fonte sem nome", "url": url, "admiralty": nota_admiralty(m.get("admiralty"))})
            novos["manifestacoes"] += 1
        except Exception as erro:
            problemas.append(f"Manifestação descartada ({erro})")
    gravar("kits", kits)
    gravar("ciber", ciber)
    gravar("manifestacoes", manif)
    return novos


def main():
    hoje = dt.datetime.now(FUSO).date()
    sinais, regioes, aliancas = ler("sinais"), ler("regioes"), ler("aliancas")
    premissas, rodada, historico = ler("premissas"), ler("rodada"), ler("historico")
    p = {r["chave"]: float(r["valor"]) for r in premissas}
    nomes = {x["iso3"]: x["nome"] for x in ler("paises")}
    nomes.update({k: v[0] for k, v in EXTRA.items()})
    sistema = (RAIZ / "prompts" / "editor-chefe.md").read_text(encoding="utf-8")

    texto = perguntar_ao_claude(sistema, montar_pedido(hoje, rodada[0], regioes, sinais, aliancas))
    resposta = extrair_json(texto)
    problemas = []

    # focos novos
    for f in resposta.get("focos_novos") or []:
        slug = re.sub(r"[^a-z0-9-]", "", str(f.get("regiao", "")).lower())
        if slug and slug not in {r["regiao"] for r in regioes} and f.get("nome"):
            novo = {"regiao": slug, "nome": limpar(f["nome"]), "continente": limpar(f.get("continente")) or "Sem continente",
                    "situacao": limpar(f.get("situacao")) or "Tensão sem guerra", "caso": limpar(f.get("caso")) or "Sem caso de referência"}
            regioes.insert(max(0, len(regioes) - 1), novo)
    focos = {r["regiao"]: r["nome"] for r in regioes}
    focos.setdefault("mundo", "Global")

    # sinais novos, incluindo os candidatos das rádios dos últimos três dias ainda não aprovados
    consumidos = {s.get("origem") for s in sinais if s.get("origem")}
    try:
        das_radios = [c for c in ler("candidatos") if c.get("origem") not in consumidos and (hoje - dia(c["data"])).days <= 3]
    except Exception:
        das_radios = []
    vistos = {(s["url"], s["titulo"]) for s in sinais}
    novos = []
    for bruto in (resposta.get("sinais_novos") or []) + das_radios:
        s = validar_sinal(bruto, hoje, focos, set(nomes), problemas)
        if s and (s["url"], s["titulo"]) not in vistos:
            vistos.add((s["url"], s["titulo"]))
            novos.append(s)
    inicio = sum(1 for s in sinais if str(s.get("id", "")).startswith(str(hoje))) + 1
    for i, s in enumerate(novos, start=inicio):
        s["id"] = f"{hoje}-{i:02d}"
    sinais = [s for s in sinais if (hoje - dia(s["data"])).days <= 365] + novos

    # alianças novas ou que mudaram
    for a in resposta.get("aliancas_novas") or []:
        tipo = limpar(a.get("tipo"))
        url = str(a.get("url", "")).strip()
        if tipo not in TIPOS or not url.startswith("https://") or not a.get("ator_a") or not a.get("ator_b"):
            problemas.append(f"Relação descartada: {a.get('ator_a')} e {a.get('ator_b')}")
            continue
        par = {limpar(a["ator_a"]), limpar(a["ator_b"])}
        existente = next((x for x in aliancas if {x["ator_a"], x["ator_b"]} == par), None)
        dado = {"tipo": tipo, "nota": limpar(a.get("nota")), "fonte_nome": limpar(a.get("fonte_nome")), "url": url}
        if existente:
            existente.update(dado)
        else:
            maior = max([int(re.sub(r"\D", "", x["id"]) or 0) for x in aliancas] + [0])
            aliancas.append({"id": f"A{maior + 1:02d}", "ator_a": limpar(a["ator_a"]), "ator_b": limpar(a["ator_b"]), **dado})

    # rodada, histórico e gravação
    anterior = max((dia(h["data"]) for h in historico), default=None)
    rodada = [{"data": str(hoje), "proxima": str(hoje + dt.timedelta(days=1)),
               "boletim": limpar(resposta.get("boletim")) or "Rodada sem boletim do editor-chefe."}]
    extras = camadas_novas(resposta, hoje, nomes, problemas)
    leituras = leituras_do_dia(sinais, nomes, p, hoje)
    historico = [h for h in historico if h["data"] != str(hoje)] + leituras
    for nome, dado in (("sinais", sinais), ("regioes", regioes), ("aliancas", aliancas), ("rodada", rodada), ("historico", historico)):
        gravar(nome, dado)

    # resumo para o pedido de aprovação
    ant = {(h["escala"], h["horizonte"]): h["indice"] for h in historico if anterior and h["data"] == str(anterior) and anterior != hoje}
    md = [f"## Rodada de {hoje:%d/%m/%Y}", "", "**Velocímetros, horizonte médio**", ""]
    for l in leituras:
        if l["horizonte"] != "medio":
            continue
        base = ant.get((l["escala"], "medio"))
        variacao = f", {l['indice'] - base:+d} desde {anterior:%d/%m}" if base is not None else ""
        md.append(f"- **{ESCALAS[l['escala']]}:** {l['indice']} ({faixa(l['indice'])}){variacao}. Puxado por {l['foco'] or 'nenhum foco'}.")
    md += ["", "**Boletim do editor-chefe**", "", rodada[0]["boletim"], "", f"**Sinais novos ({len(novos)})**", ""]
    md += [f"- {'Rádio, ' if s.get('origem') else ''}{s['familia_nome']}, {s['foco']}: {s['titulo'].rstrip('.')}. Nota {s['admiralty']}, intensidade {s['intensidade']}. [{s['fonte_nome']}]({s['url']})" for s in novos] or ["- Nenhum sinal novo validado."]
    md += ["", f"**Camadas:** {extras['kits']} registros de kits, {extras['ciber']} de ciberataques e {extras['manifestacoes']} de manifestações."]
    pend = [limpar(x) for x in resposta.get("pendencias") or []] + problemas
    if pend:
        md += ["", "**Pendências [VERIFICAR]**", ""] + [f"- {x}" for x in pend]
    md += ["", "Aprovar este pedido (Merge) publica a rodada no painel. Fechar sem aprovar descarta a rodada."]
    RESUMO.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"Rodada {hoje}: {len(novos)} sinais novos, {len(problemas)} descartados.")


if __name__ == "__main__":
    try:
        main()
    except Exception as erro:
        print(f"A rodada falhou: {erro}", file=sys.stderr)
        sys.exit(1)
