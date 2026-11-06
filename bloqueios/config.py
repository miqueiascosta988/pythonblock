"""Configuração por variáveis de ambiente (no GitHub Actions vêm de Secrets/Variables; local, de um .env)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _carregar_env_local() -> None:
    f = Path('.env')
    if not f.exists():
        return
    for linha in f.read_text().splitlines():
        linha = linha.strip()
        if linha and not linha.startswith('#') and '=' in linha:
            k, v = linha.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _obrigatoria(nome: str) -> str:
    v = os.environ.get(nome, '').strip()
    if not v:
        raise SystemExit(f'Variável de ambiente obrigatória ausente: {nome}')
    return v


@dataclass(frozen=True)
class Config:
    sheet_id: str
    google_json: str
    guesty_client_id: str = ''
    guesty_client_secret: str = ''
    guesty_conta: str = '360 Suítes'
    permitir_put: bool = False
    slack_token: str = ''
    token_cache: Path = Path('.cache/guesty_token.json')


def carregar(*, guesty: bool = False, slack: bool = False) -> Config:
    _carregar_env_local()
    gj = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON', '').strip()
    if not gj and os.environ.get('GOOGLE_APPLICATION_CREDENTIALS'):
        gj = Path(os.environ['GOOGLE_APPLICATION_CREDENTIALS']).read_text()
    if not gj:
        raise SystemExit('Defina GOOGLE_SERVICE_ACCOUNT_JSON (conteúdo do JSON da conta de serviço)')
    return Config(
        sheet_id=_obrigatoria('SHEET_ID'), google_json=gj,
        guesty_client_id=_obrigatoria('GUESTY_CLIENT_ID') if guesty else '',
        guesty_client_secret=_obrigatoria('GUESTY_CLIENT_SECRET') if guesty else '',
        guesty_conta=os.environ.get('GUESTY_CONTA', '360 Suítes'),
        permitir_put=os.environ.get('ALLOW_PUT', '').strip().lower() in ('1', 'true', 'sim'),
        slack_token=_obrigatoria('SLACK_BOT_TOKEN') if slack else '',
        token_cache=Path(os.environ.get('TOKEN_CACHE', '.cache/guesty_token.json')))
