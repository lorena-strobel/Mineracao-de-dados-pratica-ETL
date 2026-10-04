# Gabarito do cenário — uso exclusivo do docente

> **Não distribuir.** Este documento lista o que foi plantado nos dados, em que
> proporção, e o que se espera que cada armadilha produza como aprendizagem.
> Sirva-se dele para corrigir o RDT e para saber se uma equipe travada está
> travada no ponto certo.

Semente do gerador: `20262`. Escala 1.0.

---

## 1. Ambiguidades semânticas (não têm resposta correta única)

### A1 · Identidade do cliente

Cerca de **33% dos clientes do legado** também existem no e-commerce (≈14.850
pessoas na escala 1.0). A ponte é o CPF, mas:

* ~8% dos CPFs estão ausentes em **cada** origem, de forma independente — logo,
  o pareamento por CPF alcança no máximo ≈85% dos sobrepostos;
* ~9% dos CPFs têm dígito verificador inválido, e o **mesmo** CPF inválido
  aparece nas duas bases quando a pessoa é a mesma;
* no legado o CPF aparece com máscara em ~88% dos casos e sem em ~4%.

**O que se espera:** que a equipe perceba que descartar CPF inválido custa
pareamentos legítimos, porque o erro de digitação foi propagado igual para os
dois sistemas. Um CPF inválido ainda é um identificador estável. Equipes que
filtram por validade antes de parear perdem cerca de 9% das uniões — e isso é
mensurável, o que torna a discussão concreta.

**Verificado na escala 1.0:** 41.400 CPFs distintos no legado, 78.142 no
e-commerce, **12.605 na interseção** — ou seja, o pareamento por CPF alcança
**84,9%** dos 14.850 clientes efetivamente sobrepostos. Os ~15% restantes só
aparecem por pareamento aproximado, com o risco de falso positivo que isso
carrega. Este par de números (84,9% de cobertura contra o risco de fundir
clientes distintos) é o núcleo da discussão da ficha RDT-02.

**Sinal de alerta na correção:** RDT que trata validade de CPF e utilidade de
CPF como a mesma propriedade.

### A2 · Cancelamento

| Legado | E-commerce |
|---|---|
| `CANCELADO` (12% dos pedidos) | `canceled` (8%) + `payment_declined` (5%) |

O legado agrega o que o e-commerce separa. Qualquer mapeamento perde alguma
coisa: ou a distinção, ou a simetria. **Não corrigir para uma resposta única.**
Avaliar a qualidade da justificativa e se a equipe declarou o que perdeu.

### A3 · Semântica do valor

* Legado: `VALOR_TOTAL` = soma dos itens **+ frete**
* E-commerce: `total_amount` = soma dos itens, **sem** frete

Verificável reconciliando com `ITENS_PEDIDO` / `order_item`. O dicionário de
dados não informa; há apenas o comentário solto *"cuidado com o VALOR_TOTAL"*.

**Esta é a armadilha mais silenciosa do cenário.** Uma equipe que não a detectar
produz um DW com valores inconsistentes entre os dois sistemas, e nada quebra:
o pipeline roda, o modelo treina, o número sai.

Verificado na escala 1.0 (reconciliação contra a soma dos itens, tolerância de
R$ 0,02):

| | bate com frete | bate sem frete |
|---|---|---|
| Legado (130.000 pedidos) | 130.000 | 24 |
| E-commerce (280.000 pedidos) | 0 | 280.000 |

Se ninguém achar até o fim da Semana 2, vale a provocação em aula: *"calculem,
nos dois sistemas, o valor do pedido menos a soma dos seus itens. No legado dá
o frete. No e-commerce dá zero. O que isso significa?"*

### A4 · Categoria de produto

Cerca de 25 valores distintos de texto livre no legado (de um vocabulário de 27)
contra taxonomia de dois níveis no e-commerce. Casos sem solução limpa:

* `informatica e games` — cobre dois ramos distintos;
* `TV E SOM` — cobre dois filhos de *Áudio e TV*;
* `DIVERSOS`, `OUTROS`, `''` — não informam nada;
* variantes de grafia do mesmo conceito: `ELETRO`, `Eletro`, `eletrodomesticos`,
  `ELETRODOMÉSTICOS`, `Eletro-domesticos`.

O último grupo é resolvível por normalização; os três primeiros, não.

---

## 2. Defeitos de qualidade (têm tratamento tecnicamente correto)

| Cód. | Defeito | Onde | Proporção |
|---|---|---|---|
| D1 | Itens sem pedido correspondente | ambas as origens | 1,5% dos itens |
| D2 | `DT_ENTREGA` anterior a `DT_PEDIDO` | ambas | 0,8% dos entregues |
| D3 | Frete negativo | ambas | 0,3% dos pedidos |
| D3b | `tempo_resolucao_horas` negativo | SAC | 0,4% |
| D4 | CPF com dígito verificador inválido | legado ~9%, ecom ~9% | — |
| D4b | CPF ausente | ambas | 8% |
| D5 | Duplicata exata de cliente | legado | 2% |
| D5b | Duplicata aproximada (acento/espaço/máscara) | legado | 3% |
| D6 | Sentinela `1900-01-01` em `DT_ENTREGA` | legado | 1,0% |
| D6b | Sentinela `N/A` em `CIDADE` | legado | 2% |
| D6c | Sentinela `-1` em `VL_DESCONTO` | legado | 1,0% |
| D7 | Preço 10× por erro de digitação | ambas | 0,15% dos produtos |
| D8 | Linhas inteiras repetidas | SAC | 1,2% |
| D9 | Encoding `latin-1` | SAC e MySQL | 100% |
| D10 | Quebra de linha dentro de campo | SAC | 1,5% |
| D11 | `rating` ora `int`, ora `str` | JSON | 10% como string |
| D11b | `rating` ausente (chave omitida) | JSON | 3% |
| D11c | `submitted_at` sem fuso horário | JSON | 20% |
| D12 | Chaves opcionais omitidas no JSON | JSON | `title` 15%, `comment` 30%, `verified_purchase` 10%, `helpful_votes` 45% |

Conferência rápida das proporções:

```bash
docker compose exec etl python - <<'PY'
import pandas as pd
from sqlalchemy import text
from config import eng_mysql
with eng_mysql().connect() as cx:
    print(pd.read_sql(text("""
      SELECT SUM(DT_ENTREGA='1900-01-01 00:00:00') sentinela,
             SUM(VALOR_FRETE < 0)                  frete_neg,
             SUM(DT_ENTREGA IS NOT NULL AND DT_ENTREGA < DT_PEDIDO
                 AND YEAR(DT_ENTREGA) > 1900)      entrega_antes,
             COUNT(*)                              total
      FROM PEDIDOS"""), cx))
PY
```

---

## 3. O experimento de vazamento

`DATA_CORTE = 2025-06-30`, janela do alvo até `2025-09-28`.
Taxa de recompra esperada no alvo: **entre 0,30 e 0,45** (varia conforme o
tratamento de cancelados que a equipe adotar).

Ordem de grandeza esperada na comparação (AUC, Naive Bayes, partição 70/30):

* ABT correta: **0,62 a 0,72**
* ABT com vazamento em `recencia_dias` e `frequencia_pedidos`: **0,93 a 0,99**

O salto é grande o bastante para ser óbvio e, justamente por isso, é o momento
didático do projeto. A pergunta a fazer na defesa não é *"qual deu melhor?"*,
mas **"se você tivesse recebido só o segundo resultado, como descobriria que
ele está errado?"**.

Vazamento sutil a exigir de todos: normalizar (z-score) um atributo usando
média e desvio de toda a base antes da partição. O ganho de AUC é pequeno
(tipicamente 0,01 a 0,03) e é isso que o torna perigoso — não chama atenção.

---

## 4. Onde as equipes costumam travar

| Sintoma | Causa provável | Intervenção sugerida |
|---|---|---|
| Acentos corrompidos | leram `latin1` como `utf8` | não entregue a resposta; mande comparar o byte no `hexdump` |
| Contagem de itens explode | junção pedido × item sem verificar cardinalidade | `qa.cardinalidade_preservada` |
| ABT com poucas linhas | `INNER JOIN` onde cabia `LEFT` | peça para contar os clientes-base antes da junção |
| Taxa do alvo perto de 0 ou 1 | janela ou filtro de status errado | conferir `SQL_ALVO` contra o mapeamento próprio |
| Pipeline não reexecuta | `if_exists='append'` sem truncar | exigir a demonstração de `down -v` na defesa |

---

## 5. Sugestão de calibragem

Se a turma for grande ou o tempo apertar, dá para reduzir o escopo sem
descaracterizar o projeto:

* **corte mais leve:** dispensar `fato_avaliacao` (o JSON continua sendo
  perfilado na Semana 1, mas não entra no DW);
* **corte médio:** dispensar `fato_item_pedido`, mantendo só o grão de pedido —
  perde-se a discussão de granularidade dupla, que é valiosa;
* **não cortar:** o experimento de vazamento e o RDT. São o centro do projeto.

---

## 6. Verificação do kit (executada na montagem)

| Item | Resultado |
|---|---|
| Geração escala 1.0 | 2.205.843 registros · 44 s · 143 MB |
| Carga MySQL (`LOAD DATA LOCAL INFILE`, latin1) | 4,2 s · 4 tabelas |
| Carga PostgreSQL (`COPY`, UTF-8) | 8,5 s · 5 tabelas |
| DDL das três bases | executam sem erro; idempotentes |
| `docker compose config` | válido |
| Encoding | `legado_*.csv` e `atendimentos_sac.csv` em ISO-8859-1; demais em UTF-8 |
| Acentos após carga | íntegros com conexão `charset=latin1` |
| Determinismo | semente fixa `20262`; mesma geração a cada execução |

Volumes na escala 1.0:

| Fonte | Registros |
|---|---|
| `loja_legado.CLIENTES` | 47.250 (inclui 2% de duplicatas exatas e 3% aproximadas) |
| `loja_legado.PRODUTOS` | 3.000 |
| `loja_legado.PEDIDOS` | 130.000 |
| `loja_legado.ITENS_PEDIDO` | 397.086 |
| `shop.customer` | 85.000 |
| `shop.product` | 12.000 |
| `shop.orders` | 280.000 |
| `shop.order_item` | 995.367 |
| `atendimentos_sac.csv` | 96.140 linhas |
| `avaliacoes_marketplace.json` | 160.000 objetos |
