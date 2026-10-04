# Registro de Decisões de Transformação (RDT)

**Equipe:** ____________________  **Data:** ______  **Versão do pipeline:** ______

Este é o artefato central do projeto e vale **30% da nota**. Ele não descreve o
que o código faz — o código já faz isso. Ele registra **por que** cada decisão
foi tomada, **o que se perdeu** ao tomá-la e **quantos registros** foram
afetados.

Uma decisão sem consequência declarada e sem número não conta como registrada.

---

## Como preencher

Uma ficha por decisão. Use o modelo abaixo. Ao final, a tabela-resumo.

---

## Ficha RDT-000 (exemplo preenchido)

**Decisão:** tratamento de `DT_ENTREGA = '1900-01-01'` no sistema legado.

**Etapa do pipeline:** 02_transformacao · `trata_datas_e_ausencias`

**O que o dado mostrava:** 1.284 pedidos (0,99% do legado) com data de entrega
exatamente `1900-01-01 00:00:00`. Desses, 1.281 têm `STATUS = 'ENTREGUE'`.
Nenhum pedido com outro status apresenta esse valor.

**Alternativas consideradas:**

1. Tratar como data válida. Descartada: produziria `dias_entrega` de cerca de
   45 mil dias, contaminando qualquer média.
2. Converter para `NULL`. Perde a distinção entre "entrega sem data registrada"
   e "pedido que não foi entregue".
3. Converter para `NULL` **e** criar o indicador `entrega_sem_data` (booleano),
   preservando a informação de que houve falha de registro.

**Decisão:** alternativa 3.

**Justificativa:** `1900-01-01` é sentinela, não data — nenhuma entrega
ocorreu em 1900. Mas o fato de o registro ter falhado pode ser informativo
(pedidos com falha de registro logístico podem concentrar problemas de
atendimento). Converter para `NULL` sem o indicador apagaria essa hipótese
antes de poder testá-la.

**O que se perde:** a data real da entrega, que é irrecuperável. Qualquer
métrica de prazo passa a excluir esses pedidos, o que enviesa levemente o prazo
médio para baixo se as falhas de registro se concentrarem em entregas lentas.
Não há como verificar isso com os dados disponíveis.

**Registros afetados:** 1.284 pedidos (0,99% do legado; 0,31% do DW).

**Asserção associada:** `dias_entrega >= 0` para todo pedido com
`data_entrega_sk` não nula — etapa 03, asserção `prazo_nao_negativo`.

---

## Fichas obrigatórias

Ao menos uma ficha para cada decisão abaixo. Mais, se vocês encontrarem outras.

| Nº | Decisão | Etapa |
|---|---|---|
| RDT-01 | Carga completa ou incremental, e com que critério de mudança | 01 |
| RDT-02 | Regra de unificação de identidade do cliente entre os dois sistemas | 02 |
| RDT-03 | Tratamento das duplicatas internas do legado | 02 |
| RDT-04 | Conformação de `STATUS` × `status`, incluindo `payment_declined` | 02 |
| RDT-05 | Definição de `VALOR_TOTAL` e `total_amount`, e como foi descoberta | 02 |
| RDT-06 | Frete negativo e desconto `-1` | 02 |
| RDT-07 | Mapeamento de categorias de produto, incluindo os casos ambíguos | 02 |
| RDT-08 | Classificação e tratamento de cada tipo de ausência | 02 |
| RDT-09 | Padronização de fuso horário | 02 |
| RDT-10 | Itens órfãos | 03 |
| RDT-11 | Declaração de grão de `fato_pedido` e `fato_item_pedido` | 03 |
| RDT-12 | Pedidos sem cliente correspondente | 03 |
| RDT-13 | Atendimentos e avaliações que não ligam a nenhum pedido | 02/03 |
| RDT-14 | Desenho dos atributos da ABT e verificação de ausência de vazamento | 04 |
| RDT-15 | Vazamentos introduzidos deliberadamente na versão de comparação | 04 |

---

## Tabela-resumo

| Ficha | Decisão | Registros afetados | % da base | Informação perdida? |
|---|---|---|---|---|
| RDT-01 | | | | |
| RDT-02 | | | | |
| ... | | | | |

---

## Reflexão final (máximo 400 palavras)

Responda, com base no que vocês viveram no projeto:

1. Qual das decisões acima mudaria mais o resultado do modelo se tivesse sido
   tomada de outro modo? Vocês testaram, ou é uma hipótese?
2. Alguma decisão que vocês tomaram por conveniência técnica teria consequência
   sobre pessoas reais, se este fosse um sistema em produção? Qual?
3. Qual informação vocês gostariam de ter tido, e não tinham?
