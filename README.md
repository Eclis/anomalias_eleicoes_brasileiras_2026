# Anomalias T1→T2 — Presidente 2026

Pipeline reprodutível que compara, seção a seção, a votação para presidente no 1º e no 2º turno de 2026, com arquivos oficiais do [TSE Dados Abertos](https://dadosabertos.tse.jus.br/dataset/resultados-2026).

O relatório completo, em linguagem jornalística, está em [`reports/resumo.md`](reports/resumo.md). Este README descreve o propósito, os métodos e as comparações. Os números nacionais e os recortes de impacto estão no resumo.

## Propósito

A pergunta que o projeto tenta responder não é “houve mudança entre turnos?” — mudança é o esperado no 2º turno, quando só restam dois candidatos, o comparecimento costuma subir e branco/nulo recuam. A pergunta é outra:

**Existe, no recorte nacional de seções, um padrão de votos sem origem contábil — isto é, crescimento de um finalista além do que a própria urna tinha para explicar?**

O trabalho parte de três restrições:

1. Fonte única: CSVs oficiais de votação por seção e de detalhe da apuração, cargo presidente (`CD_CARGO = 1`).
2. Unidade de análise: a seção eleitoral (~499 mil urnas pareadas), não o município nem o estado.
3. Distinção explícita entre **outlier estatístico** e **indício de interferência**. Um valor extremo não prova fraude. O sinal mais forte que o desenho admite seria a combinação de (a) ganho além do reservatório da urna, (b) concentração geográfica e (c) urna grande.

O projeto **não** atribui voto a eleitor, **não** acessa urna eletrônica nem Boletim de Urna automaticamente, e **não** conclui fraude a partir de homogeneidade (100% para um candidato). Homogeneidade é registrada e pesada em votos; prova exigiria conferência documental fora deste pipeline.

## O que foi comparado

Cada seção do 1º turno foi ligada à mesma seção do 2º turno pela chave `SG_UF + CD_MUNICIPIO + NR_ZONA + NR_SECAO`. Sobre esse painel, as comparações foram:

| Comparação | O que mede |
| --- | --- |
| Totais nacionais T1 vs T2 | Crescimento de Lula, de Flávio e dos dois juntos |
| Reservatório nacional | Votos em outros candidatos no 1º turno + queda de abstenção + queda de nulo + queda de branco, contra o crescimento conjunto dos finalistas |
| Destinação do reservatório | Fatia do bolo extra absorvida por cada finalista (não identifica eleitor) |
| Recuo local vs saldo nacional | Seções em que um finalista caiu, e se essa queda cobre o crescimento do outro |
| Crescimento simultâneo na mesma urna | Seções em que os dois avançam, e se o reservatório *daquela* urna explica o ganho conjunto |
| Variação relativa ao grupo de pares | Seção versus outras do mesmo estado e da mesma faixa de eleitores aptos |
| Homogeneidade | 100% e ≥95% dos válidos para um candidato, em qualquer tamanho e em urna grande (aptos ≥ 150) |
| Queda brusca de finalista | Recuo grande com comparecimento estável ou maior |
| Conversão de branco/nulo | Queda relevante de branco+nulo quase toda para um candidato |
| Identidades contábeis | `comparecimento + abstenção = aptos`; votos ≤ aptos |
| Geografia | Concentração das flags por município, zona e UF |
| Cadastro | Mudança grande de aptos entre turnos |

Candidatos eliminados no 1º turno entram apenas como estoque (`outros`). Branco é o votável 95; nulo, 96. Totais de presidente no 2º turno são conferidos contra a soma oficial do arquivo do TSE.

## Métodos

### Extração

`01_download.py` baixa os ZIPs oficiais. `02_etl.py` lê CSV (`;`, latin-1), filtra presidente, pivota Lula (13), Flávio (22), outros, brancos e nulos, junta o detalhe da apuração (aptos, comparecimento, abstenção) e grava parquet. Preferência pelo arquivo `_BR.csv` do detalhe, que concentra o cargo 1.

### Painel T1 ∩ T2

`03_parear.py` faz inner join das seções presentes nos dois turnos e reporta as que só existem em um. Calcula deltas absolutos e de percentual de válidos, além do **reservatório da seção** (poço-base):

```
poço-base = votos em eliminados no T1
          + max(Δcomparecimento, 0)
          + max(−(Δbrancos + Δnulos), 0)

excesso de um finalista = ganho dele − poço-base − max(−Δadversário, 0)
```

Excesso relevante (> 5 votos) é o critério contábil mais duro: a urna cresceu além do que tinha para crescer, mesmo depois de contar eliminados, comparecimento extra, recuo de branco/nulo e perda do adversário.

Seções são agrupadas em faixas de aptos para não comparar urna de 40 eleitores com urna de 400.

### Detectores (`04_anomalias.py`)

1. **Discrepância T1→T2.** Z-score robusto (mediana e MAD) da variação de votos e de percentual, dentro de UF × faixa de aptos. Ranking: `|z| > 4` e aptos ≥ 50. Critério estrito: o mesmo outlier **e** excesso sobre o poço > 5.
2. **100% / ≥95% / zero.** Urnas em que um candidato leva todos ou quase todos os válidos; também finalista com zero votos em urna grande. O recorte de impacto usa 100% com aptos ≥ 150.
3. **Queda brusca.** Finalista perde ≥ 20 votos e ≥ 15% do estoque do 1º turno, com comparecimento estável ou maior.
4. **Conversão de branco/nulo.** Queda de branco+nulo ≥ 15 votos, com ≥ 80% dessa queda indo para um único finalista.
5. **Contas da seção.** Identidades `comparecimento + abstenção = aptos` e votos ≤ aptos; comparecimento 100% em urna grande é listado à parte.
6. **Clusters.** Flags pareadas agregadas por município e por zona, para ver se extremos se concentram geograficamente.

Nenhum detector, sozinho, é tratado como prova. O relatório em [`reports/resumo.md`](reports/resumo.md) confronta cada recorte com a **vantagem nacional** (votos) e com o teste do poço.

### Relatório

`05_relatorio.py` gera o texto de [`reports/resumo.md`](reports/resumo.md): conta nacional, reservatório, crescimento simultâneo com exemplos de urna, impacto de cada recorte na margem final, e interpretações que os totais não sustentam.

## Como rodar

Python 3.10+ (o ambiente atual usa 3.10). Os ZIPs do TSE somam ~480 MB.

```bash
python -m pip install -r requirements.txt
python scripts/01_download.py   # baixa os ZIPs oficiais
python scripts/02_etl.py        # data/processed/secao_turno.parquet
python scripts/03_parear.py     # data/processed/painel_t1_t2.parquet
python scripts/04_anomalias.py  # reports/flags_*.csv
python scripts/05_relatorio.py  # reports/resumo.md
```

`data/raw/` e `data/processed/` não entram no git.

## Fontes

| Arquivo | URL |
| --- | --- |
| Presidente — votação por seção (BR) | https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_secao/votacao_secao_2026_BR.zip |
| Detalhe da apuração por seção | https://cdn.tse.jus.br/estatistica/sead/odsele/detalhe_votacao_secao/detalhe_votacao_secao_2026.zip |

## Saídas

- [`reports/resumo.md`](reports/resumo.md) — relatório detalhado para leitura
- `reports/flags_*.csv` — seções de cada teste
- `reports/clusters_municipio.csv` / `clusters_zona.csv` — concentração geográfica
- `reports/mudanca_aptos.csv` — seções com mudança grande de eleitores aptos
- `data/processed/secao_turno.parquet` — uma linha por seção × turno
- `data/processed/painel_t1_t2.parquet` — seções pareadas, com variação T1→T2
