"""Execução diária: lê a Guesty, atualiza as abas Bloqueios/Reservas/Painel e corrige motivos (conforme o modo).

Uso:  python -m bloqueios.run [--dry-run] [--unidades SE2407,SL616]
  --dry-run   lê tudo, calcula, imprime o resumo; NÃO escreve na planilha e NÃO envia PUT à Guesty.
  --unidades  restringe a leitura a estas unidades (apelido ou ID). Preserva as demais linhas e não grava Reservas.
"""
from __future__ import annotations

import argparse
import sys
import traceback
from datetime import datetime, timezone

from . import classificar as C
from . import config, guesty, sheets


def agora_sp() -> str:
    return datetime.now(timezone.utc).astimezone(guesty.SP).strftime('%Y-%m-%d %H:%M')


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--unidades', default='')
    a = ap.parse_args(argv)
    cfg = config.carregar(guesty=True)
    sh = sheets.abrir(cfg.sheet_id, cfg.google_json)
    agora = agora_sp()
    if not a.dry_run:
        sheets.painel_b4(sh, f'⏳ Rodando desde {agora}…')
    try:
        return _executar(cfg, sh, agora, a)
    except Exception as e:
        print(traceback.format_exc(), file=sys.stderr)
        if not a.dry_run:
            sheets.painel_b4(sh, f'ERRO {agora} · {type(e).__name__}: {str(e)[:200]}')
        return 1


def _executar(cfg, sh, agora: str, a) -> int:
    regras_raw, atual, p_modo, p_lim = sheets.ler(sh, 'Regras!A2:I', 'Bloqueios!A1:Y', 'Painel!B3', 'Painel!B6')
    modo = str((p_modo[0] if p_modo else ['SIMULAÇÃO'])[0] or 'SIMULAÇÃO').strip().upper()
    try:
        limite = int(str((p_lim[0] if p_lim else [''])[0]).strip())
    except ValueError:
        limite = 3
    auto = modo in ('AUTOMÁTICO', 'AUTOMATICO')
    aplicar = auto and cfg.permitir_put and not a.dry_run
    if auto and not aplicar:
        print('AVISO: Painel!B3 está AUTOMÁTICO, mas ALLOW_PUT/--dry-run impede o PUT; tratando como simulação.')

    token = guesty.obter_token(cfg.guesty_client_id, cfg.guesty_client_secret, cfg.token_cache)
    g = guesty.Guesty(token)
    g.validar_conta(cfg.guesty_conta)
    desde, ate, hoje = guesty.janela()
    listings = g.listar_listings()
    if not listings:
        raise RuntimeError('Guesty devolveu 0 listings; abortando para não marcar tudo como removido')
    ignorados: set[str] = set()
    if a.unidades:
        alvo = {x.strip().lower() for x in a.unidades.split(',') if x.strip()}
        lidos = [l for l in listings if l['id'].lower() in alvo or l['n'].lower() in alvo]
        ignorados = {l['id'] for l in listings} - {l['id'] for l in lidos}
        listings = lidos
    print(f'{len(listings)} listings a ler · janela {desde} a {ate} · modo {modo}')
    lido = g.ler_calendario(listings, desde, ate)
    nao_lidos = lido['nao_lidos'] | ignorados
    if len(lido['nao_lidos']) > max(3, len(listings) // 10):
        raise RuntimeError(f"Muitos listings não lidos ({len(lido['nao_lidos'])}); abortando sem gravar")

    m = C.montar(regras_raw=regras_raw, atual=atual, blocks=lido['blocks'], reservas=lido['reservas'],
                 nao_lidos=nao_lidos, modo=modo, limite=limite, hoje=hoje, agora=agora)
    resultados = [g.corrigir(it, aplicar=aplicar) for it in m['acoes']]
    faltaram = ', '.join(sorted(lido['nao_lidos']))[:300]
    out = C.aplicar_resultados(rows=m['rows'], resultados=resultados, agora=agora, modo=modo, n_novos=m['n_novos'],
                               faltaram=faltaram, reservas=m['reservas'], reservas_ok=m['reservas_ok'])
    print(out['resumo'])
    print(f"{len(m['acoes'])} correções candidatas · {g.chamadas} chamadas à Guesty")
    if a.dry_run:
        print('--dry-run: nada foi gravado.')
        return 0
    sheets.escrever(sh, out['data'])
    sheets.anexar_log(sh, 'Log', 'A:K', out['log'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
