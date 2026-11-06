"""Envio das notificações ao Slack a partir da aba Bloqueios (colunas calculadas pela própria planilha).

A planilha decide QUEM recebe e O QUÊ (colunas "Enviar agora?", "Destino do envio", "Texto a enviar (Make)").
Este script só envia, registra na aba Envios e, assim, a coluna "Já enviado neste modo?" evita repetição.

Uso:  python -m bloqueios.slack [--escopo auto|todas|critica] [--dry-run] [--forcar]
  auto    segunda e sexta: todas as elegíveis; demais dias: só CRÍTICA, e só se SLACK_CRITICA_DIARIA=true.
"""
from __future__ import annotations

import argparse
import os
import time
from datetime import datetime, timezone

import requests

from . import config, sheets
from .guesty import SP

SEV = {'CRÍTICA': 0, 'ALTA': 1, 'MÉDIA': 2, 'BAIXA': 3}


class Slack:
    def __init__(self, token: str):
        self.s = requests.Session()
        self.s.headers['Authorization'] = f'Bearer {token}'
        self._canais: dict[str, str] | None = None

    def _api(self, metodo: str, **dados) -> dict:
        for tentativa in range(4):
            r = self.s.post(f'https://slack.com/api/{metodo}', data=dados, timeout=30)
            if r.status_code == 429:
                time.sleep(int(r.headers.get('Retry-After', '3')) + 1)
                continue
            j = r.json()
            if not j.get('ok'):
                raise RuntimeError(j.get('error', 'erro desconhecido'))
            return j
        raise RuntimeError('rate limit do Slack')

    def resolver(self, destino: str) -> str:
        """ID (C…/G…/U…/D…) passa direto; '#nome' ou 'nome' é resolvido pela lista de canais onde o bot enxerga."""
        d = destino.strip()
        if len(d) >= 9 and d[0] in 'CGUD' and d.isalnum() and d.upper() == d:
            return d
        if self._canais is None:
            self._canais, cursor = {}, ''
            while True:
                j = self._api('conversations.list', types='public_channel,private_channel', limit=1000,
                              exclude_archived='true', cursor=cursor)
                self._canais.update({c['name'].lower(): c['id'] for c in j['channels']})
                cursor = (j.get('response_metadata') or {}).get('next_cursor', '')
                if not cursor:
                    break
        nome = d.lstrip('#').lower()
        if nome not in self._canais:
            raise RuntimeError(f'canal "{destino}" não encontrado (o bot precisa ser membro; use o ID se for privado)')
        return self._canais[nome]

    def enviar(self, destino: str, texto: str) -> str:
        return self._api('chat.postMessage', channel=self.resolver(destino), text=texto, unfurl_links='false')['ts']


def escolher_escopo(escopo: str, hoje) -> str | None:
    if escopo != 'auto':
        return escopo
    if hoje.weekday() in (0, 4):  # segunda, sexta
        return 'todas'
    return 'critica' if os.environ.get('SLACK_CRITICA_DIARIA', '').lower() in ('1', 'true', 'sim') else None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--escopo', default='auto', choices=['auto', 'todas', 'critica'])
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--forcar', action='store_true', help='ignora a checagem de que a leitura da Guesty é de hoje')
    a = ap.parse_args(argv)
    cfg = config.carregar(slack=not a.dry_run)
    sh = sheets.abrir(cfg.sheet_id, cfg.google_json)
    agora_dt = datetime.now(timezone.utc).astimezone(SP)
    hoje = agora_dt.date()
    escopo = escolher_escopo(a.escopo, hoje)
    if escopo is None:
        print('Hoje não é dia de envio (segunda/sexta) e SLACK_CRITICA_DIARIA está desligada. Nada a fazer.')
        return 0

    bloq, painel, params = sheets.ler(sh, 'Bloqueios!A1:BE', 'Painel!B4', 'Parametros!B7:B9')
    b4 = str((painel[0] if painel and painel[0] else [''])[0])
    if not a.forcar and (not b4.startswith(hoje.isoformat()) or b4.startswith(('ERRO', '⏳'))):
        print(f'Leitura da Guesty não está pronta/atual (Painel!B4 = "{b4}"). Não envio com dados velhos.')
        return 1

    modo = str(params[0][0]).strip().upper() if params and params[0] else 'TESTE'
    try:
        limite_teste = int(str(params[2][0]).strip()) if len(params) > 2 and params[2] else 10
    except ValueError:
        limite_teste = 10
    h = {n: i for i, n in enumerate(bloq[0])} if bloq else {}
    falta = [c for c in ('Block ID', 'Unidade', 'Severidade', 'Enviar agora?', 'Destino do envio', 'Chave de envio',
                         'Texto a enviar (Make)') if c not in h]
    if falta:
        raise RuntimeError(f'Colunas ausentes na aba Bloqueios: {falta}')

    def v(r, nome):
        i = h.get(nome)
        return r[i] if i is not None and i < len(r) else ''

    fila = [r for r in bloq[1:] if v(r, 'Enviar agora?') == 'SIM' and v(r, 'Texto a enviar (Make)')]
    if escopo == 'critica':
        fila = [r for r in fila if v(r, 'Severidade') == 'CRÍTICA']
    fila.sort(key=lambda r: (SEV.get(v(r, 'Severidade'), 9), v(r, 'Unidade')))
    if modo == 'TESTE':
        fila = fila[:limite_teste]
    print(f'Modo {modo} · escopo {escopo} · {len(fila)} mensagens a enviar')
    if a.dry_run:
        for r in fila:
            print(f"  [{v(r, 'Severidade')}] {v(r, 'Unidade')} -> {v(r, 'Destino do envio')}")
        return 0

    sl, enviadas, erros = Slack(cfg.slack_token), 0, 0
    carimbo = agora_dt.strftime('%Y-%m-%d %H:%M')
    for r in fila:
        ts, resultado, erro = '', 'Enviado', ''
        try:
            ts = sl.enviar(v(r, 'Destino do envio'), v(r, 'Texto a enviar (Make)'))
            enviadas += 1
        except Exception as e:
            resultado, erro, erros = 'Erro', str(e)[:200], erros + 1
        # registra a cada mensagem: se o job cair no meio, o que já saiu não é reenviado na próxima execução
        sheets.anexar_log(sh, 'Envios', 'A:M', [[carimbo, modo, v(r, 'Chave de envio'), v(r, 'Block ID'), v(r, 'Unidade'),
                                                 v(r, 'Categoria Guesty (alvo)'), v(r, 'Severidade'), v(r, 'Destino do envio'),
                                                 v(r, 'Responsável'), v(r, 'Texto a enviar (Make)'), ts, resultado, erro]])
        time.sleep(1.1)  # limite do Slack: ~1 mensagem por segundo por canal
    print(f'{enviadas} enviadas, {erros} com erro.')
    return 1 if erros else 0


if __name__ == '__main__':
    raise SystemExit(main())
