# Plano de Monitoramento — vigIA

**Projeto:** vigIA — Previsão de Risco de Incêndio em Goiás
**Disciplina:** FGA0083 — Aprendizado de Máquina · UnB 2026-1 · Turma 01 · Grupo 4
**Equipe:** Felipe Rodrigues · João Paulo Cristo · Guilherme Vilela · Luiz Guilherme Faria
**Documento:** Critério 2 — Plano de monitoramento em produção

---

## 1. Objetivo e princípios

Este plano define como o desempenho e a saúde do vigIA são acompanhados após o lançamento. O objetivo é detectar precocemente três classes de problema — falha operacional, degradação de dados e degradação do modelo — antes que afetem os usuários (Defesa Civil, brigadas, fiscalização e público).

Princípios adotados: **automação** (as métricas são coletadas pelo próprio pipeline, sem trabalho manual diário), **limiares explícitos** (cada métrica tem um valor de alerta e uma ação associada), **histórico** (toda execução é registrada para análise de tendência) e **separação de severidade** (distinção entre ALERTA, que notifica, e FALHA, que aciona a equipe).

## 2. As camadas de monitoramento

**Camada 1 — Saúde do sistema (operacional).** Garante que o sistema rodou e publicou.
Itens: sucesso/falha da execução do GitHub Actions; frescor do boletim (idade de `gerado_em`); disponibilidade da Vercel; disponibilidade das APIs de origem.

**Camada 2 — Qualidade dos dados.** Garante que o boletim publicado é íntegro.
Itens: cobertura de municípios (% sobre os 244 em escopo); ausência de valores faltantes/inválidos; probabilidades dentro de [0,1]; rótulos de risco válidos; respeito ao escopo geográfico (Gouvelândia e São Simão ausentes).

**Camada 3 — Saída do modelo.** Detecta anomalias na própria predição.
Itens: distribuição das classes de risco (BAIXO/MÉDIO/ALTO); variância da probabilidade (variância ~0 indica saída constante, provável bug); detecção de saída integralmente nula.

**Camada 4 — Desempenho preditivo (backtest).** Mede se o modelo está acertando.
Itens: comparação das previsões com os focos efetivamente detectados pelo INPE, com segmentação por estação (seca vs chuvosa), pois o sistema reconhecidamente erra mais na estação chuvosa.

## 3. Catálogo de métricas, limiares e ações

| Métrica | Camada | Frequência | Limiar de ALERTA | Limiar de FALHA | Ação |
|---|---|---|---|---|---|
| Execução do pipeline (Actions) | 1 | Diária | — | Falha do job | Notificar equipe; reprocessar via `workflow_dispatch` |
| Idade do boletim (`gerado_em`) | 1 | Diária | > 24h | > 48h | Investigar Actions/Open-Meteo; manter boletim anterior |
| Disponibilidade da app (Vercel) | 1 | Contínua | Latência alta | Fora do ar | Rollback do deploy na Vercel |
| Cobertura de municípios | 2 | Diária | < 98% | < 90% | Verificar API climática; investigar falha parcial |
| Probabilidades inválidas | 2 | Diária | — | > 0 | Bloquear publicação (gate); corrigir pipeline |
| Rótulos de risco inválidos | 2 | Diária | — | > 0 | Bloquear publicação; corrigir mapeamento |
| Municípios fora de escopo | 2 | Diária | — | > 0 | Corrigir filtro de bioma |
| Variância da probabilidade | 3 | Diária | — | ≈ 0 | Investigar modelo/inferência (saída constante) |
| % de municípios em ALTO | 3 | Diária | > 70% | — | Revisar limiares; checar features climáticas |
| Hit-rate@10 (backtest) | 4 | Semanal | < 0,30 | < 0,15 | Investigar drift; planejar retreino |
| AUC / Brier (backtest) | 4 | Mensal | abaixo da baseline sazonal | queda sustentada | Reavaliar features; acionar retreino |

## 4. Instrumentação

O monitoramento das camadas 1 a 4 é operacionalizado pelo script `monitor_forecast.py` (apenas biblioteca padrão, executa no GitHub Actions sem dependências). Ele:

- carrega o `forecast.json`, calcula todas as métricas acima e atribui status `OK`/`ALERTA`/`FALHA` por checagem, mais um **status geral** (o pior entre todas);
- imprime um **relatório legível** no terminal (capturado nos logs do Actions);
- registra cada execução em um **histórico CSV** (`metrics_history.csv`) — a fonte de dados do dashboard;
- opcionalmente grava um **snapshot JSON** (`--out metrics.json`) para painéis e automação;
- opcionalmente executa o **backtest** de desempenho (`--observados focos.json`), calculando hit-rate@10 e *lift* sobre o aleatório;
- retorna **código de saída** (0 = OK, 1 = ALERTA com `--strict`, 2 = FALHA), permitindo acionar alertas automaticamente.

Exemplo de uso em produção:

```bash
python monitor_forecast.py --out metrics.json --history metrics_history.csv
python monitor_forecast.py --observados focos_inpe.json   # quando houver dados observados
```

Complementarmente, os **logs do GitHub Actions** registram sucesso/falha de cada etapa do pipeline, e a Vercel fornece o status de cada deploy.

## 5. Dashboard

O histórico CSV alimenta um painel de tendência. Não é necessária infraestrutura dedicada: uma planilha (Google Sheets/Excel) com uma linha por dia já cumpre o papel, com gráficos de:

- **idade do boletim** ao longo do tempo (saúde operacional);
- **cobertura de municípios** (qualidade de dados);
- **% em ALTO** e **probabilidade média** (estabilidade da saída);
- **hit-rate@10** ao longo das semanas, segmentado por estação (desempenho).

Opcionalmente, uma página HTML simples pode ler o `metrics.json` e renderizar os mesmos indicadores. O print do painel compõe a pasta de evidências da entrega.

## 6. Alertas e escalonamento

| Severidade | Gatilho | Canal | Responsável | Prazo de resposta |
|---|---|---|---|---|
| FALHA | Status geral = FALHA ou job do Actions falhou | Notificação do GitHub Actions / e-mail da equipe | Plantonista da semana | No mesmo dia |
| ALERTA | Status geral = ALERTA (ex.: boletim entre 24h e 48h) | Registro no histórico + aviso no grupo | Plantonista da semana | Até 48h |
| Informativo | Tendência adversa em métrica de desempenho | Revisão semanal | Equipe | Próxima revisão |

O escalonamento de FALHA segue o runbook descrito no documento de Estratégia de Manutenção.

## 7. Monitoramento de desempenho do modelo (backtest)

Como o `forecast.json` contém apenas previsões, a avaliação de desempenho requer confrontá-las com os focos **realmente observados** pelo INPE. O procedimento:

1. coletar, para cada dia previsto, a lista de municípios que registraram foco (BDqueimadas);
2. comparar com os 10 municípios de maior risco previstos para aquele dia;
3. calcular **hit-rate@10** (fração dos top-10 que de fato tiveram foco) e o **lift** sobre uma seleção aleatória;
4. acompanhar, em janelas semanais e mensais, métricas probabilísticas como **AUC** e **Brier score**;
5. **segmentar por estação** (seca vs chuvosa), reconhecendo a maior incerteza no período chuvoso.

Uma queda sustentada dessas métricas é o principal gatilho de retreino (ver Estratégia de Manutenção).

## 8. Cadência de revisão

- **Diária (automática):** camadas 1–3 a cada execução do pipeline; status geral nos logs.
- **Semanal:** revisão do hit-rate@10 e da tendência do histórico pelo plantonista.
- **Mensal:** revisão de AUC/Brier, análise de drift e decisão sobre retreino.
- **Sazonal:** reavaliação dos limiares antes do início da estação seca, período de maior demanda.