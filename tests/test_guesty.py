"""Testes do cliente da Guesty com respostas simuladas (nenhuma chamada de rede)."""
import pytest
from bloqueios.guesty import Guesty, GuestyAuthError


class Resp:
    def __init__(self, code, js=None, headers=None):
        self.status_code, self._js, self.headers = code, js, headers or {}
        self.text = '' if js is None else 'x'

    def json(self):
        return self._js


@pytest.fixture
def g(monkeypatch):
    monkeypatch.setattr('time.sleep', lambda s: None)
    return Guesty('t', intervalo=0)


def fila(g, *respostas):
    it = iter(respostas)
    g.s.request = lambda *a, **k: next(it)


def test_get_repete_429_e_depois_ok(g):
    fila(g, Resp(429), Resp(200, {'a': 1}))
    assert g.get('/x') == {'a': 1} and g.chamadas == 2


def test_put_nao_repete_erro_de_servidor(g):
    fila(g, Resp(500))
    assert g.req('PUT', '/x', {})['code'] == 500 and g.chamadas == 1


def test_401_aborta_tudo(g):
    fila(g, Resp(401))
    with pytest.raises(GuestyAuthError):
        g.req('GET', '/x')


def dia(blocos):
    return Resp(200, {'data': {'days': [{'listingId': 'L1', 'blockRefs': blocos}]}})


def test_calendario_extrai_bloqueio_manual_e_reserva_confirmada(g):
    fila(g, dia([
        {'_id': 'B1', 'type': 'm', 'startDate': '2026-11-05T00:00:00Z', 'endDate': '2026-11-06T00:00:00Z', 'blockReason': 'Other', 'note': 'n'},
        {'type': 'b', 'reservationId': 'R1', 'reservation': {'status': 'confirmed', 'confirmationCode': 'BC-1',
                                                             'checkInDateLocalized': '2026-11-06T00:00', 'checkOutDateLocalized': '2026-11-09'}},
        {'type': 'b', 'reservationId': 'R2', 'reservation': {'status': 'canceled', 'confirmationCode': 'ZZ'}}]))
    r = g.ler_calendario([{'id': 'L1', 'n': 'AA1', 't': '', 'h': 'Não', 'a': 'Sim'}], '2026-11-01', '2027-01-01')
    assert [b['id'] for b in r['blocks']] == ['B1'] and r['blocks'][0]['ini'] == '2026-11-05'
    assert r['reservas'] == [{'c': 'BC-1', 'lid': 'L1', 'un': 'AA1', 'ci': '2026-11-06', 'co': '2026-11-09'}] and not r['nao_lidos']


def test_calendario_com_falha_marca_listing_como_nao_lido(g):
    fila(g, *[Resp(500)] * 5)
    r = g.ler_calendario([{'id': 'L1', 'n': 'AA1', 't': '', 'h': '', 'a': ''}], 'a', 'b')
    assert r['nao_lidos'] == {'L1'} and not r['blocks']


ITEM = dict(id='B1', lid='L1', un='AA1', ini='2026-11-10', fim='2026-11-10', nota='limpeza', de='Other', para='Cleaning', origem='regra 20')
BLOCO = {'_id': 'B1', 'blockReason': 'Other', 'note': 'limpeza', 'startDate': '2026-11-10T00:00', 'endDate': '2026-11-10T00:00'}


def test_corrigir_pula_se_ha_reserva(g):
    fila(g, Resp(200, {'results': [{'confirmationCode': 'BC-9'}]}))
    assert g.corrigir(ITEM, aplicar=True)['tipo'] == 'sobrepoe'


def test_corrigir_simulacao_nao_faz_put(g):
    fila(g, Resp(200, {'results': []}))
    assert g.corrigir(ITEM, aplicar=False)['tipo'] == 'simulacao' and g.chamadas == 1


def test_corrigir_aborta_se_bloqueio_mudou(g):
    fila(g, Resp(200, {'results': []}), dia([{**BLOCO, 'note': 'outra nota'}]))
    assert g.corrigir(ITEM, aplicar=True)['tipo'] == 'mudou' and g.chamadas == 2  # sem PUT


def test_corrigir_ok_com_conferencia(g):
    fila(g, Resp(200, {'results': []}), dia([BLOCO]), Resp(200, {}), dia([{**BLOCO, 'blockReason': 'Cleaning'}]))
    assert g.corrigir(ITEM, aplicar=True)['tipo'] == 'ok'


def test_corrigir_detecta_put_que_nao_pegou(g):
    fila(g, Resp(200, {'results': []}), dia([BLOCO]), Resp(200, {}), dia([BLOCO]))
    r = g.corrigir(ITEM, aplicar=True)
    assert r['tipo'] == 'erro' and 'não mudou' in r['msg']
