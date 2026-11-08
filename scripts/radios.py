#!/usr/bin/env python3
"""Boletins de rádio do O Olho.

A cada execução: encontra a transmissão atual de cada rádio no Radio Browser, grava alguns minutos
de todas ao mesmo tempo, transcreve cada gravação, pede ao Claude a tradução para o português, a
classificação (fala ou não de guerra) e eventuais sinais, e publica só resumos curtos e trechos breves.
A transcrição completa nunca é gravada no repositório, que é público.
"""
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DADOS = RAIZ / "data"
MODELO = os.environ.get("MODELO") or "claude-sonnet-5-5"
MODELO_TRANSCRICAO = os.environ.get("MODELO_TRANSCRICAO") or "whisper-1"
DURACAO = int(os.environ.get("RADIOS_DURACAO") or "180")
SEM_REDE = os.environ.get("OLHO_TESTE_SEM_REDE") == "1"  # só para testar sem internet
UA = {"User-Agent": "OOlho/1.0 (painel de risco de guerra)"}
SERVIDORES = ["https://de1.api.radio-browser.info", "https://all.api.radio-browser.info"]
FAMILIAS = {"militar": "Militar", "diplomatico": "Diplomático", "violencia": "Violência em curso",
            "defesa_civil": "Defesa civil", "economico": "Econômico", "informacional": "Informacional"}
ESCALAS = {"local": "Local", "continental": "Continental", "mundial": "Mundial"}


def ler(nome):
    return json.loads((DADOS / f"{nome}.json").read_text(encoding="utf-8"))


def gravar(nome, dado):
    (DADOS / f"{nome}.json").write_text(json.dumps(dado, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def limpar(texto):
    texto = re.sub(r"\s*[\u2014\u2013]\s*", ", ", str(texto or "")).strip()
    return re.sub(r"\s+", " ", texto)


def curto(texto, palavras=25):
    p = limpar(texto).split(" ")
    return " ".join(p[:palavras]) + ("…" if len(p) > palavras else "")


# ---------- 1. encontrar a transmissão ----------
def resolver(radio):
    import requests
    for base in SERVIDORES:
        try:
            r = requests.get(f"{base}/json/stations/search", headers=UA, timeout=20,
                             params={"name": radio["busca"], "countrycode": radio["cc"], "hidebroken": "true",
                                     "order": "votes", "reverse": "true", "limit": 15})
            r.raise_for_status()
            achadas = [e for e in r.json() if e.get("url_resolved")]
            if not achadas:
                return None
            seguras = [e for e in achadas if str(e["url_resolved"]).startswith("https://")]
            e = (seguras or achadas)[0]
            pagina = e.get("homepage") or ""
            if not str(pagina).startswith("https://") and e.get("stationuuid"):
                pagina = f"https://www.radio-browser.info/history/{e['stationuuid']}"
            return {"stream_url": seguras[0]["url_resolved"] if seguras else "", "stream_gravacao": e["url_resolved"],
                    "homepage": pagina if str(pagina).startswith("https://") else "", "nome_catalogo": limpar(e.get("name"))}
        except Exception:
            continue
    return None


# ---------- 2. gravar todas ao mesmo tempo ----------
def gravar_todas(alvos, pasta):
    processos = {}
    for radio in alvos:
        destino = pasta / f"{radio['id']}.mp3"
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-t", str(DURACAO), "-i", radio["stream_gravacao"],
               "-ac", "1", "-ar", "16000", "-b:a", "32k", str(destino)]
        processos[radio["id"]] = (subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL), destino)
    limite = time.time() + DURACAO + 120
    for proc, _ in processos.values():
        try:
            proc.wait(timeout=max(1, limite - time.time()))
        except subprocess.TimeoutExpired:
            proc.kill()
    return {rid: destino for rid, (_, destino) in processos.items() if destino.exists() and destino.stat().st_size > 50_000}


# ---------- 3. transcrever ----------
def transcrever(caminho, idioma):
    import requests
    with open(caminho, "rb") as f:
        r = requests.post("https://api.openai.com/v1/audio/transcriptions", timeout=300,
                          headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
                          data={"model": MODELO_TRANSCRICAO, "language": idioma[:2], "response_format": "text"},
                          files={"file": (caminho.name, f, "audio/mpeg")})
    r.raise_for_status()
    return r.text.strip()


# ---------- 4. traduzir e classificar com o Claude ----------
def classificar(transcricoes, radios, focos):
    teste = os.environ.get("OLHO_TESTE_RESPOSTA_RADIOS")
    if teste:
        texto = Path(teste).read_text(encoding="utf-8")
    else:
        import anthropic
        sistema = (RAIZ / "prompts" / "radios.md").read_text(encoding="utf-8")
        por_id = {r["id"]: r for r in radios}
        itens = [{"radio_id": rid, "radio": por_id[rid]["nome"], "pais": por_id[rid]["pais"], "idioma": por_id[rid]["idioma_nome"],
                  "perfil": por_id[rid]["perfil"], "transcricao": txt[:7000]} for rid, txt in transcricoes.items()]
        pedido = ("Focos do Olho (id: nome):\n" + "\n".join(f"- {k}: {v}" for k, v in focos.items())
                  + "\n\nTranscrições dos boletins desta rodada:\n" + json.dumps(itens, ensure_ascii=False))
        cliente = anthropic.Anthropic()
        with cliente.messages.stream(model=MODELO, max_tokens=12000, system=sistema,
                                     messages=[{"role": "user", "content": pedido}]) as fluxo:
            resposta = fluxo.get_final_message()
        texto = "".join(b.text for b in resposta.content if getattr(b, "type", "") == "text")
    m = re.search(r"<json>(.*?)</json>", texto, re.S)
    return json.loads(m.group(1) if m else texto[texto.find("{"): texto.rfind("}") + 1])


def main():
    agora = dt.datetime.now(dt.timezone.utc).replace(second=0, microsecond=0)
    carimbo = agora.strftime("%Y%m%dT%H%MZ")
    radios, boletins, candidatos = ler("radios"), ler("boletins"), ler("candidatos")
    paises = {p["iso3"] for p in ler("paises")}
    focos = {r["regiao"]: r["nome"] for r in ler("regioes")}

    # resolve e grava
    for r in radios:
        r["ultima_checagem"] = agora.isoformat().replace("+00:00", "Z")
        if SEM_REDE:
            continue
        achada = resolver(r)
        if achada:
            r.update(achada)
            r["status"] = "Transmissão encontrada"
        else:
            r.update({"stream_url": "", "stream_gravacao": "", "status": "Sem transmissão no catálogo"})
    transcricoes = {}
    if SEM_REDE:
        pasta_teste = Path(os.environ.get("OLHO_TESTE_TRANSCRICOES", "/tmp"))
        for r in radios:
            arq = pasta_teste / f"{r['id']}.txt"
            if arq.exists():
                transcricoes[r["id"]] = arq.read_text(encoding="utf-8")
    else:
        with tempfile.TemporaryDirectory() as pasta:
            gravadas = gravar_todas([r for r in radios if r.get("stream_gravacao")], Path(pasta))
            for r in radios:
                if r.get("stream_gravacao") and r["id"] not in gravadas:
                    r["status"] = "Falha na gravação"
            for rid, caminho in gravadas.items():
                radio = next(x for x in radios if x["id"] == rid)
                try:
                    transcricoes[rid] = transcrever(caminho, radio["idioma"])
                    radio["status"] = "Boletim gravado"
                except Exception as erro:
                    radio["status"] = "Falha na transcrição"
                    print(f"{rid}: transcrição falhou ({erro})", file=sys.stderr)
    transcricoes = {k: v for k, v in transcricoes.items() if len(v.split()) >= 15}

    novos_boletins, novos_candidatos = [], []
    if transcricoes:
        resposta = classificar(transcricoes, radios, focos)
        por_id = {r["id"]: r for r in radios}
        for b in resposta.get("boletins") or []:
            rid = str(b.get("radio_id", ""))
            if rid not in transcricoes:
                continue
            radio = por_id[rid]
            iso = [c for c in (b.get("paises") or []) if str(c).upper() in paises]
            bol = {"id": f"{carimbo}-{rid}", "radio_id": rid, "radio": radio["nome"], "data_hora": agora.isoformat().replace("+00:00", "Z"),
                   "fala_de_guerra": bool(b.get("fala_de_guerra")), "intensidade": max(0, min(3, int(b.get("intensidade") or 0))),
                   "temas": [limpar(t) for t in (b.get("temas") or [])][:5], "paises": ",".join(sorted({c.upper() for c in iso})),
                   "resumo": curto(b.get("resumo"), 70), "trechos": [curto(t) for t in (b.get("trechos") or [])][:2], "link": radio.get("homepage", "")}
            novos_boletins.append(bol)
            s = b.get("sinal")
            if s and bol["fala_de_guerra"]:
                try:
                    regiao, familia, escala = str(s["regiao"]), str(s["familia"]), str(s["escala"])
                    intensidade = int(s["intensidade"])
                    if regiao not in focos and regiao != "mundo" or familia not in FAMILIAS or escala not in ESCALAS or not -3 <= intensidade <= 3:
                        raise ValueError("ficha fora do padrão")
                    url = radio.get("homepage", "")
                    if not url.startswith("https://"):
                        raise ValueError("rádio sem página https para citar")
                    novos_candidatos.append({
                        "id": f"RAD-{carimbo}-{rid}", "origem": f"radio:{carimbo}-{rid}", "data": agora.date().isoformat(),
                        "regiao": regiao, "familia": familia, "escala": escala, "intensidade": intensidade,
                        "paises": bol["paises"].split(",") if bol["paises"] else [], "fonte_letra": radio["nota"], "info_num": 3,
                        "titulo": curto(s.get("titulo"), 30), "fonte_nome": f"{radio['nome']} (boletim de rádio)", "url": url,
                        "contraditor": limpar(s.get("contraditor")) or "Fonte única de rádio; aguarda confirmação independente [VERIFICAR]."})
                except Exception as erro:
                    print(f"{rid}: sinal descartado ({erro})", file=sys.stderr)

    limite = agora - dt.timedelta(days=7)
    boletins = novos_boletins + [b for b in boletins if dt.datetime.fromisoformat(b["data_hora"].replace("Z", "+00:00")) >= limite]
    candidatos = [c for c in candidatos if dt.date.fromisoformat(c["data"]) >= limite.date()] + novos_candidatos
    gravar("radios", radios)
    gravar("boletins", boletins)
    gravar("candidatos", candidatos)
    print(f"Boletins: {len(novos_boletins)} novos, {sum(b['fala_de_guerra'] for b in novos_boletins)} falando de guerra, {len(novos_candidatos)} sinais candidatos.")


if __name__ == "__main__":
    try:
        main()
    except Exception as erro:
        print(f"A rodada de rádios falhou: {erro}", file=sys.stderr)
        sys.exit(1)
