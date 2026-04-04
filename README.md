# Processamento de Dados Geoespaciais - Painel do Fogo

Este repositório contém os scripts em Python para leitura, conversão e visualização de dados do Painel do Fogo, preparando a base para projeto de Aprendizado de Máquina para entrega do Mini Trabalho 2.

## Arquivos do Repositório

| Script | Descrição |
| :--- | :--- |
| **leituraDadosCSV.py** | Processa as geometrias e exporta os dados limpos para um arquivo tabular, ideal para a alimentação e treinamento do modelo preditivo. |
| **leituraDadosHTML.py** | Gera um mapa web interativo que permite a visualização visual dos polígonos e a inspeção das variáveis em cada foco. |
| **leituraDadosJSON.py** | Exporta a estrutura geométrica e seus atributos originais para o formato unificado GeoJSON. |

## Pré-requisitos

Certifique-se de ter o Python 3 instalado no seu sistema. Os arquivos brutos de geoprocessamento (`.shp`, `.dbf`, `.shx`, `.prj`, `.cpg`) devem estar no mesmo diretório dos scripts para que a leitura funcione corretamente. No caso desse repositório, eles estão no diretório "GO" com os dados do mês de abril de 2020.

## 1. Criando e ativando o ambiente virtual

É recomendável rodar os scripts dentro de um ambiente virtual para não gerar conflito com outras bibliotecas da sua máquina.

**No Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
```

**No Windows:**
```cmd
python -m venv venv
venv\Scripts\activate
```

## 2. Instalando as dependências

Com o seu ambiente virtual ativado, instale todas as bibliotecas necessárias lendo o arquivo de requisitos:

```bash
pip install -r requirements.txt
```

## 3. Executando os scripts

Para rodar qualquer um dos arquivos e gerar as exportações, basta chamá-los utilizando o interpretador do Python. 

**No Linux:**
```bash
python3 leituraDadosCSV.py
python3 leituraDadosHTML.py
python3 leituraDadosJSON.py
```

**No Windows:**
```cmd
python leituraDadosCSV.py
python leituraDadosHTML.py
python leituraDadosJSON.py
```

| Script | O que gera |
| :--- | :--- |
| **leituraDadosCSV.py** | Um arquivo `.csv` com os dados em formato de tabela, pronto para ser lido no projeto de Machine Learning. |
| **leituraDadosHTML.py** | Uma página `.html` contendo o mapa interativo para navegação visual direta no navegador. |
| **leituraDadosJSON.py** | Um arquivo `.geojson` padronizado, útil para plotar o mapa em plataformas web como o GitHub ou softwares como o QGIS. |