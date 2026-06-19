# -*- coding: utf-8 -*-
"""
Suíte de testes do boletim de previsão (forecast.json) — vigIA
================================================================

Estes testes formam o "portão de qualidade" (quality gate) que valida o
artefato gerado pelo pipeline antes de ir para produção. Foram desenhados
para o schema REAL produzido por `pbl/exportar_json.py`:

    {
      "gerado_em": "2026-06-19T07:57-03:00",
      "dias": ["2026-06-20", ..., "2026-06-24"],          # 5 datas ISO
      "municipios": { "2026-06-20": [ {nome, lat, lon, prob, risco, seco}, ... ], ... },
      "celulas":    { "2026-06-20": [ {lat, lon, prob, risco, mun, seco}, ... ], ... }
    }

COMO RODAR
----------
    pip install pytest
    python -m pytest tests/ -v

O teste procura o forecast.json automaticamente em locais comuns
(pbl/, frontend/, raiz, 04_codigo/...). Para apontar um caminho específico:

    VIGIA_FORECAST=/caminho/para/forecast.json python -m pytest tests/ -v

CHECAGEM DE FRESCOR (produção)
------------------------------
O teste de frescor (boletim com no máximo N horas) NÃO roda por padrão,
porque um .zip avaliado dias depois teria um boletim "antigo" de propósito.
Ele representa um monitor de produção e só roda quando habilitado:

    VIGIA_CHECK_FRESHNESS=1 python -m pytest tests/ -v          # limiar padrão: 48h
    VIGIA_CHECK_FRESHNESS=1 VIGIA_MAX_IDADE_H=24 python -m pytest tests/
"""

import os
from datetime import datetime, timezone, date

import pytest

from .conftest import (
    RISCOS_VALIDOS,
    FORA_DE_ESCOPO,
    LIMIAR_BAIXO_MEDIO,
    LIMIAR_MEDIO_ALTO,
    EPS,
    normalizar,
    parse_dt,
)


# --------------------------------------------------------------------------- #
# 1) Estrutura e schema
# --------------------------------------------------------------------------- #
class TestEstrutura:

    def test_chaves_de_topo_presentes(self, forecast):
        for chave in ("gerado_em", "dias", "municipios", "celulas"):
            assert chave in forecast, f"Chave de topo ausente no JSON: '{chave}'"

    def test_dias_sao_cinco_datas_iso(self, forecast):
        dias = forecast["dias"]
        assert isinstance(dias, list), "'dias' deve ser uma lista"
        assert len(dias) == 5, f"Esperados 5 dias de previsão, obtidos {len(dias)}"
        for d in dias:
            # Levanta ValueError se não for ISO YYYY-MM-DD
            date.fromisoformat(d)

    def test_dias_crescentes_e_consecutivos(self, forecast):
        datas = [date.fromisoformat(d) for d in forecast["dias"]]
        assert datas == sorted(datas), "Os dias não estão em ordem crescente"
        assert len(set(datas)) == len(datas), "Há dias duplicados"
        for anterior, proximo in zip(datas, datas[1:]):
            assert (proximo - anterior).days == 1, (
                f"Dias não consecutivos: {anterior} -> {proximo}"
            )

    def test_chaves_de_municipios_batem_com_dias(self, forecast):
        assert set(forecast["municipios"].keys()) == set(forecast["dias"]), (
            "As chaves de 'municipios' não correspondem exatamente a 'dias'"
        )

    def test_chaves_de_celulas_batem_com_dias(self, forecast):
        assert set(forecast["celulas"].keys()) == set(forecast["dias"]), (
            "As chaves de 'celulas' não correspondem exatamente a 'dias'"
        )

    def test_gerado_em_e_parseavel(self, forecast):
        dt = parse_dt(forecast["gerado_em"])
        assert dt.tzinfo is not None, "'gerado_em' deveria resultar em datetime com fuso"

    def test_campos_obrigatorios_municipios(self, registros_municipios):
        assert registros_municipios, "Nenhum registro de município encontrado"
        for dia, rec in registros_municipios:
            for campo in ("nome", "lat", "lon", "prob", "risco"):
                assert campo in rec, f"[{dia}] município sem campo '{campo}': {rec}"

    def test_campos_obrigatorios_celulas(self, registros_celulas):
        assert registros_celulas, "Nenhum registro de célula encontrado"
        for dia, rec in registros_celulas:
            for campo in ("lat", "lon", "prob", "risco", "mun"):
                assert campo in rec, f"[{dia}] célula sem campo '{campo}': {rec}"


# --------------------------------------------------------------------------- #
# 2) Validade dos valores
# --------------------------------------------------------------------------- #
class TestValores:

    def test_probabilidades_municipios_entre_0_e_1(self, registros_municipios):
        for dia, rec in registros_municipios:
            p = float(rec["prob"])
            assert 0.0 <= p <= 1.0, f"[{dia}] prob fora de [0,1] em {rec['nome']}: {p}"

    def test_probabilidades_celulas_entre_0_e_1(self, registros_celulas):
        for dia, rec in registros_celulas:
            p = float(rec["prob"])
            assert 0.0 <= p <= 1.0, f"[{dia}] prob de célula fora de [0,1]: {p}"

    def test_risco_municipios_valido(self, registros_municipios):
        for dia, rec in registros_municipios:
            assert rec["risco"] in RISCOS_VALIDOS, (
                f"[{dia}] risco inválido '{rec['risco']}' em {rec['nome']}"
            )

    def test_risco_celulas_valido(self, registros_celulas):
        for dia, rec in registros_celulas:
            assert rec["risco"] in RISCOS_VALIDOS, (
                f"[{dia}] risco de célula inválido: '{rec['risco']}'"
            )

    def test_coordenadas_dentro_de_goias(self, registros_municipios):
        # Caixa geográfica generosa de Goiás (lat ~ -19,6..-12,3 ; lon ~ -53,3..-45,9).
        for dia, rec in registros_municipios:
            lat, lon = float(rec["lat"]), float(rec["lon"])
            assert -20.0 <= lat <= -12.0, f"[{dia}] latitude suspeita em {rec['nome']}: {lat}"
            assert -54.0 <= lon <= -45.0, f"[{dia}] longitude suspeita em {rec['nome']}: {lon}"

    def test_indice_seco_inteiro_nao_negativo(self, registros_municipios):
        # 'seco' (dias secos) deve ser inteiro >= 0 quando presente.
        for dia, rec in registros_municipios:
            if "seco" in rec:
                seco = rec["seco"]
                assert isinstance(seco, int) and seco >= 0, (
                    f"[{dia}] 'seco' inválido em {rec['nome']}: {seco}"
                )


# --------------------------------------------------------------------------- #
# 3) Coerência risco x probabilidade
# --------------------------------------------------------------------------- #
class TestCoerencia:
    """
    As classes BAIXO/MÉDIO/ALTO devem ser separáveis por probabilidade,
    conforme os limiares do projeto (0,40 e 0,70). Verifica que não há
    inversões grosseiras (ex.: um ALTO com prob baixa).
    """

    def _por_classe(self, registros):
        faixas = {"BAIXO": [], "MÉDIO": [], "ALTO": []}
        for _dia, rec in registros:
            if rec["risco"] in faixas:
                faixas[rec["risco"]].append(float(rec["prob"]))
        return faixas

    def test_baixo_abaixo_do_limiar(self, registros_municipios):
        faixas = self._por_classe(registros_municipios)
        for p in faixas["BAIXO"]:
            assert p < LIMIAR_BAIXO_MEDIO + EPS, f"BAIXO com prob alta demais: {p}"

    def test_alto_acima_do_limiar(self, registros_municipios):
        faixas = self._por_classe(registros_municipios)
        for p in faixas["ALTO"]:
            assert p >= LIMIAR_MEDIO_ALTO - EPS, f"ALTO com prob baixa demais: {p}"

    def test_classes_separaveis(self, registros_municipios):
        faixas = self._por_classe(registros_municipios)
        if faixas["BAIXO"] and faixas["MÉDIO"]:
            assert max(faixas["BAIXO"]) <= min(faixas["MÉDIO"]) + EPS, (
                "Sobreposição relevante entre BAIXO e MÉDIO"
            )
        if faixas["MÉDIO"] and faixas["ALTO"]:
            assert max(faixas["MÉDIO"]) <= min(faixas["ALTO"]) + EPS, (
                "Sobreposição relevante entre MÉDIO e ALTO"
            )


# --------------------------------------------------------------------------- #
# 4) Cobertura e escopo geográfico
# --------------------------------------------------------------------------- #
class TestCobertura:

    def test_cobertura_minima_de_municipios(self, forecast):
        # Reúne nomes distintos previstos em qualquer dia.
        nomes = set()
        for lista in forecast["municipios"].values():
            for rec in lista:
                nomes.add(normalizar(rec["nome"]))
        assert len(nomes) >= 200, (
            f"Cobertura muito baixa: apenas {len(nomes)} municípios previstos "
            "(esperado ~244). Pipeline pode ter falhado parcialmente."
        )
        assert len(nomes) <= 246, (
            f"Mais municípios ({len(nomes)}) do que existem em Goiás (246)."
        )

    def test_municipios_fora_de_escopo_ausentes(self, forecast):
        nomes = set()
        for lista in forecast["municipios"].values():
            for rec in lista:
                nomes.add(normalizar(rec["nome"]))
        intrusos = FORA_DE_ESCOPO & nomes
        assert not intrusos, (
            f"Municípios fora de escopo (Mata Atlântica) apareceram na previsão: {intrusos}"
        )

    def test_celulas_tem_municipio_nao_vazio(self, registros_celulas):
        for dia, rec in registros_celulas:
            assert isinstance(rec["mun"], str) and rec["mun"].strip(), (
                f"[{dia}] célula sem município válido: {rec}"
            )

    def test_cada_dia_tem_previsoes(self, forecast):
        for dia in forecast["dias"]:
            assert forecast["municipios"].get(dia), f"Dia sem previsão de municípios: {dia}"
            assert forecast["celulas"].get(dia), f"Dia sem previsão de células: {dia}"


# --------------------------------------------------------------------------- #
# 5) Frescor do boletim (monitor de produção — desabilitado por padrão)
# --------------------------------------------------------------------------- #
class TestFrescor:

    @pytest.mark.skipif(
        os.environ.get("VIGIA_CHECK_FRESHNESS") != "1",
        reason="Checagem de frescor é um monitor de produção; "
               "habilite com VIGIA_CHECK_FRESHNESS=1 (ex.: no cron do CI).",
    )
    def test_boletim_recente(self, forecast):
        limite_h = float(os.environ.get("VIGIA_MAX_IDADE_H", "48"))
        gerado = parse_dt(forecast["gerado_em"])
        idade_h = (datetime.now(timezone.utc) - gerado).total_seconds() / 3600.0
        assert idade_h <= limite_h, (
            f"Boletim com {idade_h:.1f}h (limite {limite_h:.0f}h). "
            "O pipeline diário pode estar parado."
        )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))