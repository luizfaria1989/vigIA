#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
monitor_forecast.py — Monitor de produção do vigIA
===================================================

Diferente da suíte de testes (pytest, que é um portão pass/fail), este script
é um MONITOR DE PRODUÇÃO. A ideia é rodá-lo logo após o pipeline diário e
acompanhar a saúde do sistema ao longo do tempo, em três camadas:

  1) SAÚDE DO SISTEMA   — boletim existe, é JSON válido, está fresco (recente)
  2) QUALIDADE DOS DADOS — cobertura de municípios, valores inválidos, escopo
  3) SAÍDA DO MODELO     — distribuição de risco, anomalias, top-N críticos
  4) (opcional) DESEMPENHO — hit-rate dos top-N contra focos observados (INPE)

Saídas:
  - relatório legível no terminal, com status [OK] / [ALERTA] / [FALHA];
  - linha acrescentada a um histórico CSV (fonte de dados do dashboard);
  - (opcional) snapshot de métricas em JSON, para painéis/automação.

Só usa biblioteca padrão (roda no GitHub Actions sem instalar nada).

USO
---
    python monitor_forecast.py                       # auto-localiza forecast.json
    python monitor_forecast.py --forecast pbl/forecast.json
    python monitor_forecast.py --max-idade-h 24      # limiar de frescor (alerta)
    python monitor_forecast.py --out metrics.json    # salva snapshot de métricas
    python monitor_forecast.py --history hist.csv     # arquivo de histórico (default)
    python monitor_forecast.py --observados focos.json  # mede desempenho do modelo
    python monitor_forecast.py --strict              # ALERTA também retorna != 0

CÓDIGOS DE SAÍDA
----------------
    0  tudo OK (ou apenas ALERTAs, sem --strict)
    1  houve ALERTA e --strict foi usado
    2  houve FALHA (acione a equipe)

FORMATO DE --observados (para backtest, opcional)
-------------------------------------------------
    { "2026-06-20": ["NIQUELÂNDIA", "CAVALCANTE", ...], ... }
    (lista de municípios que REALMENTE registraram foco naquele dia, p.ex. via INPE)
"""

import argparse
import csv
import json
import os
import statistics
import sys
import unicodedata
from datetime import datetime, timezone, timedelta
from pathlib import Path

# --------------------------------------------------------------------------- #
# Constantes de domínio
# --------------------------------------------------------------------------- #
RISCOS_VALIDOS = {"BAIXO", "MÉDIO", "ALTO"}
FORA_DE_ESCOPO = {"GOUVELANDIA", "SAO SIMAO"}     # bioma Mata Atlântica
MUNICIPIOS_ESPERADOS = 244                         # municípios no escopo (Cerrado)
TOP_N = 10                                          # tamanho do ranking crítico

# Status possíveis (ordenados por severidade)
OK, ALERTA, FALHA = "OK", "ALERTA", "FALHA"
SEVERIDADE = {OK: 0, ALERTA: 1, FALHA: 2}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def normalizar(texto) -> str:
    s = unicodedata.normalize("NFD", str(texto))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.strip().upper()


def parse_dt(valor) -> datetime:
    """Parse tolerante de `gerado_em`; retorna datetime com fuso."""
    s = str(valor).strip().replace("Z", "+00:00")
    if "T" not in s:
        s = s + "T03:00:00-03:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone(timedelta(hours=-3)))
    return dt


def localizar_forecast(explicito: str | None) -> Path:
    if explicito:
        p = Path(explicito)
        if not p.is_file():
            raise FileNotFoundError(f"forecast.json não encontrado: {p}")
        return p
    aqui = Path(__file__).resolve().parent
    for c in [
        aqui / "forecast.json",
        aqui / "pbl" / "forecast.json",
        aqui / "frontend" / "forecast.json",
        aqui.parent / "pbl" / "forecast.json",
        aqui.parent / "frontend" / "forecast.json",
        Path.cwd() / "pbl" / "forecast.json",
        Path.cwd() / "frontend" / "forecast.json",
        Path.cwd() / "forecast.json",
    ]:
        if c.is_file():
            return c
    raise FileNotFoundError(
        "forecast.json não localizado automaticamente. Use --forecast CAMINHO."
    )


def pior(*status) -> str:
    return max(status, key=lambda s: SEVERIDADE[s])


# --------------------------------------------------------------------------- #
# Cálculo de métricas
# --------------------------------------------------------------------------- #
def calcular_metricas(fc: dict) -> dict:
    dias = fc.get("dias", [])
    municipios = fc.get("municipios", {})
    celulas = fc.get("celulas", {})

    todos_muni = [r for d in dias for r in municipios.get(d, [])]
    todas_cel = [r for d in dias for r in celulas.get(d, [])]

    probs_muni = [float(r["prob"]) for r in todos_muni if "prob" in r]
    nomes = {normalizar(r.get("nome", "")) for r in todos_muni}
    nomes.discard("")

    # Distribuição de risco (municípios)
    dist = {"BAIXO": 0, "MÉDIO": 0, "ALTO": 0}
    for r in todos_muni:
        if r.get("risco") in dist:
            dist[r["risco"]] += 1
    total_class = sum(dist.values()) or 1

    # Probabilidades inválidas / riscos inválidos
    probs_invalidas = sum(
        1 for r in todos_muni + todas_cel
        if not (isinstance(r.get("prob"), (int, float)) and 0.0 <= float(r["prob"]) <= 1.0)
    )
    riscos_invalidos = sum(
        1 for r in todos_muni + todas_cel if r.get("risco") not in RISCOS_VALIDOS
    )

    # Frescor
    idade_h = None
    if "gerado_em" in fc:
        try:
            idade_h = (datetime.now(timezone.utc) - parse_dt(fc["gerado_em"])).total_seconds() / 3600
        except Exception:
            idade_h = None

    # Top-N do primeiro dia
    top = []
    if dias:
        d0 = sorted(municipios.get(dias[0], []), key=lambda r: float(r.get("prob", 0)), reverse=True)
        top = [(r.get("nome"), round(float(r.get("prob", 0)), 4)) for r in d0[:TOP_N]]

    # Anomalias: variância ~0 (todos iguais) ou tudo zero
    variancia = statistics.pvariance(probs_muni) if len(probs_muni) > 1 else 0.0
    tudo_zero = bool(probs_muni) and max(probs_muni) == 0.0

    intrusos = sorted(FORA_DE_ESCOPO & nomes)

    return {
        "gerado_em": fc.get("gerado_em"),
        "idade_h": round(idade_h, 2) if idade_h is not None else None,
        "n_dias": len(dias),
        "n_municipios_distintos": len(nomes),
        "cobertura_pct": round(100 * len(nomes) / MUNICIPIOS_ESPERADOS, 1),
        "n_celulas_total": len(todas_cel),
        "prob_media": round(statistics.fmean(probs_muni), 4) if probs_muni else None,
        "prob_min": round(min(probs_muni), 4) if probs_muni else None,
        "prob_max": round(max(probs_muni), 4) if probs_muni else None,
        "prob_variancia": round(variancia, 6),
        "pct_baixo": round(100 * dist["BAIXO"] / total_class, 1),
        "pct_medio": round(100 * dist["MÉDIO"] / total_class, 1),
        "pct_alto": round(100 * dist["ALTO"] / total_class, 1),
        "probs_invalidas": probs_invalidas,
        "riscos_invalidos": riscos_invalidos,
        "municipios_fora_escopo": intrusos,
        "tudo_zero": tudo_zero,
        "top_n": top,
    }


# --------------------------------------------------------------------------- #
# Checagens (cada uma devolve (status, mensagem))
# --------------------------------------------------------------------------- #
def avaliar_checagens(m: dict, max_idade_h: float) -> list:
    checks = []

    # 1) SAÚDE DO SISTEMA — frescor (alerta em max_idade_h, falha no dobro)
    idade = m["idade_h"]
    if idade is None:
        checks.append(("Frescor do boletim", ALERTA, "gerado_em ausente ou ilegível"))
    elif idade > 2 * max_idade_h:
        checks.append(("Frescor do boletim", FALHA, f"{idade:.1f}h (limite {max_idade_h:.0f}h) — pipeline pode estar parado"))
    elif idade > max_idade_h:
        checks.append(("Frescor do boletim", ALERTA, f"{idade:.1f}h (limite {max_idade_h:.0f}h)"))
    else:
        checks.append(("Frescor do boletim", OK, f"{idade:.1f}h"))

    # 1b) Janela de 5 dias
    checks.append(("Janela de previsão",
                   OK if m["n_dias"] == 5 else FALHA,
                   f"{m['n_dias']} dias"))

    # 2) QUALIDADE DOS DADOS — cobertura
    cob = m["cobertura_pct"]
    if cob < 90:
        checks.append(("Cobertura de municípios", FALHA, f"{cob}% ({m['n_municipios_distintos']}/{MUNICIPIOS_ESPERADOS})"))
    elif cob < 98:
        checks.append(("Cobertura de municípios", ALERTA, f"{cob}% ({m['n_municipios_distintos']}/{MUNICIPIOS_ESPERADOS})"))
    else:
        checks.append(("Cobertura de municípios", OK, f"{cob}% ({m['n_municipios_distintos']}/{MUNICIPIOS_ESPERADOS})"))

    # 2b) Valores inválidos
    checks.append(("Probabilidades válidas",
                   OK if m["probs_invalidas"] == 0 else FALHA,
                   f"{m['probs_invalidas']} fora de [0,1]"))
    checks.append(("Rótulos de risco válidos",
                   OK if m["riscos_invalidos"] == 0 else FALHA,
                   f"{m['riscos_invalidos']} inválidos"))

    # 2c) Escopo geográfico
    intr = m["municipios_fora_escopo"]
    checks.append(("Escopo geográfico",
                   OK if not intr else FALHA,
                   "sem intrusos" if not intr else f"fora de escopo presentes: {intr}"))

    # 3) SAÍDA DO MODELO — anomalia de saída constante / tudo zero
    if m["tudo_zero"]:
        checks.append(("Saída do modelo", FALHA, "todas as probabilidades são zero"))
    elif m["prob_variancia"] is not None and m["prob_variancia"] < 1e-6:
        checks.append(("Saída do modelo", FALHA, "variância ~0 (saída constante — provável bug)"))
    else:
        checks.append(("Saída do modelo", OK,
                       f"média={m['prob_media']} var={m['prob_variancia']}"))

    # 3b) Distribuição plausível (alerta se >70% ALTO — risco de modelo 'alarmista')
    if m["pct_alto"] is not None and m["pct_alto"] > 70:
        checks.append(("Distribuição de risco", ALERTA,
                       f"ALTO={m['pct_alto']}% — distribuição suspeita"))
    else:
        checks.append(("Distribuição de risco", OK,
                       f"B={m['pct_baixo']}% M={m['pct_medio']}% A={m['pct_alto']}%"))

    return checks


def avaliar_backtest(fc: dict, observados: dict) -> tuple:
    """
    Mede desempenho do modelo: dos TOP_N municípios mais arriscados previstos
    por dia, quantos realmente registraram foco. Devolve (metricas, checagem).
    """
    dias = fc.get("dias", [])
    obs_norm = {d: {normalizar(n) for n in nomes} for d, nomes in observados.items()}

    acertos, total_top, total_obs = 0, 0, 0
    por_dia = []
    for d in dias:
        previstos = sorted(fc["municipios"].get(d, []),
                           key=lambda r: float(r.get("prob", 0)), reverse=True)
        top = [normalizar(r.get("nome", "")) for r in previstos[:TOP_N]]
        reais = obs_norm.get(d, set())
        if not reais:
            continue
        hit = len(set(top) & reais)
        acertos += hit
        total_top += len(top)
        total_obs += len(reais)
        por_dia.append({"dia": d, "hit_top_n": hit, "n_top": len(top), "n_observados": len(reais)})

    if total_top == 0:
        return ({"backtest": "sem dados observados sobrepostos"},
                ("Desempenho (backtest)", ALERTA, "sem dias observados para comparar"))

    hit_rate = round(acertos / total_top, 3)
    # lift sobre baseline aleatório (prob de um município qualquer ter foco)
    base = (total_obs / MUNICIPIOS_ESPERADOS) if total_obs else 0
    lift = round(hit_rate / base, 2) if base else None

    metricas = {"hit_rate_top_n": hit_rate, "lift_vs_aleatorio": lift, "por_dia": por_dia}
    status = OK if hit_rate >= 0.30 else (ALERTA if hit_rate >= 0.15 else FALHA)
    msg = f"hit-rate@{TOP_N}={hit_rate} (lift={lift}x)"
    return metricas, ("Desempenho (backtest)", status, msg)


# --------------------------------------------------------------------------- #
# Relatório e histórico
# --------------------------------------------------------------------------- #
def imprimir_relatorio(m: dict, checks: list, geral: str, usar_cor: bool) -> None:
    def tag(s):
        if not usar_cor:
            return f"[{s}]".ljust(9)
        cor = {OK: "\033[92m", ALERTA: "\033[93m", FALHA: "\033[91m"}[s]
        return f"{cor}[{s}]\033[0m".ljust(18)

    print("=" * 64)
    print("  vigIA — Relatório de monitoramento do boletim")
    print(f"  Execução: {datetime.now().astimezone().isoformat(timespec='seconds')}")
    print(f"  Boletim : {m['gerado_em']}  (idade: {m['idade_h']}h)")
    print("=" * 64)
    for nome, status, detalhe in checks:
        print(f"  {tag(status)} {nome:<26} {detalhe}")
    print("-" * 64)
    if m["top_n"]:
        print("  Top municípios críticos (dia 1):")
        for nome, p in m["top_n"][:5]:
            print(f"     {p:>6.2%}  {nome}")
    print("-" * 64)
    print(f"  STATUS GERAL: {tag(geral)}")
    print("=" * 64)


def registrar_historico(caminho: Path, m: dict, geral: str, extras: dict) -> None:
    novo = not caminho.exists()
    linha = {
        "executado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "gerado_em": m["gerado_em"],
        "idade_h": m["idade_h"],
        "cobertura_pct": m["cobertura_pct"],
        "prob_media": m["prob_media"],
        "pct_alto": m["pct_alto"],
        "probs_invalidas": m["probs_invalidas"],
        "hit_rate_top_n": extras.get("hit_rate_top_n", ""),
        "status": geral,
    }
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(linha.keys()))
        if novo:
            w.writeheader()
        w.writerow(linha)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Monitor de produção do boletim vigIA.")
    ap.add_argument("--forecast", help="Caminho do forecast.json (auto-localiza se omitido)")
    ap.add_argument("--history", default="metrics_history.csv", help="CSV de histórico (dashboard)")
    ap.add_argument("--out", help="Salva snapshot de métricas em JSON")
    ap.add_argument("--observados", help="JSON {dia: [municípios com foco]} para backtest")
    ap.add_argument("--max-idade-h", type=float, default=24.0, help="Limiar de frescor (alerta)")
    ap.add_argument("--strict", action="store_true", help="ALERTA também retorna código != 0")
    ap.add_argument("--no-color", action="store_true", help="Desliga cores ANSI")
    ap.add_argument("--quiet", action="store_true", help="Não imprime o relatório completo")
    args = ap.parse_args(argv)

    try:
        caminho = localizar_forecast(args.forecast)
    except FileNotFoundError as e:
        print(f"[FALHA] {e}", file=sys.stderr)
        return 2

    try:
        fc = json.loads(Path(caminho).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"[FALHA] forecast.json ilegível ({caminho}): {e}", file=sys.stderr)
        return 2

    m = calcular_metricas(fc)
    checks = avaliar_checagens(m, args.max_idade_h)
    extras = {}

    # Backtest opcional
    if args.observados:
        try:
            observados = json.loads(Path(args.observados).read_text(encoding="utf-8"))
            bt_metricas, bt_check = avaliar_backtest(fc, observados)
            checks.append(bt_check)
            extras = {k: v for k, v in bt_metricas.items() if k == "hit_rate_top_n"}
            m["backtest"] = bt_metricas
        except Exception as e:
            checks.append(("Desempenho (backtest)", ALERTA, f"erro ao ler observados: {e}"))

    geral = pior(*(s for _, s, _ in checks)) if checks else OK

    usar_cor = (not args.no_color) and sys.stdout.isatty()
    if not args.quiet:
        imprimir_relatorio(m, checks, geral, usar_cor)

    if args.out:
        snapshot = dict(m)
        snapshot["status_geral"] = geral
        snapshot["checagens"] = [{"nome": n, "status": s, "detalhe": d} for n, s, d in checks]
        Path(args.out).write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        if not args.quiet:
            print(f"  snapshot salvo em: {args.out}")

    registrar_historico(Path(args.history), m, geral, extras)
    if not args.quiet:
        print(f"  histórico atualizado: {args.history}")

    if geral == FALHA:
        return 2
    if geral == ALERTA and args.strict:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())