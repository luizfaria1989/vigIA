# vigIA — Documentação do PBL
**Previsão de Risco de Queimadas no Estado de Goiás**  
**Disciplina:** FGA0083 — Aprendizado de Máquina | UnB | 2026-1 | Turma 01 | Grupo 3  
**Data:** 2026-06-03

## Membros do Grupo
- Felipe de Jesus Rodrigues — 211062867
- João Paulo Barros de Cristo — 202023805
- Guilherme Aguera de la Fuente Vilela — 190088168
- Luiz Guilherme Morais da Costa Faria — 231011696

---

## 1. Contexto e Motivação

### 1.1 O que foi feito nos Mini Trabalhos anteriores
Nos MTs 4, 5 e 6 foi desenvolvido um modelo de **regressão** para prever o `FRP_log` (Fire Radiative Power em escala logarítmica) de focos de incêndio já detectados pelo satélite. O melhor resultado foi:

- **Random Forest:** R² = 0.7282 no conjunto holdout (após otimização no MT6)

### 1.2 Limitação identificada
O modelo de regressão tem valor limitado em produção porque o BDqueimadas/INPE já fornece o FRP medido pelo satélite junto com todas as outras colunas usadas como features. Ou seja, quando você tem os dados para rodar o modelo, já tem a resposta que ele prevê.

### 1.3 Redefinição do problema
Para o PBL, o problema foi redefinido para algo genuinamente útil:

> **"Dado o histórico de queimadas e as condições climáticas atuais, quais áreas de Goiás têm maior probabilidade de registrar focos de incêndio nos próximos dias?"**

Isso é **classificação binária** por unidade geográfica por dia, **antes** de qualquer foco existir.

---

## 2. Arquitetura do Sistema: Dois Estágios Independentes

Os dois modelos rodam de forma **independente** com as mesmas features climáticas. Ambos são executados diariamente pelo cron job. O "dois estágios" é uma decisão de **apresentação ao usuário**, não de pipeline em cascata (a saída do modelo 1 não entra no modelo 2).

```
Cron job diário
    │
    ├─► Modelo 1 (municipio_full.pkl)
    │     Features climáticas por município → P(fogo) × 247 municípios
    │     Saída: ranking — "NIQUELÂNDIA 98%, CAVALCANTE 95%..."
    │
    └─► Modelo 2 (grade_full.pkl)
          Features climáticas por célula → P(fogo) × 2.976 células
          Saída: probabilidade para cada célula 0.1° de Goiás

Frontend (apresentação em dois estágios):
  Estágio 1 → ranking de municípios (visão geral, alerta regional)
  Estágio 2 → usuário clica num município → zoom no mapa
               células daquele município coloridas por risco relativo
```

```
┌─────────────────────────────────────────────────────────┐
│  ESTÁGIO 1 — Modelo de Município (triagem regional)     │
│  Unidade: 247 municípios de Goiás                       │
│  Modelo:  modelos/municipio_full.pkl (LightGBM)         │
│  AUC:     0.816 (validação Jan-Jun 2026)                │
│  Pergunta: "QUAIS municípios estão em risco?"           │
└─────────────────────────────────────────────────────────┘
                    roda em paralelo ↕ (independente)
┌─────────────────────────────────────────────────────────┐
│  ESTÁGIO 2 — Modelo de Grade Espacial (drill-down)      │
│  Unidade: 2.976 células 0.1° × 0.1° (~11km × 11km)     │
│  Modelo:  modelos/grade_full.pkl (LightGBM)             │
│  AUC:     0.715 (validação 2026 com clima proxy)        │
│  Pergunta: "ONDE dentro do município?"                  │
└─────────────────────────────────────────────────────────┘
```

**Por que dois estágios em vez de um só?**

| Aspecto | Município | Grade 0.1° |
|---|---|---|
| AUC validação 2026 | 0.816 | 0.715 |
| Unidades | 247 | 2.976 |
| Resolução geográfica | ~50km | ~11km |
| Custo computacional | Baixo | Alto |
| Uso em produção | Alerta diário | Visualização, planejamento |

O modelo de município é mais preciso porque cada município agrega muitos focos históricos (sinal forte). O modelo de grade é menos preciso mas oferece localização dentro do município — crucial para operações de campo.

No estágio 2, o sistema usa **ranking relativo dentro do município** (não probabilidade absoluta), o que é robusto a problemas de calibração.

---

## 3. Fonte de Dados

**BDqueimadas / INPE** — Sistema de monitoramento de queimadas por satélite  
- Escopo: Estado de Goiás | 2015–2025  
- Registros brutos: 1.390.827 focos detectados  
- Após filtro (Goiás + remoção Mata Atlântica): **1.354.326 registros | 247 municípios**

**Open-Meteo Archive API** — Dados climáticos históricos gratuitos (sem autenticação)  
- Precipitação diária por coordenada geográfica
- Período: 2015–2025 + Janeiro–Junho 2026

---

## 4. Estágio 1 — Modelo de Município

### 4.1 Construção do Dataset (Fase 1)

**Estratégia para exemplos negativos:**

O BDqueimadas registra **apenas** dias com foco detectado. Para treinar um classificador binário são necessários exemplos de dias **sem** fogo. A premissa adotada:

> **Ausência de registro no BDqueimadas = ausência de foco detectado naquele município naquele dia.**

Isso é válido porque o sistema de satélites cobre Goiás continuamente.

**Geração dos exemplos:**

```
247 municípios × 4.018 dias (2015-2025) = 992.446 combinações
992.446 − 143.067 positivos = 849.379 negativos (naturais, sem amostragem)
```

| Classe | Registros | % |
|---|---|---|
| fogo = 1 | 143.067 | 14,4% |
| fogo = 0 | 849.379 | 85,6% |
| **Total** | **992.446** | 100% |

**Features do modelo:**

| Feature | Tipo | Fonte |
|---|---|---|
| `Mes` | Temporal | Data |
| `DiaSemana` | Temporal | Data |
| `Estacao_Seca` | Temporal | Mes ∈ {6,7,8,9,10} → 1 |
| `Latitude` | Geográfica | Centroide do município |
| `Longitude` | Geográfica | Centroide do município |
| `Municipio_Freq` | Histórica | Focos do município / total Goiás |
| `DiaSemChuva` | Climática | Dias consecutivos < 0.1mm (Open-Meteo) |
| `Precipitacao` | Climática | Precipitação diária em mm (Open-Meteo) |
| `media_focos_mes_hist` | Histórica | Média histórica de focos por município+mês |

### 4.2 Modelagem (Fase 2)

**Split temporal obrigatório** (random split causaria data leakage):

| Conjunto | Período | Registros |
|---|---|---|
| Treino | 2015–2022 | 721.734 |
| Validação | 2023 | 90.155 |
| Teste | 2024–2025 | 180.557 |

**Busca de hiperparâmetros:** RandomizedSearchCV em subsample de 200k + retreino no conjunto completo.

| Modelo | AUC Val | AUC Teste | Recall Teste | Precisão Teste |
|---|---|---|---|---|
| **LightGBM** | 0,8412 | **0,8350** | **0,750** | 0,329 |
| XGBoost | 0,8411 | 0,8343 | 0,710 | 0,350 |
| Random Forest | 0,8382 | 0,8297 | 0,740 | 0,326 |

**Modelo selecionado: LightGBM** — maior AUC + maior Recall.

**Melhores hiperparâmetros:**
```python
LGBMClassifier(
    n_estimators=200, learning_rate=0.05, num_leaves=50,
    max_depth=-1, subsample=1.0, colsample_bytree=0.8,
    class_weight='balanced', random_state=42
)
```

### 4.3 Retreino e Validação com 2026 (Fase 3)

Retreinado nas 992.446 amostras completas (2015–2025) → `modelo_pbl_full.pkl`

**Validação com dados reais nunca vistos (Jan–Jun 2026):**

| Métrica | Valor |
|---|---|
| AUC-ROC | **0,816** |
| Recall (@0,5) | 47,4% |
| Recall (@0,3) | 73,8% |
| Precisão (@0,3) | 12,7% |

O recall cai em Jan–Jun porque é a estação chuvosa — focos são raros (4,9% dos dias vs 14% no treino). O **AUC de 0,816** confirma que a ordenação dos municípios permanece correta mesmo na chuva.

### 4.4 Sistema de Previsão 5 Dias (Fase 4)

Para cada previsão diária:
1. **Open-Meteo Archive** (30 dias) → DiaSemChuva acumulado atual
2. **Open-Meteo Forecast** (5 dias) → precipitação prevista
3. **Projeção de DiaSemChuva** para cada dia futuro
4. `modelo_pbl_full.pkl.predict_proba()` → probabilidade por (município, dia)
5. Ranking final dos 247 municípios

**Resultado (04–08/06/2026):**
- NIQUELÂNDIA lidera todos os dias (95–98%) — 12–14 dias sem chuva
- 24–38 municípios em ALTO risco por dia

---

## 5. Estágio 2 — Modelo de Grade Espacial

### 5.1 Motivação

O modelo de município diz *qual município* está em risco, mas não *onde dentro do município*. Um município goiano pode ter 3.000–15.000 km² — informação insuficiente para operações de campo.

A grade espacial divide Goiás em células de **0,1° × 0,1° (~11km × 11km)**, com 2.976 células que tiveram ao menos 5 focos históricos.

### 5.2 Construção do Dataset de Grade (Fase 1 Grade)

**Diferença crítica em relação ao dataset de município:**  
Na primeira tentativa usamos `NEG_RATIO=4` (4 negativos por positivo por célula), o que inflou a taxa de positivos para 20%. Na validação com 2026 (estação chuvosa, 0.5% de positivos), a calibração ficou completamente errada → AUC 0.69.

**Solução: negativos naturais completos** — produto cruzado de todas as células por todos os dias, sem amostragem:

```
2.976 células × 3.652 dias = 10.872.252 combinações possíveis
10.872.252 − 249.284 positivos = 10.622.968 negativos
```

| Classe | Registros | % |
|---|---|---|
| fogo = 1 | 249.284 | 2,1% |
| fogo = 0 | 11.708.284 | 97,9% |
| **Total** | **11.957.568** | 100% |

Gerado em chunks anuais (~1M linhas/ano) para controle de memória.

**Features do modelo de grade:**

| Feature | Tipo | Diferença do município |
|---|---|---|
| `Mes`, `DiaSemana`, `Estacao_Seca` | Temporal | Igual |
| `Cell_Lat`, `Cell_Lon` | Geográfica | Centro da célula (não centroide de município) |
| `Cell_Freq` | Histórica | Focos da célula / total Goiás |
| `DiaSemChuva`, `Precipitacao` | Climática | Via município proxy (temporário) |
| `media_focos_mes_hist` | Histórica | Média por célula+mês |

**Clima atual:** cada célula usa o dado do município com centroide mais próximo (proxy). Isso introduz imprecisão de até ~80km. A correção (clima 0.5° exato) está pendente — ver Seção 5.5.

### 5.3 Modelagem da Grade (Fase 2 Grade)

| Modelo | AUC Val | AUC Teste | Recall Teste |
|---|---|---|---|
| XGBoost (GPU) | 0,8147 | **0,8356** | 0,771 |
| **LightGBM** | 0,8136 | 0,8348 | **0,769** |
| Random Forest | 0,8112 | 0,8330 | 0,757 |

XGBoost ficou ligeiramente acima por usar GPU (GTX 1650). LightGBM foi selecionado por ter recall comparável e ser mais flexível para produção (não requer CUDA).

**Melhores hiperparâmetros LightGBM grade:**
```python
LGBMClassifier(
    n_estimators=200, learning_rate=0.01, num_leaves=31,
    max_depth=10, subsample=0.8, colsample_bytree=1.0,
    class_weight='balanced', random_state=42
)
```

### 5.4 Retreino e Validação com 2026 (Fase 3 Grade)

Retreinado em 11.957.568 amostras (2015–2025) → `modelo_grade_full.pkl`

| Métrica | Município | Grade (clima proxy) |
|---|---|---|
| AUC-ROC 2026 | **0,816** | 0,715 |
| Recall @0,5 | **47,4%** | 27,3% |
| Recall @0,3 | **73,8%** | 54,7% |

O gap em relação ao município tem duas causas estruturais:
1. **Estação chuvosa:** taxa real 0,5% vs 2,1% no treino (gap de 4× vs 3× no município)
2. **Clima proxy:** imprecisão de até 80km nas features DiaSemChuva e Precipitacao

Ambas serão reduzidas com o clima 0.5° exato (ver Seção 5.5).

### 5.5 Pendência: Clima por Grade 0.5° (amanhã)

Em vez de baixar clima para as 2.976 células (2h+, rate limit inviável), usamos uma grade climática intermediária:

| Estratégia | Chamadas API | Erro máximo | Tempo |
|---|---|---|---|
| Município proxy | 247 | ~80km | 6 min |
| **Grade 0.5°** | **148** | **~35km** | **~10 min** |
| Por célula 0.1° | 2.976 | ~0km | 2h+ (rate limit) |

A grade 0.5° cobre todas as células com 148 pontos únicos. Cada célula 0.1° usa o ponto 0.5° mais próximo. Isso é **mais preciso que município** e **mais rápido**. Para retomar:

```bash
nohup bash /tmp/pipeline_clima2.sh &
```

### 5.6 Previsão 5 Dias — Grade (Fase 4 Grade)

**Modo offline** (`fase4_grade_offline.py`): reutiliza `previsao_2026-06-03.csv` (município) como proxy climático — sem novas chamadas à API. Adequado para demonstração e desenvolvimento.

**Modo produção** (`fase4_grade_previsao.py`): baixa Archive + Forecast para os municípios proxy únicos das células (~6 min, mesmo pipeline do estágio 1).

---

## 6. Frontend — Mapa Interativo

Gerado por `gerar_mapa.py` → `mapa_vigia.html` (HTML standalone, sem servidor necessário).

**Tecnologias:** Leaflet.js + Esri World Imagery (satélite, sem API key)

**Funcionalidades:**
- Células 0.1° × 0.1° como retângulos coloridos sobre imagem de satélite
- Cores: ALTO ≥70% (vermelho), MÉDIO 40–70% (laranja), BAIXO <40% (verde)
- **Hover:** tooltip com probabilidade, risco, dias sem chuva, município proxy
- **Clique:** popup completo
- Seletor de 5 dias de previsão
- Slider de probabilidade mínima (filtra células abaixo do limiar)
- Card de resumo (ALTO/MÉDIO/BAIXO por dia)

---

## 7. Abordagem: Ranking por Probabilidade

Em vez de um limiar binário fixo ("vai ter fogo? sim/não"), o sistema usa os modelos como **ferramentas de ranqueamento**:

- **Estágio 1:** ordena os 247 municípios por probabilidade → gestor vê os mais arriscados no topo
- **Estágio 2:** ordena as células dentro de cada município de alto risco → identifica subáreas críticas

**Vantagem do ranking:** o AUC garante que a ordenação está correta independentemente do limiar. AUC = 0,816 significa que em 81,6% das comparações (município com fogo vs sem fogo), o modelo classifica corretamente qual tem maior risco.

---

## 8. Arquitetura de Produção

```
Cron Job (diário, 06h)
    │
    ├─► Open-Meteo Archive + Forecast (247 municípios, ~6 min)
    │       ↓
    │   Calcular DiaSemChuva projetado para os próximos 5 dias
    │       ↓
    ├─► modelos/municipio_full.pkl  →  P(fogo) × 247 municípios
    │       ↓ resultados/previsao_municipio_<data>.csv
    │
    ├─► modelos/grade_full.pkl  →  P(fogo) × 2.976 células
    │   (usa clima de município como proxy — 0 chamadas extras à API)
    │       ↓ resultados/previsao_grade_<data>.csv
    │
    └─► frontend/mapa_vigia.html ← usuário abre no navegador
```

**Nota importante:** os dois modelos são **independentes**. O modelo de grade usa os mesmos dados climáticos dos municípios proxy (sem novas chamadas à API), então o custo de produção diário é o mesmo: ~6 minutos de API para 247 municípios.

**Próximo passo planejado:** FastAPI com endpoints:
- `GET /risco/municipios?dias=5` → ranking do estágio 1
- `GET /risco/grade?municipio=NIQUELÂNDIA` → células daquele município ordenadas por risco

---

## 9. Arquivos Gerados

### Estágio 1 — `estagio1_municipio/`
| Arquivo | Descrição |
|---|---|
| `fase1_dataset.py` | Constrói dados/dataset_municipio.csv |
| `fase1b_clima.py` | Baixa Open-Meteo histórico (247 municípios) |
| `fase2_modelagem.py` | Treina RF, XGBoost, LightGBM com busca de hiperparâmetros |
| `fase3_validacao_2026.py` | Retreino completo + validação com dados reais 2026 |
| `fase4_previsao_5dias.py` | Previsão dos próximos 5 dias por município |

### Estágio 2 — `estagio2_grade/`
| Arquivo | Descrição |
|---|---|
| `fase1_dataset_grade.py` | Constrói dados/dataset_grade.csv (negativos naturais) |
| `fase1b_clima_05graus.py` | Baixa clima 0.5° (148 pontos) — executar amanhã |
| `fase1c_aplicar_clima.py` | Substitui clima proxy pelo exato no dataset |
| `fase2_modelagem.py` | Treina modelos na grade |
| `fase3_validacao_2026.py` | Retreino completo + validação 2026 grade |
| `fase4_previsao_offline.py` | Previsão 5 dias sem API (usa previsão de município) |

### Frontend — `frontend/`
| Arquivo | Descrição |
|---|---|
| `gerar_mapa.py` | Gera mapa_vigia.html a partir de resultados/previsao_grade_*.csv |
| `mapa_vigia.html` | Mapa interativo standalone (Leaflet + satélite Esri) |

### Dados — `dados/`
| Arquivo | Descrição |
|---|---|
| `dataset_municipio.csv` | 992.446 linhas, fogo=0/1, 2015–2025 |
| `dataset_grade.csv` | 11.957.568 linhas, 2.976 células, 2015–2025 |
| `mapeamento_municipio.csv` | 247 municípios, freq + centroide lat/lon |
| `mapeamento_grade.csv` | 2.976 células + freq + município proxy |
| `clima_historico.csv` | Precipitação diária 2015–2025, Open-Meteo |
| `clima_2026.csv` | Precipitação Jan-Jun 2026, Open-Meteo |
| `clima_grade.csv` | Clima por célula 0.1° via grade 0.5° (pendente) |

### Modelos — `modelos/`
| Arquivo | Descrição |
|---|---|
| `municipio_full.pkl` | LightGBM 2015–2025, AUC 0.816 (**produção estágio 1**) |
| `grade_full.pkl` | LightGBM grade 2015–2025, AUC 0.715 (**produção estágio 2**) |
| `municipio_avaliacao.pkl` | LightGBM 2015–2022 (split temporal, avaliação) |
| `grade_avaliacao.pkl` | LightGBM grade 2015–2022 (split temporal, avaliação) |

### Resultados — `resultados/`
| Arquivo | Descrição |
|---|---|
| `resultados_municipio_fase2.csv` | Métricas dos 3 modelos (município) |
| `resultados_grade_fase2.csv` | Métricas dos 3 modelos (grade) |
| `validacao_municipio_2026.csv` | Métricas de validação 2026 (município) |
| `validacao_grade_2026.csv` | Métricas de validação 2026 (grade) |
| `previsao_municipio_<data>.csv` | Ranking 5 dias por município |
| `previsao_grade_<data>.csv` | Ranking 5 dias por célula |

---

## 10. Decisões Técnicas Relevantes

| Decisão | Motivo |
|---|---|
| Classificação em vez de regressão | FRP já é medido — regressão não agrega valor em produção |
| Ausência = negativo (BDqueimadas) | Satélite cobre Goiás continuamente |
| Split temporal | Random split vaza dados futuros no treino |
| Subsample 200k para busca | RandomizedSearchCV inviável em 720k+ amostras |
| n_jobs=1 no estimador interno | Nested parallelism travou processo por 30+ minutos |
| Negativos naturais completos (grade) | NEG_RATIO=4 inflou positivos para 20%, causou AUC 0.69 |
| Grade climática 0.5° | 148 pontos vs 2.976: sem rate limit, erro máx ~35km |
| Ranking relativo no estágio 2 | Calibração absoluta ruim na chuva; ranking interno é robusto |
| Dois estágios complementares | Município: triagem confiável; grade: localização operacional |

---

## 11. Conclusões

O sistema vigIA combina dois modelos LightGBM em estágios complementares:

**Estágio 1 (município, AUC 0,816):** identifica com alta confiança quais dos 247 municípios de Goiás estão em risco nos próximos 5 dias. Num contexto de apoio ao combate a incêndios, permite priorização de recursos e antecipação antes da detecção satelital.

**Estágio 2 (grade 0,1°, AUC 0,715):** detalha a localização do risco dentro dos municípios de alto risco, com resolução de ~11km × 11km. Mesmo com AUC menor (estação chuvosa + clima proxy), o ranking relativo entre células é útil para planejamento de campo.

A combinação dos dois estágios torna o sistema operacionalmente completo: do alerta regional à localização aproximada — tudo com dados abertos (BDqueimadas + Open-Meteo) e sem custo de infraestrutura.
