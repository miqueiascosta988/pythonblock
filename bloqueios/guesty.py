"""Cliente da Guesty Open API: token com cache, listagem de unidades, calendário, checagem de reservas e correção de motivo.

Porte dos módulos [A], [B] e [D] do Make, sem o limite de tempo de 30 s do módulo de código.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from .classificar import add_dia, nrm

BASE = 'https://open-api.guesty.com/v1'
TOKEN_URL = 'https://open-api.guesty.com/oauth2/token'
SP = ZoneInfo('America/Sao_Paulo')
RETRY = {408, 429, 500, 502, 503}


class GuestyAuthError(RuntimeError):
    """Credencial recusada: não adianta tentar de novo."""


def obter_token(client_id: str, client_secret: str, cache: Path | None) -> str:
    """A Guesty limita a emissão de tokens por dia; por isso o token (válido por 24 h) é reaproveitado do cache."""
    agora = time.time()
    if cache and cache.exists():
        try:
            c = json.loads(cache.read_text())
            if c.get('client_id') == client_id and c.get('expira', 0) > agora + 600:
                return c['token']
        except (ValueError, OSError):
            pass
    r = requests.post(TOKEN_URL, data={'grant_type': 'client_credentials', 'scope': 'open-api',
                                       'client_id': client_id, 'client_secret': client_secret},
                      headers={'accept': 'application/json'}, timeout=30)
    if r.status_code != 200:
        raise GuestyAuthError(f'Falha ao obter token da Guesty (HTTP {r.status_code}): {r.text[:200]}')
    j = r.json()
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({'client_id': client_id, 'token': j['access_token'],
                                     'expira': agora + int(j.get('expires_in', 86400))}))
        os.chmod(cache, 0o600)
    return j['access_token']


class Guesty:
    def __init__(self, token: str, intervalo: float = 0.6):
        self.s = requests.Session()
        self.s.headers.update({'Authorization': f'Bearer {token}', 'accept': 'application/json'})
        self.intervalo, self._ultimo, self.chamadas = intervalo, 0.0, 0

    def _espera(self):
        w = self.intervalo - (time.monotonic() - self._ultimo)
        if w > 0:
            time.sleep(w)
        self._ultimo = time.monotonic()

    def req(self, method: str, path: str, body: dict | None = None, tentativas: int = 5) -> dict:
        """Devolve {'code', 'json'} em sucesso ou {'code', 'err'} em falha. Só repete 429/5xx/rede (PUT: só 429)."""
        ultimo = {'code': 'retry', 'err': f'falhou após {tentativas} tentativas'}
        for a in range(tentativas):
            self._espera()
            try:
                r = self.s.request(method, BASE + path, json=body, timeout=30)
            except requests.RequestException as e:
                r, ultimo = None, {'code': 'net', 'err': str(e)[:200]}
            self.chamadas += 1
            code = r.status_code if r is not None else 'net'
            if r is not None:
                if 200 <= code < 300:
                    return {'code': code, 'json': r.json() if r.text else {}}
                ultimo = {'code': code, 'err': r.text[:200]}
                if code in (401, 403):
                    raise GuestyAuthError(f'HTTP {code} em {path}: {r.text[:200]}')
            pode_repetir = (code == 429) if method != 'GET' else (code in RETRY or code == 'net')
            if not pode_repetir:
                return ultimo
            espera = min(8, 2 ** a)
            if r is not None and r.headers.get('Retry-After', '').isdigit():
                espera = min(30, int(r.headers['Retry-After']))
            time.sleep(espera)
        return ultimo

    def get(self, path: str) -> dict:
        r = self.req('GET', path)
        if 'err' in r:
            raise RuntimeError(f"HTTP {r['code']} em {path}: {r['err']}")
        return r['json']

    # ---- [A] ----
    def validar_conta(self, esperada: str) -> None:
        nome = self.get('/accounts/me').get('name', '')
        if nrm(nome) != nrm(esperada):
            raise RuntimeError(f'Token não é da conta esperada: "{nome}" (esperado "{esperada}")')

    def listar_listings(self) -> list[dict]:
        out = []
        campos = 'fields=' + requests.utils.quote('_id nickname title type tags')
        for active in ('true', 'false'):
            skip = 0
            while True:
                p = self.get(f'/listings?limit=100&sort=_id&active={active}&skip={skip}&{campos}')
                for x in p.get('results') or []:
                    if x.get('type') == 'MTL':
                        continue
                    tags = x.get('tags') or []
                    out.append({'id': x['_id'], 'n': (x.get('nickname') or x.get('title') or '').strip(),
                                't': tags[0] if tags else '',
                                'h': 'Sim' if any('housi' in str(t).lower() for t in tags) else 'Não',
                                'a': 'Sim' if active == 'true' else 'Não'})
                skip += 100
                if skip >= (p.get('count') or 0):
                    break
        return out

    # ---- [B] ----
    def ler_calendario(self, listings: list[dict], desde: str, ate: str, por_chamada: int = 5) -> dict:
        info = {x['id']: x for x in listings}
        blocks: dict[str, dict] = {}
        reservas: dict[str, dict] = {}
        nao_lidos: list[str] = []
        for i in range(0, len(listings), por_chamada):
            grupo = listings[i:i + por_chamada]
            ids = ','.join(x['id'] for x in grupo)
            r = self.req('GET', f'/availability-pricing/api/calendar/listings?listingIds={ids}&startDate={desde}&endDate={ate}')
            if 'err' in r:
                nao_lidos += [x['id'] for x in grupo]
                continue
            for d in (r['json'].get('data') or {}).get('days') or []:
                l = info.get(d.get('listingId'), {})
                for b in d.get('blockRefs') or []:
                    if not b:
                        continue
                    if (b.get('type') == 'b' and b.get('reservationId') and (b.get('reservation') or {}).get('status') == 'confirmed'
                            and b['reservationId'] not in reservas):
                        rv = b['reservation']
                        reservas[b['reservationId']] = {
                            'c': rv.get('confirmationCode') or b['reservationId'], 'lid': d['listingId'], 'un': l.get('n', ''),
                            'ci': str(rv.get('checkInDateLocalized') or '')[:10], 'co': str(rv.get('checkOutDateLocalized') or '')[:10]}
                    if b.get('type') != 'm' or not b.get('_id') or b['_id'] in blocks:
                        continue
                    blocks[b['_id']] = {
                        'id': b['_id'], 'lid': d['listingId'], 'un': l.get('n', ''), 'tag': l.get('t', ''), 'h': l.get('h', ''),
                        'a': l.get('a', ''), 'ini': str(b.get('startDate'))[:10], 'fim': str(b.get('endDate'))[:10],
                        'mot': b.get('blockReason') or '', 'nota': b.get('note') or '',
                        'por': b.get('createdBy') or b.get('updatedBy') or '', 'em': str(b.get('createdAt') or '')[:10]}
        return {'blocks': list(blocks.values()), 'reservas': list(reservas.values()), 'nao_lidos': set(nao_lidos)}

    # ---- [D] ----
    def _dia(self, lid: str, dia: str) -> dict:
        return self.req('GET', f'/availability-pricing/api/calendar/listings/{lid}?startDate={dia}&endDate={dia}')

    @staticmethod
    def _ref(resp: dict, block_id: str) -> dict | None:
        dias = ((resp.get('json') or {}).get('data') or {}).get('days') or []
        return next((b for b in (dias[0].get('blockRefs') or []) if b.get('_id') == block_id), None) if dias else None

    def corrigir(self, it: dict, *, aplicar: bool) -> dict:
        """Confere reserva sobreposta -> relê o bloqueio -> PUT do motivo (mesmas datas e nota) -> confere o resultado."""
        res = {**{k: it[k] for k in ('id', 'un', 'ini', 'fim', 'nota', 'de', 'para', 'origem')}, 'tipo': '', 'msg': ''}
        try:
            filtros = json.dumps([{'field': 'listingId', 'operator': '$eq', 'value': it['lid']},
                                  {'field': 'status', 'operator': '$in', 'value': ['confirmed']},
                                  {'field': 'checkIn', 'operator': '$lt', 'value': add_dia(it['fim'], 1)},
                                  {'field': 'checkOut', 'operator': '$gte', 'value': add_dia(it['ini'], 1)}])
            rs = self.req('GET', '/reservations?limit=3&fields=confirmationCode&filters=' + requests.utils.quote(filtros))
            if 'err' in rs:
                return {**res, 'tipo': 'erro', 'msg': f"consulta de reservas {rs['code']}: {rs['err']}"}
            conf = [x.get('confirmationCode') for x in rs['json'].get('results') or [] if x.get('confirmationCode')]
            if conf:
                return {**res, 'tipo': 'sobrepoe', 'msg': ', '.join(conf)}
            if not aplicar:
                return {**res, 'tipo': 'simulacao'}
            cur = self._dia(it['lid'], it['ini'])
            if 'err' in cur:
                return {**res, 'tipo': 'erro', 'msg': f"releitura {cur['code']}: {cur['err']}"}
            r0 = self._ref(cur, it['id'])
            if (not r0 or (r0.get('blockReason') or '') != (it['de'] or '') or (r0.get('note') or '') != (it['nota'] or '')
                    or str(r0.get('startDate'))[:10] != it['ini'] or str(r0.get('endDate'))[:10] != it['fim']):
                return {**res, 'tipo': 'mudou', 'msg': 'bloqueio alterado desde a leitura'}
            p = self.req('PUT', f"/availability-pricing/api/calendar/listings/{it['lid']}",
                         {'startDate': it['ini'], 'endDate': it['fim'], 'status': 'unavailable',
                          'blockReason': it['para'], 'note': it['nota'] or ''})
            if 'err' in p:
                return {**res, 'tipo': 'erro', 'msg': f"PUT {p['code']}: {p['err']}"}
            v = self._dia(it['lid'], it['ini'])
            if 'err' in v:
                return {**res, 'tipo': 'ok', 'msg': 'enviado; conferência não concluída'}
            ref = self._ref(v, it['id'])
            if not ref:
                return {**res, 'tipo': 'erro', 'msg': 'PUT ok, mas o bloqueio não foi encontrado na conferência'}
            if (ref.get('blockReason') or '') != it['para']:
                return {**res, 'tipo': 'erro', 'msg': f"PUT ok, mas o motivo não mudou ({ref.get('blockReason') or 'vazio'})"}
            if (ref.get('note') or '') != (it['nota'] or ''):
                return {**res, 'tipo': 'erro', 'msg': 'Motivo corrigido, mas a nota mudou: confira'}
            if str(ref.get('startDate'))[:10] != it['ini'] or str(ref.get('endDate'))[:10] != it['fim']:
                return {**res, 'tipo': 'erro', 'msg': 'Motivo corrigido, mas as datas mudaram: confira'}
            return {**res, 'tipo': 'ok'}
        except GuestyAuthError:
            raise
        except Exception as e:  # um item com problema não derruba os demais
            return {**res, 'tipo': 'erro', 'msg': str(e)[:200]}


def janela() -> tuple[str, str, str]:
    """(desde, até, hoje) no fuso de São Paulo: 7 dias para trás e 400 para frente."""
    hoje = datetime.now(timezone.utc).astimezone(SP).date()
    return (hoje - timedelta(days=7)).isoformat(), (hoje + timedelta(days=400)).isoformat(), hoje.isoformat()
