# Registro de Decisões de Transformação (RDT)

**Equipe:** Mateus de Souza Arruda e Lorena Strobel Campos  **Data:** 14/10/2026  **Versão do pipeline:** 0.2.0

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

## Fichas Preenchidas

### Ficha RDT-05 — Definição e Decomposição Contábil de VALOR_TOTAL e total_amount

**Decisão:** harmonização da semântica monetária divergente entre `VALOR_TOTAL` (ERP Legado) e `total_amount` (E-commerce) mediante decomposição canônica nas quatro medidas contábeis aditivas de Kimball (`valor_mercadoria`, `valor_frete`, `valor_desconto`, `valor_total`).

**Etapa do pipeline:** 02_transformacao · `conforma_valores`

**O que o dado mostrava:** 
Na exploração da base na escala 1.0 (seed 20262), totalizando 410.000 pedidos (130.000 do legado e 280.000 do e-commerce), a apuração da relação algébrica entre os valores declarados no cabeçalho dos pedidos e os respectivos itens comprovou divergência semântica crítica de 100%:
1. No ERP Legado, a hipótese contábil $H_1: \text{VALOR\_TOTAL} = \sum (\text{VL\_UNITARIO} \times \text{QTD} - \text{VL\_DESCONTO}) + \text{VALOR\_FRETE}$ cumpriu-se exatamente com desvio zero para 130.000 de 130.000 pedidos (100,00%), após o tratamento do sentinela de desconto `-1` (presente em 4.056 itens de 4.003 pedidos). Provou-se que `VALOR_TOTAL` no legado é o **valor faturado bruto final com o frete embutido**.
2. No E-commerce, a hipótese contábil $H_2: \text{total\_amount} = \sum (\text{unit\_price} \times \text{quantity} - \text{discount})$ cumpriu-se exatamente com desvio zero para 280.000 de 280.000 pedidos (100,00%). O valor do frete (`freight_amount`) reside isolado e **não integra** `total_amount`. Provou-se que `total_amount` no e-commerce é o **subtotal líquido dos produtos sem frete**.

Se integrados diretamente sem conformação, ocorreria contaminação semântica severa: a unificação direta 1:1 subestimaria o faturamento corporativo em 280.000 pedidos (68,29% da base) no montante total de frete contratado (R$ 11.493.447,21 no e-commerce), ou, se somado frete cegamente a ambos os sistemas, computaria o frete em duplicidade em 130.000 pedidos (31,71% da base), inflacionando ficticiamente a receita do legado em R$ 5.307.593,25.

**Alternativas consideradas:**

1. *Ingestão literal direta (Mapeamento 1:1 ingênuo):* Mapear `VALOR_TOTAL` e `total_amount` diretamente para a medida `valor_total` em `dw.fato_pedido`. Descartada: gera heterogeneidade semântica não resolvida no Data Warehouse; o mesmo atributo dimensional conteria frete para pedidos físicos e excluiria frete para pedidos virtuais, invalidando qualquer análise de faturamento consolidado ou ticket médio.
2. *Segregação colunar por canal de origem:* Criar medidas distintas como `valor_total_legado` e `total_amount_ecommerce` na tabela fato, mantendo nulo o campo do canal ausente. Descartada: viola os princípios de Kimball de esquema dimensional único ("single source of truth"). Forçaria analistas e ferramentas analíticas (SQL, BI, Python) a utilizarem estruturas condicionais complexas (`COALESCE`), transferindo a complexidade de integração para o usuário final.
3. *Decomposição canônica de Kimball em quatro medidas aditivas:* Desconstruir e padronizar os valores de todos os 410.000 pedidos em quatro métricas atômicas universais:
   - `valor_mercadoria` = $\sum (\text{preco\_unitario} \times \text{quantidade})$
   - `valor_frete` = frete explicitado e corrigido de valores negativos
   - `valor_desconto` = descontos monetários reais calculados a partir dos itens
   - `valor_total` = $\text{valor\_mercadoria} + \text{valor\_frete} - \text{valor\_desconto}$

**Decisão:** alternativa 3.

**Justificativa:** A decomposição canônica estabelece conformidade matemática e contábil irrefutável em 100% da base corporativa. Ao desacoplar mercadorias, fretes e descontos, todas as quatro medidas tornam-se plenamente aditivas em todas as dimensões de análise (tempo, cliente, produto e canal de venda), permitindo apurar tanto a receita bruta de produtos (R$ 1.087.154.072,52) quanto a receita líquida total faturada (R$ 1.026.984.182,65) sem ambiguidade e sem risco de distorção fiscal.

**O que se perde:** Perde-se a dependência exclusiva do total de cabeçalho bruto dos sistemas legados como valor canônico autônomo. A integridade contábil passa a depender do alinhamento relacional entre cabeçalho e linhas de itens. Pequenas variações de centavos decorrentes de arredondamentos pontuais no legado são uniformizadas pela agregação das linhas de itens. Caso analistas necessitem do valor literal original sem tratamento de sentinelas, deverão consultar as tabelas de staging brutas (`stg.legado_pedidos`), pois o DW reflete unicamente a visão contábil conformada.

**Registros afetados:** 410.000 pedidos (100,00% da base consolidada: 130.000 do legado [31,71%] e 280.000 do e-commerce [68,29%]), além de 1.392.453 itens vinculados e normalizados.

**Asserção associada:** Etapa 02 (`02_transformacao.py`), asserções:
- `identidade contábil valor_total`: validação de que $|\text{valor\_total} - (\text{valor\_mercadoria} + \text{valor\_frete} - \text{valor\_desconto})| \le 0,01$ para todos os 410.000 pedidos. Resultado: 410.000 aprovados (0 divergências).
- `soma de mercadoria bate com itens`: validação de que a soma de `valor_mercadoria` nos pedidos coincide exatamente com a soma de `valor_bruto` nas linhas de itens. Resultado: 410.000 aprovados (0 divergências).
Resultados auditados e persistidos na tabela `qa.execucao_assercao`.

---

## Tabela-resumo

| Ficha | Decisão | Registros afetados | % da base | Informação perdida? |
|---|---|---|---|---|
| RDT-01 | Carga completa (full load) | | | |
| RDT-02 | Unificação de clientes por CPF | | | |
| RDT-03 | Deduplicação interna do legado | | | |
| RDT-04 | Conformação de status de pedidos | | | |
| RDT-05 | Decomposição contábil de VALOR_TOTAL e total_amount em 4 medidas | 410.000 pedidos | 100,0% | Sim (dependência de cabeçalho bruto substituída por identidade aditiva de itens) |
| RDT-06 | Frete negativo e desconto -1 | | | |
| RDT-07 | Mapeamento de categorias de produto | | | |
| RDT-08 | Classificação de ausências e sentinela 1900-01-01 | | | |
| RDT-09 | Padronização temporal em UTC | | | |
| RDT-10 | Itens órfãos | | | |
| RDT-11 | Declaração de grão de fato_pedido e fato_item_pedido | | | |
| RDT-12 | Pedidos sem cliente correspondente | | | |
| RDT-13 | Atendimentos desconectados | | | |
| RDT-14 | Engenharia de atributos da ABT sem vazamento | | | |
| RDT-15 | Vazamentos introduzidos deliberadamente | | | |

---

## Reflexão final (máximo 400 palavras)

Responda, com base no que vocês viveram no projeto:

1. Qual das decisões acima mudaria mais o resultado do modelo se tivesse sido
   tomada de outro modo? Vocês testaram, ou é uma hipótese?
2. Alguma decisão que vocês tomaram por conveniência técnica teria consequência
   sobre pessoas reais, se este fosse um sistema em produção? Qual?
3. Qual informação vocês gostariam de ter tido, e não tinham?
