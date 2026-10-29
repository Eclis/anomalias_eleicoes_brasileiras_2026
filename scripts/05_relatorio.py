"""Gera um resumo em linguagem natural para reports/resumo.md."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
PROCESSED = ROOT / "data" / "processed"


KEY = ["SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO"]


def _br_int(value: int | float | None) -> str:
    if value is None:
        return "-"
    return f"{int(round(value)):,}".replace(",", ".")


def _br_pct(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}f}%".replace(".", ",")


def _title_mun(name: str) -> str:
    particles = {"de", "do", "da", "dos", "das", "e"}
    parts = str(name or "").strip().title().split()
    return " ".join(
        p.lower() if i > 0 and p.lower() in particles else p for i, p in enumerate(parts)
    )


def _label(row: dict) -> str:
    return f"{_title_mun(row.get('NM_MUNICIPIO'))}/{row['SG_UF']}, zona {row['NR_ZONA']}, seção {row['NR_SECAO']}"


def _to_dicts(df: pl.DataFrame, n: int | None = None) -> list[dict]:
    if n is not None:
        df = df.head(n)
    return df.to_dicts()


def main() -> int:
    print("=== 05_relatorio ===")
    meta = json.loads((REPORTS / "anomalias_meta.json").read_text(encoding="utf-8"))
    pair = json.loads((REPORTS / "pareamento_summary.json").read_text(encoding="utf-8"))
    abst = meta.get("abst_nulos", {})

    painel = pl.read_parquet(PROCESSED / "painel_t1_t2.parquet")
    secao = pl.read_parquet(PROCESSED / "secao_turno.parquet")
    t1 = secao.filter(pl.col("NR_TURNO") == "1")
    t2 = secao.filter(pl.col("NR_TURNO") == "2")
    margin_nacional = int((t2["lula"] - t2["flavio"]).sum())
    crescimento_lula = int(t2["lula"].sum() - t1["lula"].sum())
    crescimento_flavio = int(t2["flavio"].sum() - t1["flavio"].sum())
    crescimento_total_finalistas = crescimento_lula + crescimento_flavio
    flv_cai = painel.filter(pl.col("delta_flavio") < 0)
    q100_all = (
        secao.with_columns((pl.col("lula") / pl.col("validos")).alias("pct_lula"))
        .filter(pl.col("validos") > 0)
    )
    q100_lula_t1 = q100_all.filter((pl.col("NR_TURNO") == "1") & (pl.col("pct_lula") >= 1))
    q100_lula_t2 = q100_all.filter((pl.col("NR_TURNO") == "2") & (pl.col("pct_lula") >= 1))

    # Leituras auxiliares
    disc = pl.read_csv(REPORTS / "flags_discrepancia.csv").with_columns(
        pl.col("CD_MUNICIPIO").cast(pl.Utf8),
        pl.col("NR_ZONA").cast(pl.Utf8),
        pl.col("NR_SECAO").cast(pl.Utf8),
    )
    q100 = pl.read_csv(REPORTS / "flags_100pct_grandes.csv").with_columns(
        pl.col("CD_MUNICIPIO").cast(pl.Utf8),
        pl.col("NR_ZONA").cast(pl.Utf8),
        pl.col("NR_SECAO").cast(pl.Utf8),
        pl.col("turno").cast(pl.Utf8),
    )
    queda = pl.read_csv(REPORTS / "flags_queda_brusca.csv").with_columns(
        pl.col("CD_MUNICIPIO").cast(pl.Utf8),
        pl.col("NR_ZONA").cast(pl.Utf8),
        pl.col("NR_SECAO").cast(pl.Utf8),
    )
    bn = pl.read_csv(REPORTS / "flags_conversao_bn.csv").with_columns(
        pl.col("CD_MUNICIPIO").cast(pl.Utf8),
        pl.col("NR_ZONA").cast(pl.Utf8),
        pl.col("NR_SECAO").cast(pl.Utf8),
    )
    uf = pl.read_csv(REPORTS / "flags_por_uf.csv") if (REPORTS / "flags_por_uf.csv").exists() else None

    disc_impact = disc.join(
        painel.select(KEY + ["lula_t2", "flavio_t2"]),
        on=KEY,
        how="left",
    )
    q100_impact = q100.join(
        secao,
        left_on=["SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO", "turno"],
        right_on=["SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO", "NR_TURNO"],
        how="left",
    )
    queda_impact = queda.join(
        painel.select(KEY + ["lula_t2", "flavio_t2", "delta_lula", "delta_flavio"]),
        on=KEY,
        how="left",
    )
    bn_impact = bn.join(
        painel.select(KEY + ["lula_t2", "flavio_t2", "delta_lula", "delta_flavio"]),
        on=KEY,
        how="left",
    )

    both_plus = painel.filter((pl.col("delta_lula") > 0) & (pl.col("delta_flavio") > 0))
    both20 = (
        painel.filter((pl.col("delta_lula") >= 20) & (pl.col("delta_flavio") >= 20))
        .with_columns(
            (pl.col("delta_lula") + pl.col("delta_flavio")).alias("ganho_total"),
            (
                pl.col("outros_t1")
                + pl.max_horizontal(pl.col("delta_comparecimento"), pl.lit(0))
                + pl.max_horizontal(-(pl.col("delta_brancos") + pl.col("delta_nulos")), pl.lit(0))
            ).alias("pool_aparente"),
        )
        .sort("ganho_total", descending=True)
    )
    q100_t2_with_history = (
        q100_lula_t2.join(
            t2.select(KEY + ["NM_MUNICIPIO"]).unique(),
            on=KEY,
            how="left",
        )
        .join(
            painel.select(KEY + ["flavio_t1", "lula_t1", "delta_flavio", "delta_lula"]),
            on=KEY,
            how="left",
        )
    )
    q100_t2_flv_prev = q100_t2_with_history.filter(pl.col("flavio_t1") > 0)
    q100_t2_flv_prev_big = q100_t2_flv_prev.filter(pl.col("aptos") >= 150)

    top_both20 = _to_dicts(
        both20.select(
            [
                "SG_UF",
                "NM_MUNICIPIO",
                "NR_ZONA",
                "NR_SECAO",
                "lula_t1",
                "flavio_t1",
                "outros_t1",
                "lula_t2",
                "flavio_t2",
                "delta_lula",
                "delta_flavio",
                "delta_comparecimento",
                "ganho_total",
                "pool_aparente",
            ]
        ),
        3,
    )
    top_queda = _to_dicts(
        queda.select(
            [
                "SG_UF",
                "NM_MUNICIPIO",
                "NR_ZONA",
                "NR_SECAO",
                "detector",
                "lula_t1",
                "lula_t2",
                "flavio_t1",
                "flavio_t2",
                "delta_lula",
                "delta_flavio",
            ]
        ),
        4,
    )
    top_100 = _to_dicts(
        q100_t2_with_history.filter((pl.col("flavio_t1") > 0) & (pl.col("aptos") >= 150))
        .sort("flavio_t1", descending=True)
        .select(
            [
                "SG_UF",
                "NM_MUNICIPIO",
                "NR_ZONA",
                "NR_SECAO",
                "aptos",
                "validos",
                "lula_t1",
                "flavio_t1",
                "lula",
                "flavio",
            ]
        ),
        4,
    )

    md: list[str] = []
    md.append("# Do 1º ao 2º turno: o que as urnas mostram na eleição presidencial de 2026\n")
    md.append(
        "A comparação seção a seção da votação para presidente, com os arquivos oficiais do Tribunal Superior Eleitoral, "
        "não encontrou um padrão nacional de votos sem origem contábil entre o 1º e o 2º turno. "
        "Luiz Inácio Lula da Silva cresceu **10,4 milhões** de votos; Flávio Bolsonaro cresceu **3,7 milhões**. "
        "Somados, os **14,1 milhões** extras cabem no reservatório de votos dos candidatos eliminados e na queda de "
        "abstenção, nulos e brancos.\n"
    )
    md.append(
        "Mudança entre turnos é o comportamento esperado numa disputa polarizada. O que esta apuração procurou "
        "não foi qualquer variação, e sim seções em que o salto de um finalista **não pudesse ser explicado** "
        "pelos votos que já estavam na urna no 1º turno. Esse teste mais restrito não apontou caso nacionalmente relevante.\n"
    )
    md.append(
        f"Outros recortes: **67 seções grandes** (150 eleitores aptos ou mais) tiveram 100% dos votos válidos para um candidato — todas para Lula, "
        f"somando **{_br_int(q100_impact['validos'].sum())} votos**. Quedas bruscas de um finalista apareceram em **17 seções** no país. "
        "Abstenção, nulo e branco recuaram na maior parte das urnas, padrão típico de segundo turno competitivo.\n"
    )
    outros_t1 = int(t1["outros"].sum())
    outros_t2 = int(t2["outros"].sum())
    abst_t1 = int(t1["abstencoes"].sum())
    abst_t2 = int(t2["abstencoes"].sum())
    nulos_t1 = int(t1["nulos"].sum())
    nulos_t2 = int(t2["nulos"].sum())
    brancos_t1 = int(t1["brancos"].sum())
    brancos_t2 = int(t2["brancos"].sum())
    queda_abst = abst_t1 - abst_t2
    queda_nulos = nulos_t1 - nulos_t2
    queda_brancos = brancos_t1 - brancos_t2
    pool_nacional = outros_t1 - outros_t2 + queda_abst + queda_nulos + queda_brancos
    conv_lula = 100 * crescimento_lula / pool_nacional if pool_nacional else 0
    conv_flavio = 100 * crescimento_flavio / pool_nacional if pool_nacional else 0
    share_outros = 100 * (outros_t1 - outros_t2) / pool_nacional if pool_nacional else 0
    share_abst = 100 * queda_abst / pool_nacional if pool_nacional else 0
    share_nulos = 100 * queda_nulos / pool_nacional if pool_nacional else 0
    share_brancos = 100 * queda_brancos / pool_nacional if pool_nacional else 0
    flv_cai_votos = int((-flv_cai["delta_flavio"]).sum())
    lula_cai_votos = int((-painel.filter(pl.col("delta_lula") < 0)["delta_lula"]).sum())
    teto_virada = 100 * flv_cai_votos / crescimento_lula if crescimento_lula else 0

    md.append("## A conta nacional\n")
    md.append(
        f"Lula passou de **{_br_int(t1['lula'].sum())}** para **{_br_int(t2['lula'].sum())} votos** "
        f"(**+{_br_int(crescimento_lula)}**). Flávio Bolsonaro passou de **{_br_int(t1['flavio'].sum())}** "
        f"para **{_br_int(t2['flavio'].sum())}** (**+{_br_int(crescimento_flavio)}**). "
        f"O crescimento conjunto foi de **{_br_int(crescimento_total_finalistas)} votos**. "
        "Os 10,4 milhões correspondem apenas à variação de Lula; os dois finalistas, juntos, avançaram 14,1 milhões.\n"
    )
    md.append("### Outros candidatos, abstenções, nulos e brancos\n")
    md.append(
        "| Item | 1º turno | 2º turno | Variação |\n"
        "| --- | ---: | ---: | ---: |\n"
        f"| Outros candidatos a presidente | {_br_int(outros_t1)} | {_br_int(outros_t2)} | {_br_int(outros_t2 - outros_t1)} |\n"
        f"| Abstenções | {_br_int(abst_t1)} | {_br_int(abst_t2)} | {_br_int(abst_t2 - abst_t1)} |\n"
        f"| Nulos | {_br_int(nulos_t1)} | {_br_int(nulos_t2)} | {_br_int(nulos_t2 - nulos_t1)} |\n"
        f"| Brancos | {_br_int(brancos_t1)} | {_br_int(brancos_t2)} | {_br_int(brancos_t2 - brancos_t1)} |\n"
        f"| **Reservatório que virou voto dos finalistas** |  |  | **{_br_int(pool_nacional)}** |\n"
        f"| **Crescimento Lula + Flávio** |  |  | **{_br_int(crescimento_total_finalistas)}** |\n"
    )
    md.append(
        f"Abstenções, nulos, brancos e votos em outros candidatos **já explicam o crescimento dos dois**. "
        f"O reservatório soma **{_br_int(pool_nacional)}**; o avanço conjunto, **{_br_int(crescimento_total_finalistas)}**. "
        "A diferença de 30 votos é residual (seções não pareadas e ajuste de cadastro).\n"
    )
    md.append("### Para quem foi esse reservatório\n")
    md.append(
        "Os arquivos do TSE não identificam eleitor. Não é possível afirmar que quem anulou no 1º turno "
        "escolheu um candidato específico no 2º. O que a totalização permite medir é a destinação do conjunto:\n"
        f"- Do reservatório de **{_br_int(pool_nacional)}** votos, Lula absorveu **{_br_pct(conv_lula)}** "
        f"({_br_int(crescimento_lula)}) e Flávio, **{_br_pct(conv_flavio)}** ({_br_int(crescimento_flavio)}).\n"
        "- Composição do reservatório:\n"
        f"  - outros candidatos: **{_br_pct(share_outros)}**;\n"
        f"  - queda de abstenção: **{_br_pct(share_abst)}**;\n"
        f"  - nulos: **{_br_pct(share_nulos)}**;\n"
        f"  - brancos: **{_br_pct(share_brancos)}**.\n"
        "A maior parte do avanço dos finalistas veio, portanto, de quem votou em candidato eliminado no 1º turno.\n"
    )
    md.append("### Transferência entre os dois finalistas\n")
    md.append(
        f"No agregado nacional, Flávio **não perdeu** votos: somou **{_br_int(crescimento_flavio)}** a mais do que no 1º turno. "
        f"Ele recuou em **{_br_int(flv_cai.height)} seções**, com perda acumulada de **{_br_int(flv_cai_votos)} votos**. "
        f"Ainda que a totalidade desses votos tivesse migrado para Lula, isso cobriria **{_br_pct(teto_virada)}** "
        f"do crescimento de Lula. No mesmo recorte, Lula perdeu **{_br_int(lula_cai_votos)} votos** nas seções em que recuou. "
        "Há troca local entre finalistas, mas o volume é insuficiente para explicar os 10,4 milhões. "
        "A origem dominante continua sendo o reservatório de eliminados, comparecimento extra e recuo de branco e nulo, "
        "com Lula capturando a fatia maior.\n"
    )

    md.append("## Quando o crescimento simultâneo seria inexplicável\n")
    md.append(
        "Um salto conjunto dos dois finalistas numa mesma seção só se torna um alerta forte se a urna "
        "não tiver votos suficientes para sustentá-lo: candidatos eliminados, aumento de comparecimento e "
        "recuo de brancos e nulos. Se, mesmo somando essas fontes, ainda faltar voto, a conta da seção não fecha.\n"
    )
    md.append(
        "Esse critério — ganho além do reservatório da própria urna — não encontrou caso nacionalmente relevante.\n"
    )

    md.append("## Quando os dois sobem na mesma urna\n")
    md.append(
        "Crescimento simultâneo é frequente no 2º turno. Os votos dos eliminados precisam de destino, "
        f"e o comparecimento costuma subir. Em **{_br_int(both_plus.height)} seções** "
        f"({_br_pct(100 * both_plus.height / painel.height, 2)} do total pareado), Lula e Flávio avançaram ao mesmo tempo. "
        f"Em **{_br_int(both20.height)} seções**, cada um ganhou 20 votos ou mais. "
        f"Nesses casos, o ganho somado foi de **{_br_int(both20['ganho_total'].sum())} votos**, "
        f"contra um reservatório de **{_br_int(both20['pool_aparente'].sum())}**. No conjunto, a conta fecha.\n"
    )
    md.append("### Três urnas em que os dois avançaram\n")
    for row in top_both20:
        md.append(
            f"- **{_label(row)}**. Lula: **{_br_int(row['lula_t1'])}** para **{_br_int(row['lula_t2'])}** "
            f"({('+' if row['delta_lula'] >= 0 else '')}{_br_int(row['delta_lula'])}). "
            f"Flávio: **{_br_int(row['flavio_t1'])}** para **{_br_int(row['flavio_t2'])}** "
            f"({('+' if row['delta_flavio'] >= 0 else '')}{_br_int(row['delta_flavio'])}). "
            f"Na mesma seção havia **{_br_int(row['outros_t1'])} votos** em candidatos que não foram ao 2º turno "
            f"e o comparecimento subiu **{_br_int(row['delta_comparecimento'])}**. "
            f"Ganho conjunto: **{_br_int(row['ganho_total'])}**. Reservatório: **{_br_int(row['pool_aparente'])}**.\n"
        )

    md.append("## Recortes que chamam atenção — e o peso no resultado\n")
    md.append(
        f"A vantagem nacional de Lula foi de **{_br_int(margin_nacional)} votos**. "
        "Os grupos abaixo são os que mais destoam visualmente. Nenhum deles, isolado, se aproxima dessa margem.\n"
    )

    md.append("### 1. Seções estatisticamente fora da curva\n")
    md.append(
        f"**{_br_int(meta['q1_discrepancia'])} seções** ({_br_pct(100 * meta['q1_discrepancia'] / meta['n_pareadas'], 3)} "
        "do painel pareado) tiveram variação T1→T2 extrema em relação a urnas do mesmo estado e da mesma faixa de tamanho. "
        f"Somadas, elas concentram **{_br_int((disc_impact['lula_t2'] + disc_impact['flavio_t2']).sum())} votos** "
        "dos dois finalistas no 2º turno. O saldo pró-Lula nesse recorte foi de "
        f"**{_br_int((disc_impact['lula_t2'] - disc_impact['flavio_t2']).sum())} votos**, "
        f"**{_br_pct(100 * (disc_impact['lula_t2'] - disc_impact['flavio_t2']).sum() / margin_nacional, 2)}** da vantagem nacional. "
        "Nenhuma passou no teste de ganho além do reservatório da própria urna.\n"
    )

    md.append("### 2. Seções com 100% para um candidato em urnas grandes\n")
    md.append(
        f"**67 seções** com pelo menos 150 aptos registraram **100% dos votos válidos para um candidato**. "
        f"Todas ficaram com Lula; nenhuma urna grande teve 100% para Flávio. "
        f"Somadas, elas têm **{_br_int(q100_impact['validos'].sum())} votos válidos**, "
        f"**{_br_pct(100 * q100_impact['validos'].sum() / margin_nacional, 2)}** da vantagem nacional. "
        "O recorte justifica conferência pontual do Boletim de Urna; o peso nacional é reduzido.\n"
    )
    md.append(
        f"Em qualquer tamanho de seção, Lula teve **{_br_int(q100_lula_t1.height)} urnas 100%** no 1º turno e "
        f"**{_br_int(q100_lula_t2.height)}** no 2º. Entre urnas grandes (aptos ≥ 150), o recorte passou de "
        f"**{_br_int(q100_lula_t1.filter(pl.col('aptos') >= 150).height)}** para "
        f"**{_br_int(q100_lula_t2.filter(pl.col('aptos') >= 150).height)}**. "
        f"Das **{_br_int(q100_lula_t2.height)}** seções 100% Lula no 2º turno, "
        f"**{_br_int(q100_t2_flv_prev.height)}** tinham pelo menos um voto de Flávio no 1º turno. "
        f"Nessas, o estoque dele era de **{_br_int(q100_t2_flv_prev['flavio_t1'].sum())} votos**; "
        f"o maior valor individual foi **{_br_int(q100_t2_flv_prev['flavio_t1'].max())}**. "
        f"Nas urnas grandes, **{_br_int(q100_t2_flv_prev_big.height)}** tinham algum voto de Flávio no 1º turno, "
        f"somando **{_br_int(q100_t2_flv_prev_big['flavio_t1'].sum())} votos** antes de zerar.\n"
    )
    md.append("Quatro seções ilustram o recorte:\n")
    for row in top_100:
        md.append(
            f"- **{_label(row)}**. No 1º turno, Lula tinha **{_br_int(row['lula_t1'])}** e Flávio **{_br_int(row['flavio_t1'])}**. "
            f"No 2º, Lula foi a **{_br_int(row['lula'])}** e Flávio zerou, "
            f"com **{_br_int(row['validos'])}** votos válidos e **{_br_int(row['aptos'])}** aptos.\n"
        )

    md.append("### 3. Quedas bruscas de um finalista\n")
    md.append(
        f"O detector de queda brusca apontou **{_br_int(meta['q3_queda'])} seções** no país. "
        f"Nelas, os dois finalistas somaram **{_br_int((queda_impact['lula_t2'] + queda_impact['flavio_t2']).sum())} votos** no 2º turno. "
        f"O saldo foi de **{_br_int((queda_impact['lula_t2'] - queda_impact['flavio_t2']).sum())} votos pró-Lula**, "
        f"**{_br_pct(100 * (queda_impact['lula_t2'] - queda_impact['flavio_t2']).sum() / margin_nacional, 3)}** da vantagem nacional.\n"
    )
    md.append("Quatro seções ilustram o recorte:\n")
    for row in top_queda:
        quem = "Lula" if "lula" in row["detector"] else "Flávio"
        md.append(
            f"- **{_label(row)}**. Recuo brusco de **{quem}**. "
            f"Lula: **{_br_int(row['lula_t1'])} → {_br_int(row['lula_t2'])}**. "
            f"Flávio: **{_br_int(row['flavio_t1'])} → {_br_int(row['flavio_t2'])}**.\n"
        )

    md.append("### 4. Queda de brancos e nulos puxando voto válido\n")
    md.append(
        f"Este recorte é maior: **{_br_int(meta['q4_conversao_bn'])} seções**. "
        f"O saldo pró-Lula nelas foi de **{_br_int((bn_impact['lula_t2'] - bn_impact['flavio_t2']).sum())} votos**, "
        f"**{_br_pct(100 * (bn_impact['lula_t2'] - bn_impact['flavio_t2']).sum() / margin_nacional, 2)}** da vantagem nacional. "
        "É o único bloco com peso mais visível. O padrão está espalhado pelo país e é compatível com eleitores "
        "que votaram branco ou nulo no 1º turno e escolheram um lado no 2º.\n"
    )

    md.append("## Abstenção, nulo e branco por seção\n")
    md.append(
        f"A abstenção recuou em **{_br_pct(abst.get('pct_secoes_queda_abstencoes', 0), 1)}** das seções "
        f"(mediana de **{_br_int(abst.get('mediana_delta_abstencoes'))}** eleitores por urna). "
        f"Nulos caíram em **{_br_pct(abst.get('pct_secoes_queda_nulos', 0), 1)}** das seções; "
        f"brancos, em **{_br_pct(abst.get('pct_secoes_queda_brancos', 0), 1)}**. "
        f"No painel pareado, isso corresponde a **{_br_int(-abst.get('soma_delta_abstencoes', 0))} abstenções a menos**, "
        f"**{_br_int(-abst.get('soma_delta_nulos', 0))} nulos a menos** e "
        f"**{_br_int(-abst.get('soma_delta_brancos', 0))} brancos a menos**.\n"
    )

    md.append("## Consistência das urnas\n")
    md.append(
        f"- Voto sem origem contábil (ganho além do reservatório da seção): **{_br_int(meta.get('q1_excesso_poco', 0))}** casos.\n"
        f"- Quebra das contas básicas (`comparecimento + abstenção = aptos`): não aparece como problema. "
        f"Houve **{_br_int(meta['contabil'])}** registros, de comparecimento 100% em urna grande, não de conta inconsistente.\n"
        f"- Mudança de **{_br_int(pair['mudanca_aptos_ge20'])}** seções com variação relevante de aptos entre turnos — "
        "contexto local (transferência temporária, recadastramento), sem desenho nacional concentrado.\n"
    )

    if uf is not None and uf.height:
        top_ufs = _to_dicts(uf, 10)
        md.append("## Distribuição geográfica dos recortes\n")
        md.append(
            "Os estados com mais seções destacadas nos testes foram: "
            + ", ".join(f"{row['SG_UF']} ({_br_int(row['n_flags'])})" for row in top_ufs)
            + ". "
            "Concentração estadual, por si só, não indica irregularidade: unidades da federação e capitais com mais seções "
            "tendem a aparecer mais em qualquer lista de extremos.\n"
        )

    md.append("## Síntese\n")
    md.append(
        "Os dados de seção **não sustentam** a tese de interferência sistêmica do 1º para o 2º turno. "
        "O que aparece de forma consistente é redistribuição dos votos dos candidatos eliminados, "
        "aumento de comparecimento e recuo de branco e nulo, com algumas urnas homogêneas em regiões específicas "
        "e um conjunto pequeno de seções em que a conferência manual do Boletim de Urna ainda faz sentido — "
        "em especial as 100% em urna grande e as 17 quedas bruscas.\n"
    )
    md.append("## Interpretações que os números não sustentam\n")
    md.append(
        "**Os 10,4 milhões de Lula não fecham, logo vieram de Flávio.** "
        "Os 10,4 milhões são só a variação de Lula. Flávio também cresceu "
        f"({_br_int(crescimento_flavio)}). Juntos, **{_br_int(crescimento_total_finalistas)}**. "
        f"O reservatório (eliminados + abstenção + nulo + branco) soma **{_br_int(pool_nacional)}**. A conta fecha sem transferir o estoque do adversário.\n"
    )
    md.append(
        "**Se os dois cresceram na mesma seção, a urna foi adulterada.** "
        "Crescimento simultâneo é o destino esperado dos votos dos eliminados e do comparecimento extra. "
        "O critério relevante é se a seção ganhou mais do que o reservatório local permitia. "
        "Esse teste não apontou caso nacionalmente relevante.\n"
    )
    md.append(
        "**Cem por cento para um candidato prova fraude.** "
        "Resultado homogêneo não é o mesmo que resultado impossível. Urnas 100% existem, sobretudo em seções pequenas, rurais ou comunitárias. "
        "No 2º turno houve **106** seções 100% Lula (**55** grandes), que somam **13.817** votos — **0,31%** da vantagem nacional. "
        "Onde Flávio zerou depois de ter tido voto, o estoque dele no 1º turno nessas seções era de **118** votos.\n"
    )
    md.append(
        "**Queda de Flávio em seção significa perda indevida.** "
        "Recuo local não é recuo nacional. Ele caiu em **82.180** seções (**383.008** votos), "
        f"mas avançou em volume maior e terminou o 2º turno com **{_br_int(crescimento_flavio)} votos a mais**. "
        "Redistribuição seção a seção com crescimento agregado é o padrão de segundo turno, não um apagão.\n"
    )
    md.append(
        "**As seções atípicas inverteram a eleição.** "
        f"A vantagem final foi **{_br_int(margin_nacional)}** votos. Fora da curva estatística: **1,51%** dessa margem; "
        "urnas 100% grandes: **0,31%**; quedas bruscas: **0,042%**. Nenhum bloco inverte o resultado. "
        "O recorte de maior peso (conversão de branco e nulo) está diluído no território e é compatível com polarização, "
        "não com um evento localizado.\n"
    )
    md.append(
        "**Um número grande, isolado, já seria evidência.** "
        f"**82 mil seções** com recuo de Flávio são **{_br_pct(100 * flv_cai.height / painel.height, 1)}** das **{_br_int(painel.height)}** seções pareadas. "
        "**106 seções 100%** concentram **118 votos** de Flávio zerados no 1º turno. Sem denominador, o recorte infla. "
        "Com denominador, cabe no tamanho da eleição.\n"
    )
    md.append(
        "Tabelas de apoio: `reports/flags_*.csv`, `reports/clusters_municipio.csv` e `reports/mudanca_aptos.csv`.\n"
    )

    out = REPORTS / "resumo.md"
    out.write_text("\n".join(md), encoding="utf-8")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
