"""Acesso ao Google Sheets via conta de serviço (gspread)."""
from __future__ import annotations

import json

import gspread
from google.oauth2.service_account import Credentials

ESCOPO = ['https://www.googleapis.com/auth/spreadsheets']


def abrir(sheet_id: str, google_json: str) -> gspread.Spreadsheet:
    cred = Credentials.from_service_account_info(json.loads(google_json), scopes=ESCOPO)
    return gspread.authorize(cred).open_by_key(sheet_id)


def ler(sh: gspread.Spreadsheet, *ranges: str) -> list[list[list]]:
    """Valores formatados de vários intervalos, na ordem pedida (intervalo vazio -> [])."""
    r = sh.values_batch_get(list(ranges), params={'valueRenderOption': 'FORMATTED_VALUE'})
    return [vr.get('values', []) for vr in r['valueRanges']]


def escrever(sh: gspread.Spreadsheet, data: list[dict]) -> None:
    sh.values_batch_update({'valueInputOption': 'RAW', 'data': data})


def anexar_log(sh: gspread.Spreadsheet, aba: str, colunas: str, linhas: list[list]) -> None:
    sh.values_append(f'{aba}!{colunas}', params={'valueInputOption': 'RAW', 'insertDataOption': 'INSERT_ROWS'},
                     body={'values': linhas})


def painel_b4(sh: gspread.Spreadsheet, texto: str) -> None:
    sh.values_update('Painel!B4', params={'valueInputOption': 'RAW'}, body={'values': [[texto]]})
