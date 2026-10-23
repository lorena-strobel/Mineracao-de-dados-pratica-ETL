# Registro de Decisões de Transformação (RDT)

**Equipe:** Mateus de Souza Arruda e Lorena Strobel Campos  **Data:** 14/10/2026  **Versão do pipeline:** 0.2.0

**Link Github:** https://github.com/lorena-strobel/Mineracao-de-dados-pratica-ETL.git

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

| Nº     | Decisão                                                             | Etapa |
| ------ | ------------------------------------------------------------------- | ----- |
| RDT-01 | Carga completa ou incremental, e com que critério de mudança        | 01    |
| RDT-02 | Regra de unificação de identidade do cliente entre os dois sistemas | 02    |
| RDT-03 | Tratamento das duplicatas internas do legado                        | 02    |
| RDT-04 | Conformação de `STATUS` × `status`, incluindo `payment_declined`    | 02    |
| RDT-05 | Definição de `VALOR_TOTAL` e `total_amount`, e como foi descoberta  | 02    |
| RDT-06 | Frete negativo e desconto `-1`                                      | 02    |
| RDT-07 | Mapeamento de categorias de produto, incluindo os casos ambíguos    | 02    |
| RDT-08 | Classificação e tratamento de cada tipo de ausência                 | 02    |
| RDT-09 | Padronização de fuso horário                                        | 02    |
| RDT-10 | Itens órfãos                                                        | 03    |
| RDT-11 | Declaração de grão de `fato_pedido` e `fato_item_pedido`            | 03    |
| RDT-12 | Pedidos sem cliente correspondente                                  | 03    |
| RDT-13 | Atendimentos e avaliações que não ligam a nenhum pedido             | 02/03 |
| RDT-14 | Desenho dos atributos da ABT e verificação de ausência de vazamento | 04    |
| RDT-15 | Vazamentos introduzidos deliberadamente na versão de comparação     | 04    |

<br>

---

<br>

## Fichas Preenchidas

### Ficha RDT-01 — Carga completa ou incremental, e com que critério de mudança

**Decisão:** Estratégia de carga da camada de Staging (Carga Completa vs. Carga Incremental).

**Etapa do pipeline:** 01_extracao · `extrai_mysql`, `extrai_postgres`, `extrai_sac`, `extrai_avaliacoes`

**O que o dado mostrava:** As quatro fontes de dados apresentam naturezas heterogêneas. Os arquivos externos (`atendimentos_sac.csv` e `avaliacoes_marketplace.json`) e as tabelas do sistema legado não fornecem campos confiáveis de controle de mutação (como `dt_atualizacao`, log transacional ou Change Data Capture - CDC). Apenas o e-commerce possui timestamps em certas tabelas, mas sem garantia de integridade de deleções/atualizações entre sistemas.

**Alternativas consideradas:**
1. Carga Incremental: Transferência apenas dos registros novos ou modificados desde a última extração. Descartada por ausência de metadados de modificação confiáveis nas origens (legado e arquivos estáticos), gerando risco de dados desatualizados ou inconsistentes.
2. Carga Completa (Full Load): Truncar/substituir as tabelas da camada `stg` e recarregar 100% dos dados brutos a cada execução.

**Decisão:** Alternativa 2 (Carga Completa).

**Justificativa:** Assegura a reprodutibilidade determinística do ambiente a partir do zero via `docker compose down -v && docker compose up --build`. Garante que o Data Warehouse reflita o estado exato das origens sem dependência de estados residuais ou falhas de sincronização incremental.

**O que se perde:** Eficiência computacional e tempo de execução. O tempo de build/extração consome entre 3 e 5 minutos para processar o volume completo das quatro origens, custo que seria mitigado em uma abordagem incremental.

**Registros afetados:** 100% dos dados brutos das quatro origens carregados na camada staging (abrangendo todas as tabelas de pedidos, clientes, produtos, SAC e avaliações do marketplace).

**Asserção associada:** Validação da integridade volumétrica e estrutural na etapa 01:
1. `qa.igual("linhas legado.PEDIDOS", ...)`: Compara a contagem do MySQL com `stg.legado_pedidos` (esperado = 130.000).
2. `qa.igual("linhas ecommerce.orders", ...)`: Compara a contagem do PostgreSQL com `stg.ecommerce_orders` (esperado = 280.000).
3. `qa.sem_nulos("protocolo do SAC", ...)`: Assegura ausência de nulos na chave de atendimento (96.140 protocolos).
4. `qa.unico("review_id", ...)`: Validação de unicidade das avaliações do marketplace (160.000 avaliações).

<br>
<br>

### Ficha RDT-02 — Regra de unificação de identidade do cliente entre os dois sistemas

**Decisão:** Regra de unificação da identidade do cliente entre o sistema legado e o e-commerce via CPF.

**Etapa do pipeline:** 02_transformacao · `unifica_clientes`

**O que o dado mostrava:** O perfilamento das origens revelou que o CPF é o único atributo estruturado capaz de atuar como ponte entre os clientes do legado (47.250 cadastros) e do e-commerce (85.000 cadastros). Contudo, foram observadas ausências de CPF em ambas as pontas (4.423 campos vazios no legado e 6.855 nulos no e-commerce), além de inconsistências de formatação (máscara). Ao inspecionar os registros com 11 dígitos, constatou-se que cerca de 9% dos CPFs apresentavam dígito verificador inválido, porém a mesmíssima sequência numérica aparecia em ambas as bases associada ao mesmo cliente, evidenciando que o erro de digitação foi propagado entre os sistemas e funciona como identificador estável.

**Alternativas consideradas:**
1. Parear exclusivamente CPFs com dígito verificador válido: Descartada, pois descartaria 1.135 pareamentos legítimos de clientes reais cujo erro de digitação foi propagado identicamente para ambos os sistemas.
2. Parear por nome normalizado + cidade + UF (para registros sem CPF): Descartada, pois a incidência de homônimos e variações de grafia introduz uma taxa estimada de 3% a 5% de falsos positivos, corrompendo a integridade da dimensão.
3. Parear por CPF limpo de 11 dígitos (aceitando válidos e inválidos propagados), mantendo controle de unicidade e marcando a regra de pareamento aplicada (`CPF_VALIDO` vs `CPF_DIGITO_INVALIDO`).

**Decisão:** Alternativa 3.

**Justificativa:** 
* *CPF com dígito inválido serve para parear?:* Sim. Se possui 11 dígitos e coincide exatamente entre os dois sistemas, a probabilidade de duas pessoas distintas terem o mesmo CPF inválido digitado é desprezível. Ele identifica o cliente de forma estável.
* *Parear por nome + cidade + UF na ausência de CPF?:* Não. A taxa estimada de 3% a 5% de falsos positivos introduz distorções inaceitáveis na base.
* *Qual erro é mais grave?:* Fundir dois clientes distintos (falso positivo), pois isso corrompe irremediavelmente o histórico de compras, métricas de LTV e a ABT de recompra. Manter o cliente duplicado fragmenta a visão, mas preserva a fidelidade dos registros individuais.
* *Tratamento de duplicatas internas do legado:* Foi realizado previamente retendo o registro com `dt_cadastro` mais recente (detalhado na RDT-03).

**O que se perde:** Deixa-se de unificar os clientes que não possuem CPF preenchido em pelo menos uma das fontes. Esses indivíduos não puderam ser pareados com segurança e passaram a coexistir como dois registros separados na dimensão (uma linha `LEGADO` e uma linha `ECOM`), fragmentando seu histórico para o modelo de recompra (ABT).

**Registros afetados:** 106.937 clientes unificados na `dw.dim_cliente`:
* `AMBOS`: 12.605 clientes pareados (11.470 com CPF válido e 1.135 com dígito inválido propagado).
* `ECOM`: 65.537 clientes exclusivos (59.705 com CPF válido e 5.832 com dígito inválido).
* `LEGADO`: 28.795 clientes exclusivos (26.196 com CPF válido e 2.599 com dígito inválido).

**Asserção associada:** 
* `qa.sem_nulos("nome_padronizado preenchido", dim_cliente["nome_padronizado"])`: 0 nulos obtidos.
* `qa.dominio("origem_unificacao valida", dim_cliente["origem_unificacao"], {"LEGADO", "ECOM", "AMBOS"})`.
* `qa.unico("cpf valido unico em dim_cliente", df_cpfs_validos["cpf_normalizado"])`: 0 duplicados entre os CPFs válidos.

<br>
<br>

### Ficha RDT-03 — Tratamento das duplicatas internas do legado

**Decisão:** Tratamento e desduplicação interna de clientes do sistema legado prévia ao cruzamento.

**Etapa do pipeline:** 02_transformacao · `unifica_clientes`

**O que o dado mostrava:** A tabela `CLIENTES` do legado continha 47.250 registros para 41.400 CPFs distintos. Havia repetição de registros de um mesmo cliente decorrentes de recadastros operacionais e variações de máscara/espaços. Ao normalizar os CPFs de 11 dígitos, identificou-se um excedente de 5.849 registros duplicados (12,38% da base), que causariam inconsistências relacionais na unificação.

**Alternativas consideradas:**
1. Manter todas as duplicatas: Descartada, pois a cardinalidade 1:N no cruzamento (JOIN) com o e-commerce geraria produto cartesiano e multiplicaria indevidamente as linhas na `dim_cliente`.
2. Descartar todos os CPFs com duplicidade: Descartada, pois eliminaria sumariamente clientes ativos e legítimos da base.
3. Ordenar os registros decrescentemente por data de cadastro (`dt_cadastro DESC`) e reter a primeira ocorrência (mais recente), consolidando o cadastro atualizado (Golden Record).

**Decisão:** Alternativa 3.

**Justificativa:** Garante a unicidade da chave natural no legado antes do merge com o e-commerce e assegura que os atributos cadastrais preservados (endereço, telefone, grafia de nome) correspondam à versão mais recente informada pelo cliente.

**O que se perde:** O histórico cadastral anterior associado aos registros antigos descartados (mudanças pretéritas de endereço ou telefone). Caso algum pedido legado estivesse associado ao `id_cliente` antigo descartado, a integridade precisa ser mantida via chave de negócio (CPF) no DW.

**Registros afetados:** 5.849 registros duplicados expurgados (12,38% dos 47.250 cadastros do legado).

**Asserção associada:** 
* `qa.unico("cpf valido unico em dim_cliente", ...)`: Verificação de 0 duplicatas de CPF na dimensão final.
* `qa.cardinalidade_preservada`: Garantia de que a junção não gerou explosão de linhas.

<br>
<br>

### Ficha RDT-04 — Conformação de `STATUS` × `status`, incluindo `payment_declined`

**Decisão:** Conformação dos status de pedido entre Legado e E-commerce, preservando a distinção de recusa de pagamento.

**Etapa do pipeline:** 02_transformacao · `conforma_status`

**O que o dado mostrava:** O agrupamento de status nas tabelas de staging revelou divergências semânticas e taxonômicas entre os sistemas. O legado agregava sob o rótulo `CANCELADO` um total de 15.774 pedidos sem detalhar o motivo. Já o e-commerce detalhava essa situação em duas categorias: desistência do cliente (`canceled`, 22.413 pedidos) e recusa técnica/financeira (`payment_declined`, 13.990 pedidos), totalizando 36.403 pedidos não concluídos. Além disso, os demais fluxos operacionais apresentavam nomenclaturas distintas (`ENTREGUE`/`delivered`, `EM TRANSITO`/`shipped`, `SEPARACAO`/`processing`).

**Alternativas consideradas:**
1. Mapear `payment_declined` para `CANCELADO` de forma plana: Descartada, pois destrói a visibilidade sobre falhas de pagamento e antifraude no e-commerce.
2. Criar status planos separados (`CANCELADO_CLIENTE` e `CANCELADO_PAGAMENTO`): Descartada, pois introduz assimetria forçada onde o legado ficaria indefinido, complicando agregações gerenciais de cancelamento global.
3. Modelagem hierárquica na dimensão: Definir `status_conformado = 'CANCELADO'` para ambos os fluxos e criar o atributo complementar `motivo_cancelamento`, preenchido como `'DESISTENCIA_CLIENTE'`, `'RECUSA_PAGAMENTO'` ou `NULL` (quando desconhecido no legado).

**Decisão:** Alternativa 3.

**Justificativa:** Atende perfeitamente ao esquema relacional da `dw.dim_status`, unificando a visão gerencial de pedidos cancelados sem descartar a granularidade e a riqueza analítica existente na origem do e-commerce.

**O que se perde:** O motivo de cancelamento dos 15.774 pedidos do legado permanece desconhecido e irrecuperável (`NULL`), gerando uma assimetria analítica que impede o uso homogêneo do atributo de recusa de pagamento para clientes exclusivos do legado na modelagem da ABT.

**Registros afetados:** 410.000 pedidos conformados no DW (130.000 do legado e 280.000 do e-commerce), abrangendo as 9 regras da dimensão. No recorte de cancelamentos: 15.774 pedidos do legado e 36.403 do e-commerce (22.413 por desistência e 13.990 por recusa de pagamento).

**Asserção associada:** 
* `qa.sem_nulos("status_conformado preenchido", ...)`: 0 nulos (esperado = 0).
* `qa.dominio("status_conformado valido", ..., {"ENTREGUE", "CANCELADO", "EM_TRANSITO", "PROCESSAMENTO"})`: 0 violações.
* `qa.igual("total de regras dim_status", len(df_status), 9)`: Exatamente 9 regras mapeadas.
* `qa.igual("cobertura total de status dos pedidos", len(status_sem_regra), 0)`: 100% dos status brutos cobertos sem órfãos.

<br>
<br>

### Ficha RDT-05 — Definição e Decomposição Contábil de VALOR_TOTAL e total_amount

**Decisão:** harmonização da semântica monetária divergente entre `VALOR_TOTAL` (ERP Legado) e `total_amount` (E-commerce) mediante decomposição canônica nas quatro medidas contábeis aditivas de Kimball (`valor_mercadoria`, `valor_frete`, `valor_desconto`, `valor_total`).

**Etapa do pipeline:** 02_transformacao · `conforma_valores`

**O que o dado mostrava:** 
Na exploração da base na escala 1.0 (seed 20262), totalizando 410.000 pedidos (130.000 do legado e 280.000 do e-commerce), a apuração da relação algébrica entre os valores declarados no cabeçalho dos pedidos e os respectivos itens comprovou divergência semântica crítica de 100%:
1. No ERP Legado, a hipótese contábil $H_{1}: \text{VALOR}{\text{TOTAL}} = \sum (\text{VL}{\text{UNITARIO}} \times \text{QTD} - \text{VL}{\text{DESCONTO}}) + \text{VALOR}{\text{FRETE}}$ cumpriu-se exatamente com desvio zero para 130.000 de 130.000 pedidos (100,00%), após o tratamento do sentinela de desconto `-1` (presente em 4.056 itens de 4.003 pedidos). Provou-se que `VALOR_TOTAL` no legado é o **valor faturado bruto final com o frete embutido**.
2. No E-commerce, a hipótese contábil $H_{2}: \text{total}{\text{amount}} = \sum (\text{unit}{\text{price}} \times \text{quantity} - \text{discount})$ cumpriu-se exatamente com desvio zero para 280.000 de 280.000 pedidos (100,00%). O valor do frete (`freight_amount`) reside isolado e **não integra** `total_amount`. Provou-se que `total_amount` no e-commerce é o **subtotal líquido dos produtos sem frete**.

Se integrados diretamente sem conformação, ocorreria contaminação semântica severa: a unificação direta 1:1 subestimaria o faturamento corporativo em 280.000 pedidos (68,29% da base) no montante total de frete contratado (R$ 11.493.447,21 no e-commerce), ou, se somado frete cegamente a ambos os sistemas, computaria o frete em duplicidade em $130.000$ pedidos ($31,71%$ da base), inflacionando ficticiamente a receita do legado em R$ 5.307.593,25.

**Alternativas consideradas:**

1. *Ingestão literal direta (Mapeamento 1:1 ingênuo):* Mapear `VALOR_TOTAL` e `total_amount` diretamente para a medida `valor_total` em `dw.fato_pedido`. Descartada: gera heterogeneidade semântica não resolvida no Data Warehouse; o mesmo atributo dimensional conteria frete para pedidos físicos e excluiria frete para pedidos virtuais, invalidando qualquer análise de faturamento consolidado ou ticket médio.
2. *Segregação colunar por canal de origem:* Criar medidas distintas como `valor_total_legado` e `total_amount_ecommerce` na tabela fato, mantendo nulo o campo do canal ausente. Descartada: viola os princípios de Kimball de esquema dimensional único ("single source of truth"). Forçaria analistas e ferramentas analíticas (SQL, BI, Python) a utilizarem estruturas condicionais complexas (`COALESCE`), transferindo a complexidade de integração para o usuário final.
3. *Decomposição canônica de Kimball em quatro medidas aditivas:* Desconstruir e padronizar os valores de todos os 410.000 pedidos em quatro métricas atômicas universais:
   - `valor_mercadoria` = $\sum (\text{preco}_{\text{unitario}} \times \text{quantidade})$
   - `valor_frete` = frete explicitado e corrigido de valores negativos
   - `valor_desconto` = descontos monetários reais calculados a partir dos itens
   - `valor_total` = $\text{valor}{\text{mercadoria}} + \text{valor}{\text{frete}} - \text{valor}{\text{desconto}}$

**Decisão:** alternativa 3.

**Justificativa:** A decomposição canônica estabelece conformidade matemática e contábil irrefutável em 100% da base corporativa. Ao desacoplar mercadorias, fretes e descontos, todas as quatro medidas tornam-se plenamente aditivas em todas as dimensões de análise (tempo, cliente, produto e canal de venda), permitindo apurar tanto a receita bruta de produtos (R$ 1.087.154.072,52) quanto a receita líquida total faturada (R$ 1.026.984.182,65) sem ambiguidade e sem risco de distorção fiscal.

**O que se perde:** Perde-se a dependência exclusiva do total de cabeçalho bruto dos sistemas legados como valor canônico autônomo. A integridade contábil passa a depender do alinhamento relacional entre cabeçalho e linhas de itens. Pequenas variações de centavos decorrentes de arredondamentos pontuais no legado são uniformizadas pela agregação das linhas de itens. Caso analistas necessitem do valor literal original sem tratamento de sentinelas, deverão consultar as tabelas de staging brutas (`stg.legado_pedidos`), pois o DW reflete unicamente a visão contábil conformada.

**Registros afetados:** 410.000 pedidos (100,00% da base consolidada: 130.000 do legado [31,71%] e 280.000 do e-commerce [68,29%]), além de 1.392.453 itens vinculados e normalizados.

**Asserção associada:** Etapa 02 (`02_transformacao.py`), asserções:
- `identidade contábil valor_total`: validação de que $|\text{valor}{\text{total}} - (\text{valor}{\text{mercadoria}} + \text{valor}{\text{frete}} - \text{valor}_{\text{desconto}})| \le 0,01$ para todos os $410.000$ pedidos. Resultado: $410.000$ aprovados ($0$ divergências).
- `soma de mercadoria bate com itens`: validação de que a soma de `valor_mercadoria` nos pedidos coincide exatamente com a soma de `valor_bruto` nas linhas de itens. Resultado: $410.000$ aprovados ($0$ divergências).
Resultados auditados e persistidos na tabela `qa.execucao_assercao`.

<br>
<br>

### Ficha RDT-06 — Tratamento de Frete Negativo e Desconto Sentinela `-1`

**Decisão:** saneamento de anomalias operacionais de domínio nos componentes de valores: truncamento de valores de frete negativos para `0.00` via `GREATEST(0, frete)` com ativação de `flag_frete_negativo = TRUE`, e conversão de descontos sentinela `-1.00` para `0.00` com ativação de `flag_desconto_sentinela = TRUE`.

**Etapa do pipeline:** 02_transformacao · `conforma_valores`

**O que o dado mostrava:** 
A inspeção da base consolidada em escala 1.0 (seed 20262) revelou duas anomalias que violam premissas de domínio físico e contábil:
1. *Frete Negativo:* Presente em $1.174$ pedidos ($0,286%$ dos $410.000$ pedidos), sendo $362$ pedidos no ERP Legado ($0,278%$ do canal; variação de -R$ 88,78 a -R$ 0,01; soma: -R$ 16.098,86; média: -R$ 44,47) e 812 pedidos no E-commerce (0,290% do canal; variação de -R$ 78,86 a -R$ 0,01; soma: -R$ 32.248,65; média: -R$ 39,72). No ERP Legado, a prova contábil demonstrou que em 100,0% dos 362 pedidos o total faturado subtraiu o frete negativo, evidenciando uso do campo como artifício para conceder subsídio logístico ou estorno comercial ao cliente. No total, as anomalias de frete perfazem -R$ 48.347,51.
2. *Desconto Sentinela `-1`:* Presente em 4.056 linhas de itens do ERP Legado (1,021% dos itens do canal), afetando 4.003 pedidos distintos (3,079% dos pedidos do legado). Não existe nenhum outro valor negativo além do literal exato `-1.00`. No E-commerce, essa anomalia é inexistente (0 itens). Trata-se de código sentinela legado para indicar produto inelegível para descontos promocionais. Se calculado aritmeticamente na receita líquida ($\text{Preço} \times \text{QTD} - \text{Desconto}$), geraria $-(-1) = +1$, inflacionando artificialmente a receita em R$ 4.056,00.

**Alternativas consideradas:**

*Para Frete Negativo:*
1. *Manter valores negativos brutos:* Descartada: gera custos de transporte negativos nos cubos OLAP do DW, distorcendo relatórios de despesas logísticas por transportadora e médias de frete por UF.
2. *Inverter o sinal (`ABS(frete)`):* Descartada: arbitrária e contrafactual. A reconciliação do legado provou que o valor foi abatido e não cobrado a mais do cliente; inverter o sinal computaria cobrança indevida.
3. *Truncar em `0.00` e registrar indicador de anomalia (`flag_frete_negativo`):* Estabelecer $\text{valor}_{\text{frete}} = \max(0, \text{frete})$ e sinalizar a ocorrência com booleano.

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

<br>
<br>

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

<br>
<br>

### Ficha RDT-08 — Classificação de Ausências, Sentinela 1900-01-01 e Inversão Temporal

**Decisão:** classificação formal das ausências em três categorias analíticas (não coletada, não aplicável e código sentinela) e saneamento das anomalias cronológicas de entrega: conversão da data-sentinela `1900-01-01 00:00:00` para `NULL` com ativação de `flag_entrega_sem_data = TRUE`, anulação de datas de entrega invertidas (`DT_ENTREGA < DT_PEDIDO`) com ativação de `flag_entrega_inconsistente = TRUE`, e preservação de `NULL` para ausências estruturais de pedidos não entregues.

**Etapa do pipeline:** 02_transformacao · `trata_datas_e_ausencias`

**O que o dado mostrava:** 
O perfilamento empírico da base total de 410.000 pedidos (escala 1.0, seed 20262) revelou anomalias cronológicas severas e dados ausentes com naturezas epistemológicas distintas:
1. *Sentinela `1900-01-01 00:00:00` (1.025 pedidos, 0,788% do legado; 0,250% do DW):* Concentrada exclusivamente em pedidos do ERP Legado. Exatos 1.025 de 1.025 pedidos (100,0%) possuem status `ENTREGUE`. Nenhum pedido cancelado ou em separação possui esse valor. Trata-se de código sentinela imposto por restrição técnica de banco de dados (`NOT NULL`) quando a entrega física ocorreu, mas o comprovante de data não foi digitado.
2. *Inversões Temporais `DT_ENTREGA < DT_PEDIDO` (2.458 pedidos entregues, 0,797% dos 308.396 pedidos entregues):* Presente em ambas as origens (775 pedidos no legado [0,766% dos entregues] e 1.683 pedidos no e-commerce [0,812% dos entregues]), com entregas registradas entre 1 e 5 dias antes da compra. Trata-se de violação da causalidade física gerada por preenchimento retroativo em lojas físicas ou desajuste de relógio de servidores.
3. *Ausências Estruturais e Não Coletadas:* 101.604 pedidos (28.808 legado e 72.796 e-commerce) legitimamente não possuem data de entrega por não terem sido entregues (cancelados, processamento, em trânsito); 933 clientes do legado apresentam cidade mascarada com `"N/A"`; 5.856 atendimentos do SAC não possuem data de fechamento por estarem em aberto.

**Alternativas consideradas:**

*Para a Sentinela `1900-01-01`:*
1. *Manter como data válida:* Descartada: geraria prazos de entrega calculados (`dias_entrega`) de aproximadamente 45.000 dias (mais de 120 anos), explodindo a variância e invalidando médias de SLA, regressões e algoritmos de árvore de decisão.
2. *Converter para `NULL` sem indicador:* Descartada: apaga a distinção essencial entre "pedido concluído cuja data de recebimento falhou" e "pedido cancelado/extraviado que nunca foi entregue".
3. *Converter para `NULL` e criar o indicador booleano `flag_entrega_sem_data`:* Adotada.

*Para as Inversões Temporais (`DT_ENTREGA < DT_PEDIDO`):*
1. *Manter as datas originais:* Descartada: gera prazos de entrega negativos (`dias_entrega < 0`), violando a flecha do tempo e introduzindo ruído estatístico.
2. *Inverter as colunas (`DT_PEDIDO <-> DT_ENTREGA`):* Descartada: premissa contrafactual e infundada; não há base empírica para afirmar que o operador trocou os campos.
3. *Anular a data de entrega e criar a flag `flag_entrega_inconsistente`:* Adotada.

**Decisão:** alternativa 3 para ambas as anomalias, acompanhada da classificação estrita de ausências: preservação de `NULL` para ausências não aplicáveis (pedidos cancelados sem entrega) e não coletadas (textos opcionais).

**Justificativa:** Protege os modelos analíticos e preditivos contra distorções aberrantes de prazo (eliminando outliers de 45.000 dias e prazos negativos), garantindo que os prazos de entrega válidos no DW variem estritamente entre 1 e 20 dias (média real homologada de 8,47 dias). A retenção das flags booleanas de auditoria preserva 100% da rastreabilidade para mineração de falhas operacionais e estudos de qualidade de atendimento.

**O que se perde:** Perde-se a data real fática de entrega dos 1.025 pedidos sentinela e dos 2.458 pedidos com inversão temporal, que é irrecuperável nos sistemas de origem. Métricas de tempo médio de entrega passam a excluir esses 3.483 pedidos (1,13% dos pedidos entregues), o que pode subestimar levemente o SLA médio caso as falhas de registro tenham se concentrado em entregas lentas ou problemáticas.

**Registros afetados:** 
- Data sentinela 1900: 1.025 pedidos (0,788% do legado; 0,250% dos 410.000 pedidos do DW).
- Inversão temporal de entrega: 2.458 pedidos (0,797% dos pedidos entregues; 775 legado e 1.683 e-commerce).
- Total de pedidos impactados no cálculo de SLA: 3.483 pedidos (0,850% da base consolidada).

**Asserção associada:** Etapa 02 (`02_transformacao.py`), asserções:
- `sem sentinela 1900 dw`: valida 0 pedidos remanescentes com data em 1900.
- `prazo entrega nao negativo`: valida 0 pedidos com `dt_entrega_conformada < dt_pedido_conformada`.
- `quantificacao sentinela 1900`: valida contagem exata de 1.025 pedidos com `flag_entrega_sem_data = TRUE`.
- `quantificacao inversao temporal total`: valida contagem exata de 2.458 pedidos com `flag_entrega_inconsistente = TRUE`.
- `quantificacao inversao temporal legado`: valida 775 pedidos no legado.
- `quantificacao inversao temporal ecom`: valida 1.683 pedidos no e-commerce.
- `menor prazo de entrega valido`: valida que o menor prazo calculado é $\ge 0,0$ dias (obtido: 1,00 dia).
- `ausencias estruturais preservadas`: valida 0 entregas conformadas em pedidos não entregues.
Todas auditadas e registradas na tabela `qa.execucao_assercao`.

<br>
<br>

### Ficha RDT-09 — Padronização Temporal em UTC entre os Sistemas de Origem

**Decisão:** padronização uniforme de todas as datas e eventos transacionais no tipo canônico `TIMESTAMPTZ` em UTC, interpretando os dados temporais ingênuos (sem fuso horário do ERP Legado e 19,95% do Marketplace) sob o fuso oficial de referência comercial brasileiro (`America/Sao_Paulo` / UTC-3).

**Etapa do pipeline:** 02_transformacao · `conforma_valores` e `trata_datas_e_ausencias`

**O que o dado mostrava:** 
O perfilamento empírico da base total de 410.000 pedidos e 160.000 avaliações (escala 1.0, seed 20262) revelou três convenções de fuso horário heterogêneas e assimétricas entre os sistemas:
1. *ERP Legado (130.000 pedidos, 31,71% da base):* Registros em MySQL utilizavam `DATETIME` ingênuo sem fuso horário (ex.: `2025-06-30 21:46:00`), correspondente ao horário local comercial da sede (UTC-3). Na ingestão direta para o PostgreSQL DW cujo fuso de sessão é `Etc/UTC`, o banco assumia implicitamente UTC (+00:00), criando defasagem física artificial de 3 horas em 100% dos pedidos.
2. *E-commerce (280.000 pedidos, 68,29% da base):* Registros em PostgreSQL utilizavam `TIMESTAMPTZ` nativo gravados com offset `-03` (ex.: `2025-06-30 21:46:00-03`), convertidos automaticamente pelo motor de banco para UTC (`2025-07-01 00:46:00+00`).
3. *Marketplace (160.000 avaliações):* 128.085 avaliações (80,05%) possuíam fuso explícito `-03:00`, ao passo que 31.915 avaliações (19,95%) apresentavam strings ISO sem fuso (anomalia D11c).
4. *Fronteira Crítica do Corte Preditivo (`2025-06-30 23:59:59 UTC`):* Na faixa noturna entre 21:00:00 e 23:59:59 horário local de 30/06/2025, foram identificados 11 pedidos no ERP Legado e 37 pedidos no E-commerce. Sem o alinhamento de fuso, os 11 pedidos do legado eram incorretamente retidos na janela de atributos preditivos (até 30/06), enquanto compras virtuais ocorridas no mesmo segundo físico eram alocadas em 01/07 (janela do alvo), violando a causalidade e criando assimetria entre canais.

**Alternativas consideradas:**
1. *Manter timestamps ingênuos como UTC sem ajuste:* Descartada: gera assimetria de 3 horas entre lojas físicas e virtuais; assume contrafactualmente que os PDVs operavam no Meridiano de Greenwich e causa falso positivo de corte preditivo.
2. *Converter todas as datas para Horário Local de Brasília (`America/Sao_Paulo` / UTC-3):* Descartada: entra em conflito com as convenções dos contêineres e do PostgreSQL DW (que operam canonicamente em UTC) e dificulta a portabilidade do pipeline analítico.
3. *Padronizar integralmente em UTC (`TIMESTAMPTZ`), interpretando campos ingênuos sob `America/Sao_Paulo`:* Adotada.

**Decisão:** alternativa 3.

**Justificativa:** Restaura a comparabilidade física e causal absoluta entre todas as transações da organização. Ao aplicar `AT TIME ZONE 'America/Sao_Paulo'` na ingestão do legado e das avaliações do marketplace, garante-se que pedidos realizados simultaneamente em loja física ou e-commerce recebam a mesma marcação temporal canônica em UTC. Protege a partição temporal do corte analítico contra vazamentos sutis de fim de mês.

**O que se perde:** Perde-se a hora visual "de relógio de parede" da loja física na representação atômica da coluna `TIMESTAMPTZ` (uma compra física das 21:46 em Cuiabá passa a constar como 00:46 UTC do dia subsequente). Relatórios operacionais que demandem a hora local civil de fechamento de caixa devem explicitamente projetar `AT TIME ZONE 'America/Sao_Paulo'`.

**Registros afetados:** 
- 130.000 pedidos do ERP Legado (100,0% da origem; 31,71% do total de 410.000 pedidos do DW) ajustados em +3 horas para UTC.
- 31.915 avaliações do Marketplace sem fuso (19,95% das avaliações) padronizadas em UTC.
- 11 pedidos noturnos do legado em 30/06/2025 realocados da janela de atributos para a janela pós-corte UTC (resultando em 108.059 pedidos do legado até o corte e 21.941 pós-corte; 341.546 consolidados até o corte e 68.454 pós-corte).

**Asserção associada:** Etapa 02 (`02_transformacao.py`), asserções:
- `dt_pedido sem nulos`: valida 0 pedidos com data de pedido nula no DW.
- `pedidos conformados ate corte utc`: valida contagem exata de 341.546 pedidos conformados até `2025-06-30 23:59:59+00` (108.059 legado + 233.487 e-commerce).
- `pedidos conformados pos corte utc`: valida contagem exata de 68.454 pedidos pós-corte temporal no DW (21.941 legado + 46.513 e-commerce).
- `alinhamento legado ate corte`: valida 108.059 pedidos do legado até a data de corte UTC (atestando a realocação das 11 compras noturnas).
Todas auditadas e registradas na tabela `qa.execucao_assercao`.

<br>
<br>

### Ficha RDT-10 — Itens Orfãos

**Decisão:** 

**Etapa do pipeline:** 

**O que o dado mostrava:** 


**Alternativas consideradas:**


**Decisão:**

**Justificativa:** 

**O que se perde:** 

**Registros afetados:** 

**Asserção associada:** 

<br>
<br>

### Ficha RDT-11 — Declaração de grão de `fato_pedido` e `fato_item_pedido`

**Decisão:** adoção da arquitetura dimensional de grão duplo (*dual grain* de Ralph Kimball), segregando a transação do pedido (`dw.fato_pedido`) das linhas de produtos comercializados (`dw.fato_item_pedido`), com a formalização das declarações canônicas de grão:
1. *"Uma linha de `dw.fato_pedido` representa a transação de um pedido de compra individual emitido por um cliente em uma data e canal específicos."*
2. *"Uma linha de `dw.fato_item_pedido` representa a ocorrência de um produto comercializado (linha de item) dentro de um determinado pedido."*

**Etapa do pipeline:** 03_carga_dw · `carrega_fato_pedido` e `carrega_fato_item`

**O que o dado mostrava:** 
As origens transacionais (ERP Legado no MySQL e E-commerce no PostgreSQL) operam com arquiteturas relacionais de cabeçalho e detalhe:
- **Cabeçalhos de pedidos:** 130.000 pedidos no ERP Legado (`PEDIDOS`) e 280.000 pedidos no E-commerce (`orders`), totalizando 410.000 transações de compra consolidadas.
- **Itens de pedidos:** 397.453 itens no Legado (`ITENS_PEDIDO`) e 995.000 itens no E-commerce (`order_item`), totalizando 1.392.453 linhas de itens (uma média de ~3,4 itens por pedido).
Métricas financeiras como frete e status de entrega existem exclusivamente no grão do pedido, ao passo que métricas como quantidade, preço unitário e desconto por item existem no grão do produto.

**Alternativas consideradas:**
1. *Grão Único de Item (Fato Desnormalizada 1:N):* Armazenar apenas uma tabela-fato no grão de item, repetindo os atributos de cabeçalho (data do pedido, cliente, status, frete) em cada linha de item. Descartada: destrói a aditividade das métricas de cabeçalho. Ao calcular o frete total ou faturamento via `SUM()`, os valores seriam multiplicados pela quantidade de itens do pedido, gerando distorções financeiras graves nos relatórios gerenciais e na ABT.
2. *Grão Único de Pedido (Fato Agregada 1:1):* Armazenar apenas uma tabela-fato no grão de pedido, descartando a granularidade atômica dos produtos ou agregando-os em listas/contagens simples. Descartada: inviabiliza análises de cesta de compras (*market-basket*), propensão de compra por categoria de produto e associação de produtos na mineração de dados.
3. *Grão Duplo de Kimball (Duas Tabelas-Fato Complementares):* Implementar `dw.fato_pedido` (grão de pedido) e `dw.fato_item_pedido` (grão de item) ligadas por chave estrangeira (`pedido_sk`). Adotada.

**Decisão:** Alternativa 3.

**Justificativa:** 
Garante conformidade matemática e aditividade perfeita em 100% das métricas do DW, respeitando os princípios de modelagem dimensional de Kimball. Na `dw.fato_pedido`, métricas de nível de transação (`valor_total`, `valor_frete`, `dias_entrega`) somam e tiram média de forma consistente sem risco de produto cartesiano. Na `dw.fato_item_pedido`, métricas atômicas de produto (`quantidade`, `valor_unitario`, `valor_linha`) permitem análises profundas de sortimento e afinidade de categorias sem contaminar os totais de caixa da empresa.

**O que se perde:** 
Perde-se a simplicidade de consultar uma tabela única desnormalizada. Para análises que cruzam atributos do cliente/pedido com o produto específico comprado, analistas precisam realizar um `JOIN` entre as duas tabelas-fato (`fato_pedido` e `fato_item_pedido`), aumentando a complexidade das consultas OLAP.

**Registros afetados:** 
- `dw.fato_pedido`: 410.000 pedidos consolidados (130.000 do legado e 280.000 do e-commerce).
- `dw.fato_item_pedido`: 1.392.453 itens vinculados (397.453 do legado e 995.000 do e-commerce).

**Asserção associada:** 
- `qa.igual("total fato_pedido", ...)`: Validação de 410.000 pedidos carregados.
- `qa.igual("total fato_item_pedido", ...)`: Validação de integridade dos itens.
- `qa.igual("reconciliacao financeira legado", ...)`: Validação de que $\sum \text{valor}_{\text{total}}$ bate com a origem em $\pm 0,1\%$.
- `qa.igual("reconciliacao financeira ecommerce", ...)`: Validação de faturamento sem distorção por multiplicidade de itens.

<br>
<br>

### Ficha RDT-12 — Pedidos sem cliente correspondente

**Decisão:** Inserção do cliente sentinela canônico `DESCONHECIDO` (`cliente_sk = -1`) na dimensão `dw.dim_cliente` para associação relacional dos 38.699 pedidos que não possuem cliente mapeado em `dw.dim_cliente`, assegurando a integridade referencial estrita (`REFERENCES dw.dim_cliente`) e a retenção integral de R$ 95.206.869,23 de faturamento corporativo na reconciliação financeira de Ralph Kimball em $\pm 0,1\%$.

**Etapa do pipeline:** 03_carga_dw · `carrega_dimensoes` e `carrega_fato_pedido`

**O que o dado mostrava:** 
Na reconciliação relacional entre os 410.000 pedidos conformados (`stg.pedidos_valores_conformados`) e a dimensão consolidada `dw.dim_cliente`, o cruzamento de chaves apurou **38.699 pedidos (9,44% de toda a base)** cujos identificadores de cliente originais (`id_cliente_origem`) não existem na dimensão unificada:
1. *No ERP Legado:* 16.183 pedidos (12,45% dos 130.000 pedidos do canal físico) referenciam `ID_CLIENTE` inexistentes em `dw.dim_cliente` (decorrentes de vendas balcão anônimas e clientes antigos expurgados no desempate da deduplicação interna do legado no RDT-03). O montante financeiro desses pedidos perfaz **R$ 35.263.082,14** (ticket médio de R$ 2.179,02).
2. *No E-commerce:* 22.516 pedidos (8,04% dos 280.000 pedidos do canal virtual) referenciam `customer_id` inexistentes no cadastro de clientes, totalizando **R$ 59.943.787,09** (ticket médio de R$ 2.662,28).
No total consolidado, as compras órfãs de clientes representam **R$ 95.206.869,23** em receita faturada.

**Alternativas consideradas:**
1. *Descarte dos Pedidos Órfãos:* Excluir os 38.699 pedidos da carga de `dw.fato_pedido`. Descartada: violação contábil inaceitável. Descartaria 9,44% do volume de pedidos e R$ 95,2 milhões em faturamento real de caixa da empresa, corrompendo a reconciliação financeira de Ralph Kimball em $\pm 0,1\%$ e destruindo a integridade dos relatórios corporativos.
2. *Geração de Clientes Sintéticos Dinâmicos (1:1):* Inserir 38.699 novos registros fictícios na `dw.dim_cliente` para cada pedido órfão. Descartada: inflacionaria artificialmente o catálogo de clientes em 36,2% (passando de 106.937 para 145.636 clientes), gerando severo ruído amostral na engenharia de atributos da ABT da Semana 4 e na apuração de métricas demográficas de clientes reais.
3. *Cliente Sentinela Canônico de Kimball (`DESCONHECIDO`):* Inserir um registro permanente na dimensão `dw.dim_cliente` com identificador sentinela fixo (`cliente_sk = -1`), atributos descritivos padronizados (`nome_padronizado = 'CLIENTE DESCONHECIDO'`, `origem_unificacao = 'SISTEMA'`), atribuindo `cliente_sk = -1` a todos os 38.699 pedidos sem cadastro prévio. Adotada.

**Decisão:** Alternativa 3.

**Justificativa:** 
Representa a melhor prática canônica da modelagem dimensional de Ralph Kimball para tratamento de integridade referencial em fatos com dimensões incompletas. Permite satisfazer plenamente a restrição de integridade referencial `FOREIGN KEY (cliente_sk) REFERENCES dw.dim_cliente (cliente_sk)` em nível de DDL no PostgreSQL sem descartar um único centavo de faturamento. Preserva a aditividade estrita das métricas financeiras nas dimensões de tempo, status e canal de venda, ao mesmo tempo em que sinaliza explicitamente nos cubos analíticos que as transações ocorreram sob anonimato ou falha cadastral.

**O que se perde:** 
Perde-se a rastreabilidade do perfil demográfico, localização geográfica (cidade/UF) e histórico de recompra individual dos compradores dessas 38.699 transações. Clientes atribuídos à chave sentinela não pontuarão em atributos RFV (Recência, Frequência e Valor individual) na ABT preditiva da Semana 4, participando da mineração de dados apenas em agregações macro de produto, canal e sazonalidade.

**Registros afetados:** 
38.699 pedidos (9,44% da base transacional de 410.000 pedidos: 16.183 no legado e 22.516 no e-commerce), preservando R$ 95.206.869,23 de faturamento corporativo no DW.

**Asserção associada:** Etapa 03 (`03_carga_dw.py`), asserções:
- `sem_nulos cliente_sk em fato_pedido`: validação de que nenhum dos 410.000 pedidos possui `cliente_sk = NULL`.
- `total pedidos fato_pedido`: confirmação da carga exata de 410.000 pedidos.
- `pedidos cliente desconhecido`: validação da contagem exata de 38.699 pedidos associados à surrogate key sentinela (`cliente_sk = -1`).
- `reconciliacao financeira legado`: validação de convergência contábil de $\sum \text{valor}_{\text{total}}$ com a origem dentro de $\pm 0,1\%$.
- `reconciliacao financeira ecommerce`: validação de convergência contábil de $\sum \text{valor}_{\text{total}}$ com a origem dentro de $\pm 0,1\%$.

<br>
<br>

### Ficha RDT-13 — Atendimentos e avaliações que não ligam a nenhum pedido e heterogeneidade estrutural de produtos

**Decisão:** Carga integral dos fatos auxiliares `dw.fato_atendimento` (95.000 eventos únicos deduplicados a partir de 96.140 registros na staging) e `dw.fato_avaliacao` (160.000 eventos), com inferência de `cliente_sk` pelo pedido para os 5.918 atendimentos com CPFs não cadastrados, e desambiguação sintática de 40.016 avaliações de produtos físicos mascaradas sob `product_sku = 'LEG-{id_legado}'` via amarração com a chave primária `id_legado` de `dw.dim_produto`, preservando 23.654 interações de clientes dependentes das transações do RDT-12.

**Etapa do pipeline:** 03_carga_dw · `carrega_fatos_auxiliares`

**O que o dado mostrava:** 
A auditoria relacional nos dados de SAC (`stg.sac_atendimentos`) e Marketplace (`stg.marketplace_avaliacoes`) revelou duas heterogeneidades críticas de conectividade e uma anomalia de duplicação:
1. *Conectividade de Pedidos e Dependência do RDT-12:* Todos os atendimentos do SAC e todas as 160.000 avaliações de marketplace possuem códigos de pedido válidos na origem (`id_pedido_origem` e `order_ref`). Contudo, o perfilamento comprovou que **23.654 eventos de clientes** (9.195 atendimentos do SAC [9,56%] e 14.459 avaliações [9,04%]) referenciam exatamente os 38.699 pedidos sem cliente resolvidos no RDT-12. Se esses pedidos tivessem sido descartados no RDT-12, 23.654 interações de clientes se tornariam subitamente órfãs no DW com `pedido_sk = NULL`.
2. *Deduplicação e Inferência Cadastral no SAC:* A extração bruta de `stg.sac_atendimentos` continha 96.140 registros com 1.140 duplicatas idênticas de protocolo. A aplicação da restrição de unicidade canônica (`protocolo UNIQUE`) consolidou **95.000 atendimentos únicos**. Destes, 89.082 (93,77%) conectam diretamente ao cliente via CPF em `dw.dim_cliente`, mas 5.918 atendimentos (6,23%) apresentam CPFs ausentes do cadastro consolidado. Como o pedido correspondente existe no DW, a chave do cliente (`cliente_sk`) é herdada do próprio pedido.
3. *Heterogeneidade Sintática de Produtos nas Avaliações:* Das 160.000 avaliações do marketplace, 119.984 (74,99%) ligam diretamente ao produto através de `dw.dim_produto.sku` (catálogo virtual). Em contrapartida, **40.016 avaliações (25,01%)** referenciam produtos físicos do ERP Legado sob o código sintético `product_sku = 'LEG-{id_legado}'` (ex.: `LEG-1`, `LEG-10`, `LEG-1000`). Como a coluna `sku` para produtos físicos do legado é vazia em `dw.dim_produto`, uma junção ingênua (`dw.dim_produto.sku = a.product_sku`) deixaria 40.016 avaliações com `produto_sk = NULL`, desconectando 1/4 de todo o feedback de clientes sobre o catálogo físico.

**Alternativas consideradas:**
1. *Descarte de Eventos com Produtos Mascarados ou Sem Cadastro:* Descartar as 40.016 avaliações de produtos do legado e os atendimentos de SAC sem CPF cadastrado. Descartada: causaria perda severa de 25% das avaliações e mais de 6% do SAC, enviesando negativamente a modelagem preditiva de churn e recompra na ABT da Semana 4.
2. *Carga com Chaves Nulas (`pedido_sk = NULL` e `produto_sk = NULL`):* Ingerir as linhas mantendo chaves estrangeiras nulas sem tentar resolver a desambiguação sintática. Descartada: negligencia a heterogeneidade semântica/sintática gerada pela plataforma de marketplace, deixando de associar as avaliações às categorias de produtos que de fato foram avaliadas.
3. *Resolução Híbrida de Chaves com Desambiguação Sintática e Deduplicação:*
   - Para o SAC: Deduplicação exata de protocolos em 95.000 eventos únicos; manter `pedido_sk` 100% preenchido; resolver `cliente_sk` preferencialmente via CPF e, nos 5.918 casos ausentes, inferir `cliente_sk` diretamente da transação em `dw.fato_pedido`.
   - Para Avaliações: Manter `pedido_sk` 100% preenchido via `order_ref`; resolver `produto_sk` via junção direta no `sku` para o e-commerce e via extração numérica `SUBSTRING(product_sku FROM 5)::int = id_legado` para o catálogo físico. Adotada.

**Decisão:** Alternativa 3.

**Justificativa:** 
Garante integridade relacional e densidade informacional máxima em 100% dos fatos auxiliares. Ao recuperar o vínculo dos 40.016 produtos avaliados via `id_legado` e inferir o cliente dos 5.918 protocolos de atendimento pelo pedido, o Data Warehouse maximiza a precisão da engenharia de atributos preditivos para a Semana 4 (como nota média de satisfação por cliente e quantidade de chamados abertos), sem criar duplicidades nem descartar evidências empíricas reais.

**O que se perde:** 
Assume-se que o prefixo `LEG-` nas avaliações do marketplace reflete com 100% de exatidão a chave primária `ID_PRODUTO` do ERP Legado sem verificação cruzada de descrição textual. Nos 5.918 atendimentos com cliente inferido pelo pedido, assume-se que o solicitante do SAC é o próprio titular do pedido original de compra, descartando a possibilidade de reclamação aberta por terceiros. As 1.140 linhas duplicadas de protocolos idênticos foram expurgadas.

**Registros afetados:** 
- `dw.fato_atendimento`: 95.000 atendimentos carregados (100% com pedido conectado; 5.918 clientes inferidos via pedido; 1.140 duplicações sintáticas expurgadas; 9.195 eventos dependentes das transações do RDT-12).
- `dw.fato_avaliacao`: 160.000 avaliações carregadas (100% com pedido conectado; 40.016 produtos físicos desambiguados via `id_legado` [25,01% da base]; 14.459 eventos dependentes do RDT-12).

**Asserção associada:** Etapa 03 (`03_carga_dw.py`), asserções homologadas com 100% de aprovação:
- `total fato_atendimento`: validação de exatamente 95.000 atendimentos únicos carregados.
- `protocolos unicos fato_atendimento`: confirmação de 0 duplicados em `protocolo`.
- `total fato_avaliacao`: validação de exatamente 160.000 avaliações carregadas.
- `reviews unicos fato_avaliacao`: confirmação de 0 duplicados em `review_id`.
- `nulos pedido_sk em fato_atendimento` e `nulos pedido_sk em fato_avaliacao`: confirmação de 0 nulos em `pedido_sk`.
- `nulos produto_sk em fato_avaliacao`: confirmação de que todas as 160.000 avaliações possuem `produto_sk` resolvido (0 nulos).
- `nulos cliente_sk em fato_atendimento`: confirmação de que todos os 95.000 atendimentos possuem `cliente_sk` resolvido (0 nulos).
- `avaliacoes produtos legado conectadas`: confirmação de exatamente 40.016 avaliações ligadas ao catálogo físico.
- `avaliacoes produtos ecommerce conectadas`: confirmação de exatamente 119.984 avaliações ligadas ao catálogo virtual.

---

<br>

## Tabela-resumo

| Ficha  | Decisão                                                                               | Registros afetados                                            | % da base                            | Informação perdida?                                                                                                                                  |
| ------ | ------------------------------------------------------------------------------------- | ------------------------------------------------------------- | ------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| RDT-01 | Carga completa (full load)                                                            | 100% dos dados brutos das 4 origens na stg                    | 100,0%                               | Não (perda apenas de eficiência computacional: 3 a 5 min de recarga total a cada execução)                                                           |
| RDT-02 | Unificação de clientes por CPF                                                        | 106.937 clientes unificados em dw.dim_cliente                 | 100,0% da dim_cliente                | Sim (clientes sem CPF nas origens não foram unidos, fragmentando o histórico em dois cadastros)                                                      |
| RDT-03 | Deduplicação interna do legado                                                        | 5.849 registros duplicados expurgados                         | 12,38% do legado                     | Sim (histórico cadastral de endereços e telefones anteriores associados aos registros antigos descartados)                                           |
| RDT-04 | Conformação de status de pedidos                                                      | 410.000 pedidos (52.177 cancelados: 15.774 leg + 36.403 ecom) | 100,0% (12,7% cancelamentos)         | Sim (motivo de cancelamento dos 15.774 pedidos do legado permanece desconhecido e nulo, gerando assimetria entre canais)                             |
| RDT-05 | Decomposição contábil de VALOR_TOTAL e total_amount em 4 medidas                      | 410.000 pedidos                                               | 100,0%                               | Sim (dependência de cabeçalho bruto substituída por identidade aditiva de itens)                                                                     |
| RDT-06 | Truncamento de frete negativo e conversão de sentinela de desconto -1                 | 1.174 pedidos (frete) / 4.056 itens (desconto)                | 0,29% (pedidos) / 0,29% (itens)      | Sim (subsídios de frete de R$ 48.347,51 descartados do frete faturado; inelegibilidade retida em flag)                                               |
| RDT-07 | Conformação da taxonomia de produtos em 2 níveis e desambiguação léxica               | 3.000 produtos (legado)                                       | 20,0% do catálogo                    | Sim (categoria administrativa do legado sobreposta pela descrição fática; texto bruto retido em categoria_origem)                                    |
| RDT-08 | Classificação de ausências, anulação de 1900-01-01 e de inversões temporais com flags | 3.483 pedidos (1.025 sentinela 1900 + 2.458 invertidos)       | 0,85% da base                        | Sim (datas reais irrecuperáveis excluídas do cálculo de SLA; rastreabilidade retida em flags)                                                        |
| RDT-09 | Padronização temporal em UTC e conversão de fontes ingênuas sob Horário de Brasília   | 130.000 pedidos (legado) + 31.915 avaliações (marketplace)    | 31,7% (pedidos) / 19,9% (avaliações) | Sim (hora visual de relógio de parede nas lojas físicas substituída pelo padrão astronômico UTC; 11 pedidos noturnos de 30/06 alocados em 01/07 UTC) |
| RDT-10 | Itens órfãos                                                                          |                                                               |                                      |                                                                                                                                                      |
| RDT-11 | Declaração de grão de fato_pedido e fato_item_pedido                                  | 410.000 pedidos (fato_pedido) / 1.392.453 itens (fato_item)   | 100,0%                               | Não (preserva a aditividade atômica e agregada de Kimball; exige JOIN entre fatos para consultas combinadas)                                         |
| RDT-12 | Pedidos sem cliente correspondente (cliente sentinela DESCONHECIDO)                   | 38.699 pedidos (16.183 legado + 22.516 e-commerce)            | 9,44% dos pedidos                    | Sim (perfil demográfico individual perdido; preservados R$ 95.206.869,23 de faturamento corporativo no cliente DESCONHECIDO)                      |
| RDT-13 | Resolução sintática de produtos e fatos auxiliares (SAC e Avaliações)                 | 40.016 avaliações (SKU legado) + 5.918 SAC (cliente inferido) | 25,0% (avaliações) / 6,2% (SAC)      | Sim (assume-se que LEG-{id} mapeia o ID legado e que o reclamante do SAC é o titular da compra; 1.140 duplicações de protocolo no SAC deduplicadas)   |
| RDT-14 | Engenharia de atributos da ABT sem vazamento                                          |                                                               |                                      |                                                                                                                                                      |
| RDT-15 | Vazamentos introduzidos deliberadamente                                               |                                                               |                                      |                                                                                                                                                      |

---

## Reflexão final (máximo 400 palavras)

Responda, com base no que vocês viveram no projeto:

1. Qual das decisões acima mudaria mais o resultado do modelo se tivesse sido
   tomada de outro modo? Vocês testaram, ou é uma hipótese?
2. Alguma decisão que vocês tomaram por conveniência técnica teria consequência
   sobre pessoas reais, se este fosse um sistema em produção? Qual?
3. Qual informação vocês gostariam de ter tido, e não tinham?
