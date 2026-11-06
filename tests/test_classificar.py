"""Testes das regras com dados sintéticos (nenhum dado real da operação no repositório)."""
from bloqueios import classificar as C

REGRAS = [
    ['10', 'vazamento; infiltracao', 'preventiva', 'Hidráulica', 'Emergency out of order', 'Emergência', '0', 'SIM', ''],
    ['20', 'limpeza', '', 'Limpeza', 'Cleaning', 'Limpeza', '0', 'SIM', ''],
    ['30', 'dono', '', 'Proprietário', 'Do not sell', 'Proprietário', '8', 'SIM', ''],
    ['40', 'desativada', '', 'X', 'Other', 'Outro', '0', 'NÃO', ''],
]
HOJE, AGORA = '2026-11-06', '2026-11-06 07:00'


def bloco(id_, nota, mot='Other', ini='2026-11-10', fim='2026-11-10', ativo='Sim'):
    return {'id': id_, 'lid': 'L1', 'un': 'AA101', 'tag': 'AA', 'h': 'Não', 'a': ativo, 'ini': ini, 'fim': fim,
            'mot': mot, 'nota': nota, 'por': 'x@y', 'em': '2026-11-01'}


def montar(blocks, modo='SIMULAÇÃO', limite=3, nao_lidos=frozenset(), atual=None):
    return C.montar(regras_raw=REGRAS, atual=atual or [C.HEAD], blocks=blocks, reservas=[], nao_lidos=set(nao_lidos),
                    modo=modo, limite=limite, hoje=HOJE, agora=AGORA)


def status(m, i=0):
    return m['rows'][i][C.I['Status']]


def test_acentos_e_maiusculas_na_palavra_chave():
    assert C.classifica(C.carregar_regras(REGRAS), 'INFILTRAÇÃO no banheiro', 1)['mot'] == 'Emergency out of order'


def test_excecao_bloqueia_regra():
    assert C.classifica(C.carregar_regras(REGRAS), 'vazamento (manutenção preventiva)', 1) is None


def test_minimo_de_noites_e_regra_inativa():
    r = C.carregar_regras(REGRAS)
    assert C.classifica(r, 'dono', 3) is None and C.classifica(r, 'dono', 8)['cat'] == 'Proprietário'
    assert C.classifica(r, 'desativada', 1) is None


def test_divergente_gera_acao_e_ok_nao():
    m = montar([bloco('a', 'limpeza geral', mot='Other'), bloco('b', 'limpeza geral', mot='Cleaning')])
    assert [x['id'] for x in m['acoes']] == ['a'] and status(m, 0) == 'Divergente' and status(m, 1) == 'OK'


def test_limite_so_vale_no_automatico():
    bs = [bloco(str(i), 'limpeza') for i in range(5)]
    assert len(montar(bs, 'SIMULAÇÃO', 3)['acoes']) == 5
    m = montar(bs, 'AUTOMÁTICO', 3)
    assert len(m['acoes']) == 3 and status(m, 3).startswith('Divergente – na fila')


def test_motivo_de_sistema_e_listing_inativo_nao_sao_alterados():
    assert status(montar([bloco('a', 'limpeza', mot='Migrated unit block')])).startswith('Motivo de sistema')
    assert status(montar([bloco('a', 'limpeza', ativo='Não')])).startswith('Listing inativo')


def test_encerrado_e_sem_regra():
    assert status(montar([bloco('a', 'limpeza', ini='2026-11-01', fim='2026-11-05')])) == 'Encerrado'
    assert status(montar([bloco('a', 'texto sem regra')])) == 'Sem regra – conferir'
    assert status(montar([bloco('a', '', mot='')])).startswith('Preencher – sem nota')


def test_motivo_manual_prevalece_sobre_a_regra():
    atual = [C.HEAD, ['a'] + [''] * 15 + ['Maintenance'] + [''] * 8]
    m = montar([bloco('a', 'limpeza')], atual=atual)
    assert m['acoes'][0]['para'] == 'Maintenance' and m['acoes'][0]['origem'] == 'manual'


def test_bloqueio_que_sumiu_vira_removido_mas_nao_se_listing_nao_lido():
    linha = [''] * 25
    linha[C.I['Block ID']], linha[C.I['Listing ID']], linha[C.I['Checkout']], linha[C.I['Status']] = 'x', 'L9', '2027-01-01', 'OK'
    atual = [C.HEAD, linha]
    assert status(montar([], atual=atual)) == 'Removido da Guesty'
    assert status(montar([], atual=atual, nao_lidos={'L9'})) == 'OK'
    assert montar([], nao_lidos={'L9'})['reservas_ok'] is False


def test_resultados_atualizam_status_e_log():
    m = montar([bloco('a', 'limpeza'), bloco('b', 'limpeza'), bloco('c', 'limpeza')])
    res = [dict(id='a', un='AA101', ini='', fim='', nota='', de='Other', para='Cleaning', origem='regra 20', tipo='ok', msg=''),
           dict(id='b', un='AA101', ini='', fim='', nota='', de='Other', para='Cleaning', origem='regra 20', tipo='sobrepoe', msg='BC-1'),
           dict(id='c', un='AA101', ini='', fim='', nota='', de='Other', para='Cleaning', origem='regra 20', tipo='simulacao', msg='')]
    out = C.aplicar_resultados(rows=m['rows'], resultados=res, agora=AGORA, modo='AUTOMÁTICO', n_novos=3, faltaram='',
                               reservas=[], reservas_ok=True)
    st = [r[C.I['Status']] for r in m['rows']]
    assert st == ['Corrigido em 06/11', 'Revisar – sobrepõe reserva BC-1', 'Divergente – seria corrigido para Cleaning']
    assert [l[-1] for l in out['log']] == ['Corrigido', 'Pulado – sobrepõe reserva BC-1']  # simulação não entra no Log
    assert out['data'][2]['range'] == 'Reservas!A2' and len(out['data'][2]['values']) == C.RES_MAX
