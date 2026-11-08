/* Runtime do painel O Olho fora do claude.ai: carrega as bases em data/, roda os cálculos e redesenha. */
window.OLHO_AUDIO = true; /* nesta versão o painel pode tocar as rádios */
(function () {
  const BASES = ['sinais', 'regioes', 'aliancas', 'premissas', 'referencias', 'rodada', 'historico', 'paises', 'conflitos', 'kits', 'ciber', 'manifestacoes', 'portais', 'radios', 'boletins'];
  const PADRAO = { aba: 'geral', escala: 'continental', horizonte: 'medio', camada: 'pressao', pais: 'RUS', familia: null };
  const estado = {};
  const calcs = {};
  const memo = {};
  const desenhos = [];
  const aoDados = [];
  let params = Object.assign({}, PADRAO);
  let agendado = false;
  BASES.forEach((id) => { estado[id] = { status: 'loading', data: [] }; });

  function dados(id) {
    if (estado[id]) return estado[id];
    const c = calcs[id];
    if (!c) return { status: 'error', data: [] };
    if (memo[id]) return memo[id];
    const entradas = c.inputs.map(dados);
    if (entradas.some((e) => e.status === 'error')) return { status: 'error', data: [] };
    if (entradas.some((e) => e.status !== 'ok')) return { status: 'loading', data: [] };
    try { memo[id] = { status: 'ok', data: c.fn(...entradas.map((e) => e.data)) }; }
    catch (err) { console.error('Cálculo ' + id, err); memo[id] = { status: 'error', data: [] }; }
    return memo[id];
  }
  function desenhar() {
    agendado = false;
    aoDados.forEach((fn) => { try { fn(); } catch (e) { console.error(e); } });
    desenhos.forEach(({ nome, fn }) => {
      document.querySelectorAll('[data-draw="' + nome + '"]').forEach((el) => {
        if (el.closest('[hidden]')) return;
        try { fn(el); } catch (e) { console.error('Desenho ' + nome, e); }
      });
    });
  }
  function agendar() { if (!agendado) { agendado = true; requestAnimationFrame(desenhar); } }

  window.dash = {
    calc: (id, o) => { calcs[id] = o; },
    draw: (nome, fn) => { desenhos.push({ nome, fn }); agendar(); },
    data: dados,
    params: () => Object.assign({}, params),
    setParams: (p) => { params = Object.assign({}, params, p); agendar(); },
    setLink: (id) => { try { history.replaceState(null, '', '#' + id); } catch (e) { /* sem histórico */ } },
    onData: (fn) => { aoDados.push(fn); agendar(); },
    colors: ['#2f62c9', '#b0569a', '#12867a'],
  };

  async function carregar(id) {
    try {
      const r = await fetch('data/' + id + '.json?t=' + Date.now(), { cache: 'no-store' });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      estado[id] = { status: 'ok', data: await r.json() };
    } catch (e) {
      console.error('Base ' + id, e);
      estado[id] = { status: 'error', data: [] };
    }
    Object.keys(memo).forEach((k) => { delete memo[k]; });
    agendar();
  }
  document.addEventListener('DOMContentLoaded', () => { BASES.forEach(carregar); });
  let espera;
  window.addEventListener('resize', () => { clearTimeout(espera); espera = setTimeout(agendar, 150); });
})();
