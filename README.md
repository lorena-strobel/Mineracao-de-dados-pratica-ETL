# Laboratório de ETL — Mercatto Varejo

Projeto prático da disciplina de **Mineração de Dados** · IFMT · 2026/2

Quatro fontes heterogêneas, cerca de **1,9 milhão de registros**, um repositório
analítico a construir e uma pergunta preditiva a responder no Orange.

---

## 1. Requisitos

* Docker e Docker Compose (v2)
* 8 GB de RAM recomendados · 4 GB funcionam com `ESCALA=0.2`
* ~2 GB livres em disco
* [Orange Data Mining](https://orangedatamining.com/) instalado na máquina (não roda em contêiner)

## 2. Subir o ambiente

```bash
cp .env.example .env          # ajuste ESCALA se sua máquina for modesta
docker compose up -d --build
docker compose logs -f seed   # acompanhe a geração e a carga (~3 a 5 minutos)
```

Quando o serviço `seed` terminar com `ambiente pronto.`, está tudo no lugar.

### O que subiu

| Serviço | O que é | Acesso |
|---|---|---|
| `mysql_legado` | ERP legado, charset `latin1` | `localhost:3307` · `etl_ro` / `etl_ro` |
| `pg_ecommerce` | Plataforma de e-commerce, `UTF-8` | `localhost:5433` · `etl_ro` / `etl_ro` |
| `pg_dw` | Destino analítico (você escreve aqui) | `localhost:5434` · `postgres` / `postgres` |
| `adminer` | Inspeção pelo navegador | <http://localhost:8080> |
| `etl` | Contêiner de trabalho (Python) | `docker compose exec etl bash` |

As duas fontes de arquivo ficam em `./dados/`:
`atendimentos_sac.csv` e `avaliacoes_marketplace.json`.

> Os usuários das origens são **somente leitura**, de propósito. Corrigir o dado
> na origem não é uma opção disponível — como quase nunca é.

## 3. Estrutura

```
.
├── docker-compose.yml
├── dados/                    fontes de arquivo + CSVs de carga (gerados)
├── sql/                      DDL das origens e do DW
├── etl/                      onde vocês trabalham
│   ├── config.py             conexões e parâmetros analíticos (não alterar)
│   ├── 00_perfilamento.py    PRONTO — modelo de perfilamento
│   ├── 01_extracao.py        esqueleto
│   ├── 02_transformacao.py   esqueleto
│   ├── 03_carga_dw.py        esqueleto
│   ├── 04_abt.py             esqueleto (inclui o experimento de vazamento)
│   ├── 05_exportar_orange.py PRONTO — exporta a ABT para o Orange
│   └── qualidade/assercoes.py PRONTO — framework de asserções
├── saida/                    relatórios e CSVs para o Orange
└── docs/
    ├── DICIONARIO_DE_DADOS.md   incompleto, como na vida real
    └── MODELO_RDT.md            modelo do Registro de Decisões
```

## 4. Primeiro comando

```bash
docker compose exec etl python 00_perfilamento.py
```

Leia a saída inteira antes de escrever qualquer transformação.

## 5. Ordem de execução do pipeline

```bash
docker compose exec etl python 01_extracao.py
docker compose exec etl python 02_transformacao.py
docker compose exec etl python 03_carga_dw.py
docker compose exec etl python 04_abt.py --correta
docker compose exec etl python 04_abt.py --vazamento
docker compose exec etl python 05_exportar_orange.py
```

O pipeline precisa rodar do zero, na ordem, sem intervenção manual. Isso é
avaliado: `docker compose down -v && docker compose up -d --build` seguido dos
seis comandos acima tem de reproduzir exatamente o mesmo resultado.

## 6. Consultar as asserções

```sql
SELECT etapa, nome, valor_obtido, valor_esperado, aprovado, executado_em
FROM qa.execucao_assercao ORDER BY id DESC LIMIT 50;
```

## 7. Reiniciar do zero

```bash
docker compose down -v          # apaga volumes dos bancos
rm -rf dados saida              # apaga dados gerados
docker compose up -d --build
```

A semente do gerador é fixa: os dados voltam idênticos.

## 8. Problemas comuns

**`LOAD DATA LOCAL INFILE` recusado** — o `docker-compose.yml` já sobe o MySQL
com `--local-infile=1`. Se editou o arquivo, verifique.

**Acentos aparecem como `Ã§`** — você leu a base `latin1` com `utf8`. A conexão
correta está em `config.py`. O problema é de leitura, não do dado.

**`seed` terminou com erro** — `docker compose logs seed`. Para repetir a carga:
`docker compose run --rm seed python carregar.py --forcar`.

**Contêiner sem memória durante a geração** — use `ESCALA=0.2` no `.env`,
derrube tudo com `docker compose down -v` e suba de novo.

**Orange não abre o CSV** — use os arquivos de `./saida/`, que já vêm com o
cabeçalho de três linhas do Orange. Não use os CSVs de `./dados/`.
