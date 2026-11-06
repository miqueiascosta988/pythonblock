from datetime import date

from bloqueios.slack import Slack, escolher_escopo


def test_escopo_segunda_e_sexta_enviam_tudo(monkeypatch):
    monkeypatch.delenv('SLACK_CRITICA_DIARIA', raising=False)
    assert escolher_escopo('auto', date(2026, 11, 6)) == 'todas'   # sexta
    assert escolher_escopo('auto', date(2026, 11, 9)) == 'todas'   # segunda
    assert escolher_escopo('auto', date(2026, 11, 10)) is None     # terça, sem envio diário


def test_envio_diario_de_criticas_so_se_ligado(monkeypatch):
    monkeypatch.setenv('SLACK_CRITICA_DIARIA', 'true')
    assert escolher_escopo('auto', date(2026, 11, 10)) == 'critica'


def test_resolver_id_passa_direto_e_nome_usa_lista(monkeypatch):
    s = Slack('x')
    assert s.resolver('C0123ABCDEF') == 'C0123ABCDEF'
    monkeypatch.setattr(s, '_api', lambda *a, **k: {'channels': [{'name': 'limpeza', 'id': 'C999AAAAAA'}], 'response_metadata': {}})
    assert s.resolver('#Limpeza') == 'C999AAAAAA'
