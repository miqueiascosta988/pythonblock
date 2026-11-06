"""Teste de ponta a ponta do orquestrador com planilha e Guesty simuladas (verifica a fiação entre os módulos)."""
import pytest
from bloqueios import classificar as C
from bloqueios import config, run

REGRAS = [['20', 'limpeza', '', 'Limpeza', 'Cleaning', 'Limpeza', '0', 'SIM', '']]


class FakeSheet:
    def __init__(self, modo='SIMULAÇÃO'):
        self.modo, self.escritas, self.logs, self.b4 = modo, [], [], []


class FakeGuesty:
    def __init__(self, *a, **k):
        self.chamadas, self.puts = 0, []
        FakeGuesty.ultima = self

    def validar_conta(self, nome): pass

    def listar_listings(self):
        return [{'id': 'L1', 'n': 'AA101', 't': 'AA', 'h': 'Não', 'a': 'Sim'}]

    def ler_calendario(self, listings, desde, ate):
        b = {'id': 'B1', 'lid': 'L1', 'un': 'AA101', 'tag': 'AA', 'h': 'Não', 'a': 'Sim', 'ini': '2999-01-10', 'fim': '2999-01-10',
             'mot': 'Other', 'nota': 'limpeza', 'por': 'x', 'em': '2026-11-01'}
        return {'blocks': [b], 'reservas': [], 'nao_lidos': set()}

    def corrigir(self, it, *, aplicar):
        if aplicar:
            self.puts.append(it['id'])
        return {**{k: it[k] for k in ('id', 'un', 'ini', 'fim', 'nota', 'de', 'para', 'origem')},
                'tipo': 'ok' if aplicar else 'simulacao', 'msg': ''}


@pytest.fixture
def ambiente(monkeypatch):
    sh = FakeSheet()
    monkeypatch.setattr(run.sheets, 'ler', lambda s, *r: [REGRAS, [C.HEAD], [[sh.modo]], [['3']]])
    monkeypatch.setattr(run.sheets, 'escrever', lambda s, d: sh.escritas.append(d))
    monkeypatch.setattr(run.sheets, 'anexar_log', lambda s, aba, col, linhas: sh.logs.append(linhas))
    monkeypatch.setattr(run.sheets, 'painel_b4', lambda s, t: sh.b4.append(t))
    monkeypatch.setattr(run.guesty, 'Guesty', FakeGuesty)
    monkeypatch.setattr(run.guesty, 'obter_token', lambda *a, **k: 'tok')
    return sh


def cfg(permitir_put):
    return config.Config(sheet_id='s', google_json='{}', guesty_client_id='i', guesty_client_secret='s', permitir_put=permitir_put)


def args(**k):
    return type('A', (), {'dry_run': False, 'unidades': '', **k})


def test_simulacao_grava_planilha_sem_put(ambiente):
    assert run._executar(cfg(True), None, '2026-11-06 07:00', args()) == 0
    status = ambiente.escritas[0][0]['values'][1][C.I['Status']]
    assert status == 'Divergente – seria corrigido para Cleaning' and FakeGuesty.ultima.puts == []
    assert ambiente.logs[0][0][-1] == 'Nenhuma alteração enviada'


def test_automatico_sem_allow_put_nao_faz_put(ambiente):
    ambiente.modo = 'AUTOMÁTICO'
    run._executar(cfg(False), None, '2026-11-06 07:00', args())
    assert FakeGuesty.ultima.puts == []


def test_automatico_com_allow_put_corrige(ambiente):
    ambiente.modo = 'AUTOMÁTICO'
    run._executar(cfg(True), None, '2026-11-06 07:00', args())
    assert FakeGuesty.ultima.puts == ['B1']
    assert ambiente.escritas[0][0]['values'][1][C.I['Status']].startswith('Corrigido em')


def test_dry_run_nao_grava_e_nao_faz_put(ambiente):
    ambiente.modo = 'AUTOMÁTICO'
    assert run._executar(cfg(True), None, '2026-11-06 07:00', args(dry_run=True)) == 0
    assert ambiente.escritas == [] and ambiente.logs == [] and FakeGuesty.ultima.puts == []


def test_erro_inesperado_registra_no_painel(ambiente, monkeypatch):
    monkeypatch.setattr(run.config, 'carregar', lambda **k: cfg(False))
    monkeypatch.setattr(run.sheets, 'abrir', lambda *a: None)
    monkeypatch.setattr(FakeGuesty, 'listar_listings', lambda self: [])
    assert run.main([]) == 1
    assert ambiente.b4[0].startswith('⏳') and ambiente.b4[-1].startswith('ERRO')
