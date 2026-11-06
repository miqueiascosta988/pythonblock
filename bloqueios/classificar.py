"""Regras do Gabarito: classificação dos bloqueios, decisão de correções e montagem das linhas.

Porte fiel dos módulos [C] e [E] do cenário do Make (mesma ordem de decisão, mesmos textos de status),
para que a planilha continue funcionando sem mudanças.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta
from typing import Any

HEAD = ['Block ID', 'Listing ID', 'Unidade', 'Prédio (tag)', 'Housi', 'Listing ativo', 'Início', 'Última noite',
        'Checkout', 'Noites', 'Nota (Guesty)', 'Motivo atual (EN)', 'Categoria', 'Palavra-chave encontrada',
        'Regra (prioridade)', 'Motivo pela regra (EN)', 'MOTIVO A APLICAR (preencher)', 'Status', 'Última ação',
        'Data da última ação', 'Criado por', 'Criado em', 'Primeira leitura', 'Última leitura', 'Observações']
I = {h: i for i, h in enumerate(HEAD)}
ALIAS = {'Categoria': ['Categoria', 'Categoria (regra)'], 'Regra (prioridade)': ['Regra (prioridade)', 'Regra nº']}
ORDEM_ST = ['Corrigido', 'Erro', 'Revisar', 'Preencher', 'Divergente', 'Sem regra', 'Sem nota', 'Listing inativo',
            'Motivo de sistema', 'OK', 'Encerrado', 'Removido da Guesty']
RES_MAX = 4000
_COMBINANTES = re.compile('[̀-ͯ]')


def nrm(s: Any) -> str:
    return _COMBINANTES.sub('', unicodedata.normalize('NFD', str(s or ''))).lower()


def lista(s: Any) -> list[str]:
    return [x for x in (nrm(p).strip() for p in str(s or '').split(';')) if x]


def _num(v: Any, padrao: float) -> float:
    """Equivale a `Number(v) || padrao` do JavaScript (vazio, 0 e texto inválido caem no padrão)."""
    try:
        n = float(str(v).strip().replace(',', '.')) if str(v).strip() != '' else 0
    except ValueError:
        return padrao
    return n if n else padrao


def _chave_ord(s: str) -> tuple:
    """Aproxima o localeCompare do JS: ignora maiúsculas/acentos primeiro; empate decide pelo texto original."""
    return (nrm(s), s)


def _c(r: list, i: int) -> Any:
    return r[i] if i < len(r) else ''


def carregar_regras(regras_raw: list[list]) -> list[dict]:
    """Colunas: Prioridade | Palavra-chave | Exceções | Categoria | Motivo (EN) | Motivo (PT) | Mín. noites | Ativa | Obs."""
    out = []
    for r in regras_raw:
        if not (_c(r, 1) and _c(r, 3) and _c(r, 4)):
            continue
        if nrm(_c(r, 7) or 'sim').strip() == 'nao':
            continue
        kw = lista(_c(r, 1))
        if not kw:
            continue
        p = _num(_c(r, 0), 99999)
        out.append({'p': int(p) if float(p).is_integer() else p, 'kw': kw, 'ex': lista(_c(r, 2)),
                    'cat': str(r[3]).strip(), 'mot': str(r[4]).strip(), 'min': _num(_c(r, 6), 0)})
    out.sort(key=lambda x: x['p'])  # sort estável, como no JS
    return out


def classifica(regras: list[dict], nota: str, noites: int) -> dict | None:
    n = nrm(nota)
    if not n.strip():
        return None
    for r in regras:
        k = next((k for k in r['kw'] if k in n), None)
        if k and not any(e in n for e in r['ex']) and noites >= r['min']:
            return {**r, 'k': k}
    return None


def add_dia(s: str, k: int) -> str:
    return (date.fromisoformat(s) + timedelta(days=k)).isoformat()


def noites_de(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days + 1


def _linhas_atuais(atual: list[list]) -> tuple[dict, list]:
    h0 = [str(x).strip() for x in (atual[0] if atual else [])]

    def col(nome: str) -> int:
        for n in ALIAS.get(nome, [nome]):
            if n in h0:
                return h0.index(n)
        return -1

    mapa = [col(h) for h in HEAD]
    prev: dict[str, list] = {}
    ordem: list[str] = []
    for r in atual[1:]:
        if not _c(r, 0):
            continue
        prev[r[0]] = [(_c(r, mapa[j]) if mapa[j] >= 0 else '') for j in range(len(HEAD))]
        if r[0] not in ordem:
            ordem.append(r[0])
    return prev, ordem


def montar(*, regras_raw, atual, blocks, reservas, nao_lidos, modo, limite, hoje, agora) -> dict:
    """Porte do módulo [C]. `blocks`/`reservas`: listas de dicts como no JS (id, lid, un, tag, h, a, ini, fim, mot, nota, por, em)."""
    auto = modo in ('AUTOMÁTICO', 'AUTOMATICO')
    regras = carregar_regras(regras_raw)
    novos = {b['id']: b for b in blocks}
    rsv = {f"{rv['lid']}|{rv['c']}": rv for rv in reservas}
    prev, ordem = _linhas_atuais(atual)
    rows: list[list] = []
    acoes: list[dict] = []

    def monta(b: dict, p: list | None) -> list:
        noites, checkout = noites_de(b['ini'], b['fim']), add_dia(b['fim'], 1)
        rg = classifica(regras, b['nota'], noites)
        manual = str(p[I['MOTIVO A APLICAR (preencher)']] or '').strip() if p else ''
        alvo = manual or (rg['mot'] if rg else '')
        tem_nota = bool(b['nota'].strip())
        if checkout <= hoje:
            st = 'Encerrado'
        elif not alvo:
            if b['mot']:
                st = 'Sem regra – conferir' if tem_nota else 'Sem nota – conferir'
            else:
                st = 'Preencher – sem regra e sem motivo' if tem_nota else 'Preencher – sem nota e sem motivo'
        elif alvo == b['mot']:
            st = 'OK'
        elif re.search('migrated', b['mot'], re.I):
            st = 'Motivo de sistema – não alterado'
        elif b['a'] != 'Sim':
            st = 'Listing inativo – não alterado'
        elif auto and len(acoes) >= limite:
            st = 'Divergente – na fila (limite por execução)'
        else:
            st = 'Divergente'
            acoes.append({'id': b['id'], 'lid': b['lid'], 'un': b['un'], 'ini': b['ini'], 'fim': b['fim'],
                          'nota': b['nota'], 'de': b['mot'], 'para': alvo,
                          'origem': 'manual' if manual else f"regra {rg['p']}"})

        def g(k):
            return p[I[k]] if p else ''
        return [b['id'], b['lid'], b['un'], b['tag'], b['h'], b['a'], b['ini'], b['fim'], checkout, noites, b['nota'],
                b['mot'], rg['cat'] if rg else '', rg['k'] if rg else '', rg['p'] if rg else '',
                rg['mot'] if rg else '', manual, st, g('Última ação'), g('Data da última ação'), b['por'], b['em'],
                g('Primeira leitura') or agora, agora, g('Observações')]

    for id_ in ordem:
        if id_ in novos:
            rows.append(monta(novos.pop(id_), prev[id_]))
            continue
        r = list(prev[id_])
        s = I['Status']
        if r[I['Listing ID']] in nao_lidos:
            rows.append(r)
            continue
        if r[s] not in ('Encerrado', 'Removido da Guesty'):
            r[s] = 'Encerrado' if str(r[I['Checkout']]) <= hoje else 'Removido da Guesty'
        rows.append(r)
    entrou = sorted(novos.values(), key=lambda b: _chave_ord(b['un'] + b['ini']))
    for b in entrou:
        rows.append(monta(b, None))

    reservas_saida = [[rv['c'], rv['lid'], rv['un'], rv['ci'], rv['co'], 'confirmed', agora]
                      for rv in sorted(rsv.values(), key=lambda rv: _chave_ord(rv['un'] + rv['ci']))]
    return {'rows': rows, 'acoes': acoes, 'n_novos': len(entrou), 'n_regras': len(regras),
            'reservas': reservas_saida, 'reservas_ok': len(nao_lidos) == 0}


def aplicar_resultados(*, rows, resultados, agora, modo, n_novos, faltaram, reservas, reservas_ok) -> dict:
    """Porte do módulo [E]: aplica resultados das correções nas linhas e monta Painel, Reservas e Log."""
    MOT, ST, ACAO, DT = I['Motivo atual (EN)'], I['Status'], I['Última ação'], I['Data da última ação']
    res = {r['id']: r for r in resultados}
    dm = agora[8:10] + '/' + agora[5:7]
    log: list[list] = []
    cont: dict[str, int] = {}
    for row in rows:
        r = res.get(row[0])
        if r:
            acao = f"{r.get('de') or '(vazio)'} → {r['para']} ({r['origem']})"
            t = r['tipo']
            if t == 'ok':
                row[MOT], row[ST], row[ACAO], row[DT] = r['para'], f'Corrigido em {dm}', acao, agora
            elif t == 'sobrepoe':
                row[ST] = f"Revisar – sobrepõe reserva {r['msg']}"
            elif t == 'mudou':
                row[ST] = 'Divergente – bloqueio mudou; reavaliar na próxima execução'
            elif t == 'simulacao':
                row[ST] = f"Divergente – seria corrigido para {r['para']}"
            elif t == 'pendente':
                row[ST] = 'Divergente – pendente para a próxima execução'
            else:
                row[ST], row[ACAO], row[DT] = f"Erro: {r['msg']}", acao, agora
            if t not in ('simulacao', 'pendente'):
                resultado = ('Corrigido' if t == 'ok' else
                             f"Pulado – sobrepõe reserva {r['msg']}" if t == 'sobrepoe' else
                             f"Pulado – {r['msg']}" if t == 'mudou' else f"Erro: {r['msg']}")
                log.append([agora, modo, r['un'], r['id'], r['ini'], r['fim'], r['nota'], r['de'], r['para'],
                            r['origem'], resultado])
        k = str(row[ST]).split(' –')[0].split(' em ')[0].split(':')[0]
        cont[k] = cont.get(k, 0) + 1
    resumo = (f'{len(rows)} bloqueios na base · {n_novos} novos hoje · '
              + ' · '.join(f'{k}: {cont[k]}' for k in ORDEM_ST if cont.get(k))
              + (f' · ATENÇÃO: listings não lidos: {faltaram}' if faltaram else ''))
    if reservas_ok:
        resumo += f' · reservas confirmadas na janela: {len(reservas)}'
        if len(reservas) > RES_MAX:
            resumo += ' (ACIMA DO LIMITE DA ABA RESERVAS)'
    else:
        resumo += ' · aba Reservas NÃO atualizada (leitura incompleta)'
    data = [{'range': 'Bloqueios!A1', 'values': [HEAD, *rows]},
            {'range': 'Painel!B4:B5', 'values': [[f'{agora} · modo {modo}'], [resumo]]}]
    if reservas_ok:
        pad = [['', '', '', '', '', '', '']] * max(0, RES_MAX - len(reservas))
        data.append({'range': 'Reservas!A2', 'values': [*reservas[:RES_MAX], *pad]})
    return {'resumo': resumo, 'data': data,
            'log': log or [[agora, modo, '', '', '', '', '', '', '', '', 'Nenhuma alteração enviada']]}
