# -*- coding: utf-8 -*-
"""
Configuração compartilhada do pytest — vigIA tests
====================================================

Contém fixtures, helpers e constantes reutilizáveis pelos testes.
"""

import json
import os
import unicodedata
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest


# --------------------------------------------------------------------------- #
# Constantes de domínio
# --------------------------------------------------------------------------- #
RISCOS_VALIDOS = {"BAIXO", "MÉDIO", "ALTO"}

# Municípios documentados como fora de escopo (bioma Mata Atlântica).
# Não devem aparecer nas previsões.
FORA_DE_ESCOPO = {"GOUVELANDIA", "SAO SIMAO"}

# Faixas de probabilidade esperadas por classe de risco (limiares do projeto:
# ver riskBucket em frontend/data.js — 0,40 e 0,70). Usamos uma tolerância para
# absorver arredondamento na fronteira sem deixar o teste frágil.
LIMIAR_BAIXO_MEDIO = 0.40
LIMIAR_MEDIO_ALTO = 0.70
EPS = 0.02


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def normalizar(texto: str) -> str:
    """Remove acentos, espaços extras e caixa, para comparação robusta de nomes."""
    s = unicodedata.normalize("NFD", str(texto))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.strip().upper()


def parse_dt(valor: str) -> datetime:
    """
    Faz o parse de `gerado_em`, tolerando variações de formato:
      - "2026-06-19T07:57-03:00"      (HH:MM sem segundos)
      - "2026-06-04T06:00:00-03:00"   (completo)
      - "2026-06-04"                  (sem hora — assume 03:00 BRT)
      - sufixo "Z" (UTC)
    Retorna um datetime SEMPRE ciente de fuso (timezone-aware).
    """
    s = str(valor).strip().replace("Z", "+00:00")
    if "T" not in s:
        s = s + "T03:00:00-03:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        # Sem fuso explícito: assume horário de Brasília (UTC-3).
        dt = dt.replace(tzinfo=timezone(timedelta(hours=-3)))
    return dt


def localizar_forecast() -> Path:
    """Procura o forecast.json em caminhos comuns, ou usa VIGIA_FORECAST."""
    env = os.environ.get("VIGIA_FORECAST")
    if env:
        p = Path(env)
        if p.is_file():
            return p
        pytest.fail(f"VIGIA_FORECAST aponta para arquivo inexistente: {p}")

    aqui = Path(__file__).resolve().parent
    candidatos = [
        aqui / "forecast.json",
        aqui.parent / "forecast.json",
        aqui.parent / "pbl" / "forecast.json",
        aqui.parent / "frontend" / "forecast.json",
        aqui.parent / "04_codigo" / "pbl" / "forecast.json",
        aqui.parent / "04_codigo" / "frontend" / "forecast.json",
        Path.cwd() / "forecast.json",
        Path.cwd() / "pbl" / "forecast.json",
        Path.cwd() / "frontend" / "forecast.json",
    ]
    for c in candidatos:
        if c.is_file():
            return c

    procurados = "\n  - ".join(str(c) for c in candidatos)
    pytest.fail(
        "forecast.json não encontrado. Defina VIGIA_FORECAST=/caminho/forecast.json "
        f"ou coloque-o em um destes locais:\n  - {procurados}"
    )


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="session")
def forecast() -> dict:
    """Carrega e devolve o forecast.json (uma vez por sessão de testes)."""
    caminho = localizar_forecast()
    with open(caminho, "r", encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="session")
def registros_municipios(forecast) -> list:
    """Achata todos os registros de município (de todos os dias) em uma lista."""
    out = []
    for dia, lista in forecast.get("municipios", {}).items():
        for rec in lista:
            out.append((dia, rec))
    return out


@pytest.fixture(scope="session")
def registros_celulas(forecast) -> list:
    """Achata todos os registros de célula (de todos os dias) em uma lista."""
    out = []
    for dia, lista in forecast.get("celulas", {}).items():
        for rec in lista:
            out.append((dia, rec))
    return out
