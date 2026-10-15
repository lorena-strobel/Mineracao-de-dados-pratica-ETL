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

### Ficha RDT-06 — Tratamento de Frete Negativo e Desconto Sentinela `-1`

**Decisão:** saneamento de anomalias operacionais de domínio nos componentes de valores: truncamento de valores de frete negativos para `0.00` via `GREATEST(0, frete)` com ativação de `flag_frete_negativo = TRUE`, e conversão de descontos sentinela `-1.00` para `0.00` com ativação de `flag_desconto_sentinela = TRUE`.

**Etapa do pipeline:** 02_transformacao · `conforma_valores`

**O que o dado mostrava:** 
A inspeção da base consolidada em escala 1.0 (seed 20262) revelou duas anomalias que violam premissas de domínio físico e contábil:
1. *Frete Negativo:* Presente em 1.174 pedidos (0,286% dos 410.000 pedidos), sendo 362 pedidos no ERP Legado (0,278% do canal; variação de -R$ 88,78 a -R$ 0,01; soma: -R$ 16.098,86; média: -R$ 44,47) e 812 pedidos no E-commerce (0,290% do canal; variação de -R$ 78,86 a -R$ 0,01; soma: -R$ 32.248,65; média: -R$ 39,72). No ERP Legado, a prova contábil demonstrou que em 100,0% dos 362 pedidos o total faturado subtraiu o frete negativo, evidenciando uso do campo como artifício para conceder subsídio logístico ou estorno comercial ao cliente. No total, as anomalias de frete perfazem -R$ 48.347,51.
2. *Desconto Sentinela `-1`:* Presente em 4.056 linhas de itens do ERP Legado (1,021% dos itens do canal), afetando 4.003 pedidos distintos (3,079% dos pedidos do legado). Não existe nenhum outro valor negativo além do literal exato `-1.00`. No E-commerce, essa anomalia é inexistente (0 itens). Trata-se de código sentinela legado para indicar produto inelegível para descontos promocionais. Se calculado aritmeticamente na receita líquida ($\text{Preço} \times \text{QTD} - \text{Desconto}$), geraria $-(-1) = +1$, inflacionando artificialmente a receita em R$ 4.056,00.

**Alternativas consideradas:**

*Para Frete Negativo:*
1. *Manter valores negativos brutos:* Descartada: gera custos de transporte negativos nos cubos OLAP do DW, distorcendo relatórios de despesas logísticas por transportadora e médias de frete por UF.
2. *Inverter o sinal (`ABS(frete)`):* Descartada: arbitrária e contrafactual. A reconciliação do legado provou que o valor foi abatido e não cobrado a mais do cliente; inverter o sinal computaria cobrança indevida.
3. *Truncar em `0.00` e registrar indicador de anomalia (`flag_frete_negativo`):* Estabelecer $\text{valor\_frete} = \max(0, \text{frete})$ e sinalizar a ocorrência com booleano.

*Para Desconto Sentinela `-1`:*
1. *Cálculo literal aritmético (-R$ 1,00):* Descartada: gera ganho fictício de receita líquida de R$ 1,00 por item.
2. *Converter para `NULL`:* Descartada: viola a integridade dimensional de Kimball; nulos em métricas aditivas quebram agregações SQL (`SUM`, `AVG`).
3. *Substituir por `0.00` e registrar indicador (`flag_desconto_sentinela`):* Mapear para zero monetário, preservando o significado de ausência de desconto financeiro real e retendo a flag para auditoria.

**Decisão:** alternativa 3 para ambas as anomalias.

**Justificativa:** Assegura a integridade de domínio físico e contábil em 100% da base: nenhum serviço de frete no DW possui custo negativo, e nenhum item tem sua receita inflacionada por um marcador de sistema. A conversão simultânea com sinalização por flags booleanas garante a conformidade matemática estrita exigida pelo esquema estrela, ao mesmo tempo em que retém rastreabilidade para mineração de regras de associação sobre falhas operacionais e estornos.

**O que se perde:** 
1. No frete, perde-se o registro contábil do subsídio logístico concedido aos clientes (-R$ 16.098,86 no legado e -R$ 32.248,65 no e-commerce, somando -R$ 48.347,51). O DW prioriza a métrica de custo físico de transporte sobre o estorno promocional.
2. No desconto, perde-se a distinção nativa do ERP Legado entre item estruturalmente inelegível para promoção e item elegível com desconto zero, a menos que o analista consulte a flag de auditoria.

**Registros afetados:** 
- Frete negativo: 1.174 pedidos (0,286% da base total de 410.000 pedidos: 362 legado e 812 e-commerce).
- Desconto sentinela `-1`: 4.056 itens (0,291% do total de 1.392.453 itens), distribuídos em 4.003 pedidos (0,976% dos pedidos do DW).

**Asserção associada:** Etapa 02 (`02_transformacao.py`), asserções:
- `frete não negativo dw`: valida se $\text{menor frete} \ge 0,00$. Resultado: menor = R$ 0,00 (0 negativos).
- `desconto não negativo itens`: valida se $\text{menor desconto} \ge 0,00$. Resultado: menor = R$ 0,00 (0 negativos).
- `desconto sem sentinela menos um`: valida se restou algum `-1` na base. Resultado: 0 ocorrências.
- `quantificacao frete negativo consolidado`: valida contagem exata de 1.174 pedidos com `flag_frete_negativo = TRUE`.
- `quantificacao frete negativo legado`: valida 362 pedidos no legado.
- `quantificacao frete negativo ecom`: valida 812 pedidos no e-commerce.
- `quantificacao desconto sentinela itens`: valida 4.056 itens com `flag_desconto_sentinela = TRUE`.
- `quantificacao desconto sentinela pedidos`: valida 4.003 pedidos com `flag_desconto_sentinela = TRUE`.
Todas auditadas e registradas na tabela `qa.execucao_assercao`.

### Ficha RDT-07 — Mapeamento e Taxonomia de Categorias de Produto

**Decisão:** conformação dos 27 rótulos livres de produtos do ERP Legado para a taxonomia relacional de dois níveis do E-commerce (`categoria_nivel1` e `categoria_nivel2`), desambiguando casos complexos (`informatica e games`, `TV E SOM`, `DIVERSOS`, `OUTROS`, vazio) por enriquecimento léxico de substantivos de domínio da descrição, com preservação obrigatória da evidência bruta em `categoria_origem`.

**Etapa do pipeline:** 02_transformacao · `conforma_categorias`

**O que o dado mostrava:** 
O catálogo de produtos do E-commerce (12.000 itens) é regido por uma taxonomia relacional controlada composta por 8 categorias raiz no Nível 1 e 13 subcategorias no Nível 2. Em contrapartida, o catálogo do ERP Legado (3.000 itens) armazena categorias em um campo de texto livre com 27 variantes grafadas sem padronização.
A análise empírica identificou três ordens de desafios semânticos:
1. *Variantes Ortográficas e Morfológicas (22 rótulos, 2.437 produtos):* Grafias divergentes do mesmo conceito (ex: `ELETRO`, `Eletro`, `eletrodomesticos`, `Eletro-domesticos`, `ELETRODOMÉSTICOS`; `INFORMATICA`, `Informática`, `INFO`; `TELEFONIA`, `Celulares`, `CELULAR/SMARTPHONE`; `CASA`, `Casa e decoracao`, `MOVEIS`).
2. *Fusão de Ramos Raiz e de Subcategorias (2 rótulos, 223 produtos):*
   - `informatica e games` (112 produtos): funde duas categorias raiz distintas da taxonomia corporativa (`Informática` e `Games`).
   - `TV E SOM` (111 produtos): funde os dois filhos de `Áudio e TV` (`Televisores` e `Áudio`).
3. *Categorias Sem Informação Semântica (3 rótulos, 340 produtos):* `OUTROS` (121 produtos), `DIVERSOS` (116 produtos) e strings vazias/espaços (103 produtos), totalizando 11,33% do legado sem classificação utilizável.

Entretanto, o perfilamento fático revelou que **100,00% dos 3.000 produtos do legado** possuem o substantivo canônico do catálogo na primeira palavra de sua descrição (ex: `FOGÃO`, `NOTEBOOK`, `CONSOLE`, `SOFÁ`, `TELEVISOR`), viabilizando a identificação inequívoca da natureza do produto.

**Alternativas consideradas:**

1. *De-Para puramente categórico com valores nulos/descarte nos ambíguos:* Mapear apenas os rótulos óbvios e classificar os 563 produtos ambíguos ou genéricos como `Não Informado`. Descartada: descarta 18,77% do catálogo do legado, criando "pontos cegos" maciços que invalidam análises de market-basket, propensão de recompra e segmentação por produto na mineração de dados.
2. *Criação de categorias híbridas artificiais no DW:* Criar categorias como "Informática e Games" ou "TV e Som" no Nível 1 da dimensão. Descartada: viola o princípio de conformação dimensional de Kimball ("conformed dimensions"), criando assimetria estrutural e impedindo comparações analíticas coerentes entre os canais físico e virtual.
3. *Conformação Híbrida com Desambiguação Léxica pela Descrição:* Classificar a hierarquia taxonômica de dois níveis (`categoria_nivel1` e `categoria_nivel2`) inspecionando o substantivo de domínio presente na descrição do produto, associando cada item a um dos 15 pares taxonômicos válidos do e-commerce, preservando estritamente o texto livre original em `categoria_origem`.

**Decisão:** alternativa 3.

**Justificativa:** A alternativa 3 assegura 100,00% de cobertura taxonômica homologada para todos os 15.000 produtos do catálogo unificado (`dw.dim_produto`), garantindo que 100% dos produtos do legado sejam mapeados para os 15 pares taxonômicos idênticos aos do e-commerce. A integridade dimensional de Kimball é plenamente preservada sem perda de produtos, enquanto a preservação da coluna `categoria_origem` garante auditabilidade integral e conformidade com o princípio de retenção de evidências brutas.

**O que se perde:** Perde-se a fidelidade estrita à taxonomia administrativa originalmente preenchida pelo operador do sistema legado na navegação hierárquica do DW. Assume-se a premissa de que a descrição fática do produto ("FOGÃO NEXA 826") sobrepõe o cadastro operacional impreciso ("informatica e games"). Analistas que necessitem consultar a classificação do legado exatamente como digitada em 2021 devem utilizar o atributo `categoria_origem`.

**Registros afetados:** 3.000 produtos do ERP Legado (20,00% do catálogo consolidado de 15.000 produtos do DW), dos quais 563 produtos (18,77% do legado; 3,75% do total de produtos) apresentavam ambiguidade estrutural ou ausência total de informação categórica.

**Asserção associada:** Etapa 02 (`02_transformacao.py`), asserções:
- `total produtos dw`: valida exatamente 15.000 produtos em `dw.dim_produto`.
- `produtos origem legado`: valida 3.000 produtos oriundos do legado.
- `produtos origem ecom`: valida 12.000 produtos oriundos do e-commerce.
- `categoria_nivel1 sem nulos`: valida 0 nulos ou vazios no primeiro nível.
- `categoria_nivel2 sem nulos`: valida 0 nulos ou vazios no segundo nível.
- `categoria_origem preservada`: valida 100% dos produtos com rastreabilidade da evidência original.
- `taxonomia conforme ecommerce`: valida se todos os pares `(categoria_nivel1, categoria_nivel2)` do legado existem na taxonomia do e-commerce (0 pares inválidos).
Todas aprovadas e persistidas na tabela `qa.execucao_assercao`.

---

## Tabela-resumo

| Ficha | Decisão | Registros afetados | % da base | Informação perdida? |
|---|---|---|---|---|
| RDT-01 | Carga completa (full load) | | | |
| RDT-02 | Unificação de clientes por CPF | | | |
| RDT-03 | Deduplicação interna do legado | | | |
| RDT-04 | Conformação de status de pedidos | | | |
| RDT-05 | Decomposição contábil de VALOR_TOTAL e total_amount em 4 medidas | 410.000 pedidos | 100,0% | Sim (dependência de cabeçalho bruto substituída por identidade aditiva de itens) |
| RDT-06 | Truncamento de frete negativo e conversão de sentinela de desconto -1 | 1.174 pedidos (frete) / 4.056 itens (desconto) | 0,29% (pedidos) / 0,29% (itens) | Sim (subsídios de frete de R$ 48.347,51 descartados do frete faturado; inelegibilidade retida em flag) |
| RDT-07 | Conformação da taxonomia de produtos em 2 níveis e desambiguação léxica | 3.000 produtos (legado) | 20,0% do catálogo | Sim (categoria administrativa do legado sobreposta pela descrição fática; texto bruto retido em categoria_origem) |
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
