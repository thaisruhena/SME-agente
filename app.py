import os, json, unicodedata, re
from flask import Flask, request, jsonify, render_template
import anthropic

app = Flask(__name__)

# Carrega dados uma vez ao iniciar o servidor
with open(os.path.join(os.path.dirname(__file__), "sme_data.json"), encoding="utf-8") as f:
    SME_DATA = json.load(f)

print(f"[SME] {len(SME_DATA['projetos'])} projetos | {len(SME_DATA['indicadores'])} indicadores carregados")

SYSTEM_PROMPT = """Você é um agente executivo especializado no monitoramento estratégico dos projetos do Governo do Estado do Rio Grande do Sul (SME-RS).

REGRAS OBRIGATÓRIAS:
- Responda SEMPRE em português brasileiro.
- Use linguagem executiva, clara e objetiva.
- Organize respostas em tópicos quando listar múltiplos itens.
- Destaque criticidades, riscos e atrasos.
- Nunca invente informações — use apenas os dados fornecidos.

STATUS OFICIAL DO PROJETO — REGRA FUNDAMENTAL:
O status oficial é SEMPRE o campo Projeto.AnáliseGerente_Situacão atribuído pelo gerente.
  CP = Com Problemas
  RA = Requer Atenção
  N  = Normal
NÃO use Projeto.STATUS_CRONOGRAMA como status do projeto.

CAMPOS IMPORTANTES:
- Projeto.AnáliseGerente: análise textual do gerente (riscos, contexto, justificativas)
- Projeto.AnáliseSPGG_Situacão: status do assessor de governança (CP/RA/N)
- Projeto.AnáliseSPGG: análise textual da SPGG
- Projeto.STATUS_OPERACIONAL: fase do projeto
- Projeto.% EXECUÇÃO: execução física
- Indicador.analise.status_grafico: 0=Sem info|1=No prazo|2=Atenção|3=Crítico
- Indicador.medicao_atual.meta vs realizado: desvios de meta
- Indicador.Objetivo_Acordado: objetivo do indicador

Panoramas gerais: inclua total, distribuição por status do gerente, projetos críticos.
Projetos específicos: inclua status do gerente, análise, execução e indicadores."""


def norm(t):
    t = str(t).lower()
    t = unicodedata.normalize("NFD", t).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t).strip()


def semantic_search(query, max_p=8):
    words = [w for w in norm(query).split() if len(w) > 2]
    if not words:
        return SME_DATA["projetos"][:max_p], SME_DATA["indicadores"][:40]
    scored = []
    for p in SME_DATA["projetos"]:
        txt = norm(" ".join(str(v) for v in p.values()))
        score = sum(txt.count(w) for w in words)
        scored.append((score, id(p), p))
    scored.sort(reverse=True)
    top = [p for s, _, p in scored if s > 0][:max_p] or SME_DATA["projetos"][:max_p]
    codes = {str(p["Projeto.CODIGO_PROJETO"]) for p in top}
    inds = [i for i in SME_DATA["indicadores"] if str(i["Indicador.CODIGO_PROJETO"]) in codes][:60]
    return top, inds


@app.route("/")
def index():
    stats = {
        "total": len(SME_DATA["projetos"]),
        "em_execucao": sum(1 for p in SME_DATA["projetos"] if p.get("Projeto.STATUS_OPERACIONAL") == "Em execução"),
        "cp":     sum(1 for p in SME_DATA["projetos"] if str(p.get("Projeto.AnáliseGerente_Situacão","")).strip().upper() == "CP"),
        "ra":     sum(1 for p in SME_DATA["projetos"] if str(p.get("Projeto.AnáliseGerente_Situacão","")).strip().upper() == "RA"),
        "normal": sum(1 for p in SME_DATA["projetos"] if str(p.get("Projeto.AnáliseGerente_Situacão","")).strip().upper() == "N"),
        "ind_criticos": sum(1 for i in SME_DATA["indicadores"] if str(i.get("Indicador.analise.status_grafico","")) == "3"),
    }
    return render_template("index.html", stats=stats)


@app.route("/perguntar", methods=["POST"])
def perguntar():
    dados = request.json or {}
    pergunta = (dados.get("pergunta") or "").strip()
    historico = dados.get("historico") or []

    if not pergunta:
        return jsonify({"erro": "Pergunta vazia."}), 400

    projetos, indicadores = semantic_search(pergunta)
    context = json.dumps({"projetos": projetos, "indicadores": indicadores}, ensure_ascii=False)

    messages = [
        {"role": m["role"], "content": m["content"]}
        for m in historico[-6:]
        if m.get("role") in ("user", "assistant")
    ]
    messages.append({
        "role": "user",
        "content": f"Pergunta: {pergunta}\n\nDados relevantes (JSON):\n{context}"
    })

    # A chave vem da variável de ambiente configurada no Render — nunca exposta ao usuário
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=messages,
    )
    return jsonify({"resposta": resp.content[0].text})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
