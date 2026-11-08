# O Olho

Painel de pressão de guerra local, continental e mundial, alimentado por uma rodada diária do Claude com busca na web e publicado pelo GitHub Pages. Nada vai ao ar sem a sua aprovação.

Metodologia completa: [O Olho | Metodologia v1](https://claude.ai/artifact/LT7EfqmZS5C26GyP3gpbou)

## Como funciona

1. **Rodada automática:** todo dia às 6h de Fortaleza, o GitHub roda o editor-chefe (`scripts/rodada.py`), que pede ao Claude os sinais novos desde a última rodada.
2. **Validação:** o script confere cada ficha pela metodologia, descarta as que fogem do padrão, recalcula os velocímetros e grava a leitura do dia no histórico.
3. **Pedido de aprovação:** o GitHub abre um pull request chamado "Rodada de AAAA-MM-DD" com os velocímetros, o boletim, os sinais novos com link e as pendências.
4. **Sua decisão:** aprovar (Merge) publica a rodada no painel em poucos minutos. Fechar sem aprovar descarta a rodada.

## Arquivos do repositório

- **index.html:** o painel, com oito telas: Visão geral (velocímetros, mapa com quatro camadas, série diária), Países, Kits, Ciber, Rádios, Gatilhos (mapa mental), Alianças, Portais e Fichas.
- **assets/dash-shim.js:** motor do painel. Carrega as bases de `data/`, roda os cálculos e redesenha as telas.
- **assets/tema.css:** cores e fontes do painel, nos modos claro e escuro.
- **data/sinais.json:** fichas de sinal, cada uma com os países envolvidos. A rodada acrescenta as novas e remove as com mais de um ano.
- **data/paises.json:** contorno vetorial de 174 países já projetado, com nome em português e continente. Não muda.
- **data/conflitos.json:** países com guerra em curso, partes em guerra e violência armada. Revisão manual.
- **data/kits.json:** países, estados e cidades que pediram kits ou abriram abrigos, lugares onde a procura disparou e notícias sobre o tema. A rodada acrescenta.
- **data/ciber.json:** alvos de ciberataques e origens atribuídas por relatórios. A rodada acrescenta.
- **data/manifestacoes.json:** protestos de massa e crises internas. A rodada acrescenta.
- **data/portais.json:** diretório de portais com nota de confiabilidade. Atualização manual.
- **data/radios.json:** as 17 rádios monitoradas, com país, idioma, perfil e nota. Para incluir ou tirar uma rádio, edite este arquivo; a transmissão é encontrada sozinha no catálogo Radio Browser.
- **data/boletins.json:** resumos traduzidos dos boletins dos últimos sete dias, publicados automaticamente.
- **data/candidatos.json:** sinais sugeridos pelas rádios, que entram no pedido de aprovação diário.
- **scripts/radios.py:** grava os boletins, transcreve, traduz e classifica.
- **prompts/radios.md:** instruções do analista de escuta.
- **.github/workflows/boletins-radio.yml:** roda as rádios três vezes ao dia e publica os resumos sem pedir aprovação.
- **data/regioes.json:** focos monitorados. A rodada pode incluir focos novos.
- **data/aliancas.json:** relações entre atores, cada uma com fonte.
- **data/premissas.json:** pesos e parâmetros do índice. Só muda na calibração, sempre à mão.
- **data/referencias.json:** indicadores de contexto, como o Relógio do Juízo Final. Atualização manual.
- **data/rodada.json:** data da rodada e boletim do editor-chefe.
- **data/historico.json:** leituras gravadas por dia. Nunca edite linhas antigas: elas são a base da calibração.
- **scripts/rodada.py:** o editor-chefe automático.
- **scripts/requirements.txt:** dependência do script (SDK da Anthropic).
- **prompts/editor-chefe.md:** instruções que o Claude recebe em cada rodada. Mudar este arquivo muda o comportamento da pesquisa.
- **.github/workflows/rodada-diaria.yml:** agenda diária e abertura do pedido de aprovação.

## Configuração, uma vez só

1. **Chave da API:** crie uma chave no Claude Console e confirme que a busca na web está habilitada para a sua organização. Sem isso, a rodada falha.
2. **Repositório:** crie no GitHub um repositório chamado `o-olho` e envie estes arquivos.
3. **Segredos:** em Settings, Secrets and variables, Actions, crie o segredo `ANTHROPIC_API_KEY` com a chave do Claude e o segredo `OPENAI_API_KEY` com a chave usada só para transcrever o áudio das rádios.
4. **Permissões:** em Settings, Actions, General, Workflow permissions, marque "Read and write permissions" e "Allow GitHub Actions to create and approve pull requests".
5. **Painel:** em Settings, Pages, escolha "Deploy from a branch", branch `main`, pasta `/ (root)`.
6. **Primeira rodada:** em Actions, abra "Rodada diária do O Olho" e clique em "Run workflow".

## Ajustes

- **Horário:** está em `.github/workflows/rodada-diaria.yml`, no horário UTC. 6h em Fortaleza é 9h UTC.
- **Modelo:** crie a variável `MODELO` em Settings, Secrets and variables, Actions, Variables. Sem ela, a rodada usa `claude-sonnet-5-5`.
- **Buscas por rodada:** variável `MAX_BUSCAS`. Sem ela, o limite é 20.
- **Rádios:** horários em `.github/workflows/boletins-radio.yml` (06h01, 12h01 e 19h01 de Fortaleza). Duração de cada gravação na variável `RADIOS_DURACAO`, em segundos (padrão 180). Modelo de transcrição na variável `MODELO_TRANSCRICAO` (padrão `whisper-1`).

## Cuidados

- **Uma rodada por vez:** aprove ou feche o pedido do dia antes da rodada seguinte. Dois pedidos abertos mexem nos mesmos arquivos e entram em conflito.
- **Custo:** cada rodada consome tokens e buscas da API. O valor depende do modelo e do número de buscas; confira os preços atuais no site da Anthropic.
- **Privacidade:** no plano gratuito do GitHub, o Pages só publica repositório público, e o painel e os dados ficam visíveis para quem tiver o link. Para manter tudo privado, é preciso um plano pago do GitHub.
- **Custo das rádios:** com 17 rádios, 3 minutos e 3 vezes ao dia, são cerca de 150 minutos de áudio transcritos por dia, mais uma chamada ao Claude por rodada. Confira o preço por minuto do serviço de transcrição antes de ativar.
- **Direito autoral:** o repositório é público, por isso só resumos e trechos curtos dos boletins são publicados. A transcrição completa existe apenas durante a execução e é descartada.
- **Áudio ao vivo:** o botão "Ouvir ao vivo" só aparece para rádios com transmissão segura (https). O painel do claude.ai não toca áudio.
- **Revisão humana:** o pedido de aprovação é o seu controle de qualidade. Leia as pendências antes de aprovar.
- **Unidade do índice:** desde 7/11/2026 a nota é calculada por país. As leituras gravadas antes disso no histórico eram por foco e não foram alteradas.
- **Teste sem gastar a API:** com a variável de ambiente `OLHO_TESTE_RESPOSTA` apontando para um arquivo de resposta, o script roda sem chamar o Claude.
