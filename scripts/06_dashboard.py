"""Gera reports/dashboard.md + gráficos em reports/figures/."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
PROCESSED = ROOT / "data" / "processed"
FIGS = REPORTS / "figures"

# Paleta sóbria (não roxo/glow)
C_LULA = "#C0392B"
C_FLAVIO = "#1F4E79"
C_POOL = "#2C7A7B"
C_MUTED = "#718096"
C_BG = "#F7FAFC"
C_GRID = "#E2E8F0"
C_TEXT = "#1A202C"


def _br_int(value: int | float | None) -> str:
    if value is None:
        return "-"
    return f"{int(round(value)):,}".replace(",", ".")


def _br_pct(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}f}%".replace(".", ",")


def _style_ax(ax) -> None:
    ax.set_facecolor(C_BG)
    ax.tick_params(colors=C_TEXT, labelsize=9)
    for spine in ax.spines.values():
        spine.set_color(C_GRID)
    ax.yaxis.label.set_color(C_TEXT)
    ax.xaxis.label.set_color(C_TEXT)
    ax.title.set_color(C_TEXT)


def _savefig(fig, name: str) -> str:
    FIGS.mkdir(parents=True, exist_ok=True)
    path = FIGS / name
    fig.savefig(path, dpi=140, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return f"figures/{name}"


def chart_crescimento(lula_t1: int, lula_t2: int, flv_t1: int, flv_t2: int) -> str:
    fig, ax = plt.subplots(figsize=(7.2, 3.8))
    _style_ax(ax)
    x = [0, 1]
    w = 0.35
    ax.bar([i - w / 2 for i in x], [lula_t1 / 1e6, flv_t1 / 1e6], w, label="1º turno", color=C_MUTED)
    ax.bar(
        [i + w / 2 for i in x],
        [lula_t2 / 1e6, flv_t2 / 1e6],
        w,
        label="2º turno",
        color=[C_LULA, C_FLAVIO],
    )
    ax.set_xticks(x)
    ax.set_xticklabels(["Lula", "Flávio Bolsonaro"])
    ax.set_ylabel("Milhões de votos")
    ax.set_title("Votos válidos dos finalistas — 1º × 2º turno")
    ax.legend(frameon=False, fontsize=9)
    ax.grid(axis="y", color=C_GRID, linewidth=0.8)
    # anotações de delta
    ax.annotate(
        f"+{(lula_t2 - lula_t1) / 1e6:.1f} mi",
        xy=(0 + w / 2, lula_t2 / 1e6),
        xytext=(0, 6),
        textcoords="offset points",
        ha="center",
        fontsize=8,
        color=C_LULA,
    )
    ax.annotate(
        f"+{(flv_t2 - flv_t1) / 1e6:.1f} mi",
        xy=(1 + w / 2, flv_t2 / 1e6),
        xytext=(0, 6),
        textcoords="offset points",
        ha="center",
        fontsize=8,
        color=C_FLAVIO,
    )
    return _savefig(fig, "crescimento_finalistas.png")


def chart_reservatorio(
    outros: int, abst: int, nulos: int, brancos: int, cresc: int
) -> str:
    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    _style_ax(ax)
    labels = ["Eliminados", "↓ Abstenção", "↓ Nulos", "↓ Brancos", "Lula+Flávio"]
    vals = [outros / 1e6, abst / 1e6, nulos / 1e6, brancos / 1e6, cresc / 1e6]
    colors = [C_POOL, C_POOL, C_POOL, C_POOL, "#2D3748"]
    bars = ax.barh(labels[::-1], vals[::-1], color=colors[::-1], height=0.65)
    ax.set_xlabel("Milhões de votos")
    ax.set_title("Reservatório vs. crescimento conjunto dos finalistas")
    ax.grid(axis="x", color=C_GRID, linewidth=0.8)
    for bar, v in zip(bars, vals[::-1]):
        ax.text(
            v + 0.15,
            bar.get_y() + bar.get_height() / 2,
            f"{v:.2f}",
            va="center",
            fontsize=8,
            color=C_TEXT,
        )
    return _savefig(fig, "reservatorio.png")


def chart_destino(pct_lula: float, pct_flavio: float) -> str:
    fig, ax = plt.subplots(figsize=(5.5, 3.6))
    _style_ax(ax)
    wedges, texts, autotexts = ax.pie(
        [pct_lula, pct_flavio],
        labels=["Lula", "Flávio"],
        colors=[C_LULA, C_FLAVIO],
        autopct=lambda p: f"{p:.1f}%".replace(".", ","),
        startangle=90,
        wedgeprops=dict(width=0.55, edgecolor="white", linewidth=2),
        textprops=dict(color=C_TEXT, fontsize=10),
    )
    for t in autotexts:
        t.set_color("white")
        t.set_fontsize(10)
        t.set_fontweight("bold")
    ax.set_title("Quem absorveu o reservatório nacional")
    return _savefig(fig, "destino_reservatorio.png")


def chart_peso_recortes(rows: list[tuple[str, float]]) -> str:
    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    _style_ax(ax)
    labels = [r[0] for r in rows][::-1]
    vals = [r[1] for r in rows][::-1]
    colors = ["#E53E3E" if v >= 5 else "#DD6B20" if v >= 1 else C_MUTED for v in vals]
    bars = ax.barh(labels, vals, color=colors, height=0.6)
    ax.set_xlabel("% da vantagem nacional de Lula (4,43 mi)")
    ax.set_title("Peso visual dos recortes — nenhum inverte o resultado")
    ax.grid(axis="x", color=C_GRID, linewidth=0.8)
    ax.set_xlim(0, max(vals) * 1.25 if vals else 1)
    for bar, v in zip(bars, vals):
        ax.text(
            v + 0.15,
            bar.get_y() + bar.get_height() / 2,
            f"{v:.2f}%".replace(".", ","),
            va="center",
            fontsize=8,
            color=C_TEXT,
        )
    return _savefig(fig, "peso_recortes.png")


def chart_silva_jardim(sj_sec: pl.DataFrame, sj: dict) -> str:
    fig, axes = plt.subplots(1, 2, figsize=(8.5, 3.6), gridspec_kw={"width_ratios": [1.2, 1]})
    ax0, ax1 = axes
    _style_ax(ax0)
    _style_ax(ax1)

    deltas = sj_sec["delta_flavio"].to_list()
    ax0.axhline(0, color=C_GRID, linewidth=1)
    colors = [C_FLAVIO if d >= 0 else "#A0AEC0" for d in deltas]
    ax0.bar(range(len(deltas)), deltas, color=colors, width=0.85)
    ax0.set_title("Silva Jardim — Δ Flávio por seção")
    ax0.set_xlabel(f"{len(deltas)} seções (ordenado por zona/seção)")
    ax0.set_ylabel("Votos")
    ax0.grid(axis="y", color=C_GRID, linewidth=0.8)

    cats = ["Flávio T1", "Flávio T2", "Lula T1", "Lula T2"]
    vals = [sj["flavio_t1"], sj["flavio_t2"], sj["lula_t1"], sj["lula_t2"]]
    cols = [C_FLAVIO, C_FLAVIO, C_LULA, C_LULA]
    ax1.bar(cats, vals, color=cols, width=0.7)
    ax1.set_title("Totais municipais")
    ax1.tick_params(axis="x", rotation=25)
    ax1.grid(axis="y", color=C_GRID, linewidth=0.8)
    for i, v in enumerate(vals):
        ax1.text(i, v + 80, _br_int(v), ha="center", fontsize=7, color=C_TEXT)

    fig.tight_layout()
    return _savefig(fig, "silva_jardim.png")


def chart_hist_mun(mun_br: pl.DataFrame) -> str:
    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    _style_ax(ax)
    d = mun_br["delta_flavio"].clip(-2000, 4000).to_numpy()
    ax.hist(d, bins=60, color=C_FLAVIO, alpha=0.85, edgecolor="white", linewidth=0.3)
    ax.axvline(0, color=C_MUTED, linestyle="--", linewidth=1)
    ax.axvline(1, color="#DD6B20", linestyle="-", linewidth=1.2, label="Silva Jardim (+1)")
    ax.set_title("Distribuição do Δ Flávio por município (BR)")
    ax.set_xlabel("Δ votos Flávio (T2 − T1), cortado em ± extremos")
    ax.set_ylabel("Nº de municípios")
    ax.legend(frameon=False, fontsize=8)
    ax.grid(axis="y", color=C_GRID, linewidth=0.8)
    return _savefig(fig, "municipios_delta_flavio.png")


def main() -> int:
    print("=== 06_dashboard ===")
    meta = json.loads((REPORTS / "anomalias_meta.json").read_text(encoding="utf-8"))
    painel = pl.read_parquet(PROCESSED / "painel_t1_t2.parquet")
    secao = pl.read_parquet(PROCESSED / "secao_turno.parquet")
    t1 = secao.filter(pl.col("NR_TURNO") == "1")
    t2 = secao.filter(pl.col("NR_TURNO") == "2")

    lula_t1 = int(t1["lula"].sum())
    lula_t2 = int(t2["lula"].sum())
    flv_t1 = int(t1["flavio"].sum())
    flv_t2 = int(t2["flavio"].sum())
    d_lula = lula_t2 - lula_t1
    d_flv = flv_t2 - flv_t1
    d_conj = d_lula + d_flv
    margin = lula_t2 - flv_t2

    outros = int(t1["outros"].sum()) - int(t2["outros"].sum())
    q_abst = int(t1["abstencoes"].sum()) - int(t2["abstencoes"].sum())
    q_nulos = int(t1["nulos"].sum()) - int(t2["nulos"].sum())
    q_brancos = int(t1["brancos"].sum()) - int(t2["brancos"].sum())
    pool = outros + q_abst + q_nulos + q_brancos
    pct_lula = 100 * d_lula / pool if pool else 0
    pct_flavio = 100 * d_flv / pool if pool else 0

    mun_path = REPORTS / "municipios_variacao.csv"
    if mun_path.exists():
        mun = pl.read_csv(mun_path)
    else:
        raise SystemExit("Run 05_relatorio.py first (municipios_variacao.csv)")

    sj = mun.filter((pl.col("SG_UF") == "RJ") & (pl.col("NM_MUNICIPIO") == "SILVA JARDIM"))
    if sj.height != 1:
        raise SystemExit("Silva Jardim not found")
    sj_row = sj.to_dicts()[0]
    sj_sec = painel.filter(
        (pl.col("SG_UF") == "RJ") & (pl.col("CD_MUNICIPIO") == str(sj_row["CD_MUNICIPIO"]))
    ).sort(["NR_ZONA", "NR_SECAO"])

    mun_br = mun.filter(pl.col("SG_UF") != "ZZ")
    flv_abs1_br = mun_br.filter(pl.col("delta_flavio").abs() <= 1)
    flv_abs1 = mun.filter(pl.col("delta_flavio").abs() <= 1)
    flv_cai = mun.filter(pl.col("delta_flavio") < 0)
    flv_sobe = mun.filter(pl.col("delta_flavio") > 0)

    # impactos
    q100 = pl.read_csv(REPORTS / "flags_100pct_grandes.csv")
    queda = pl.read_csv(REPORTS / "flags_queda_brusca.csv").with_columns(
        pl.col("CD_MUNICIPIO").cast(pl.Utf8),
        pl.col("NR_ZONA").cast(pl.Utf8),
        pl.col("NR_SECAO").cast(pl.Utf8),
    )
    disc = pl.read_csv(REPORTS / "flags_discrepancia.csv").with_columns(
        pl.col("CD_MUNICIPIO").cast(pl.Utf8),
        pl.col("NR_ZONA").cast(pl.Utf8),
        pl.col("NR_SECAO").cast(pl.Utf8),
    )
    bn = pl.read_csv(REPORTS / "flags_conversao_bn.csv").with_columns(
        pl.col("CD_MUNICIPIO").cast(pl.Utf8),
        pl.col("NR_ZONA").cast(pl.Utf8),
        pl.col("NR_SECAO").cast(pl.Utf8),
    )
    key = ["SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO"]
    disc_i = disc.join(painel.select(key + ["lula_t2", "flavio_t2"]), on=key, how="left")
    queda_i = queda.join(painel.select(key + ["lula_t2", "flavio_t2"]), on=key, how="left")
    bn_i = bn.join(painel.select(key + ["lula_t2", "flavio_t2"]), on=key, how="left")

    # 100% grandes: validos from secao join
    q100c = q100.with_columns(
        pl.col("CD_MUNICIPIO").cast(pl.Utf8),
        pl.col("NR_ZONA").cast(pl.Utf8),
        pl.col("NR_SECAO").cast(pl.Utf8),
        pl.col("turno").cast(pl.Utf8),
    )
    q100_i = q100c.join(
        secao,
        left_on=["SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO", "turno"],
        right_on=["SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO", "NR_TURNO"],
        how="left",
    )
    peso_bn = 100 * (bn_i["lula_t2"] - bn_i["flavio_t2"]).sum() / margin
    peso_disc = 100 * (disc_i["lula_t2"] - disc_i["flavio_t2"]).sum() / margin
    peso_100 = 100 * q100_i["validos"].sum() / margin
    peso_queda = 100 * (queda_i["lula_t2"] - queda_i["flavio_t2"]).sum() / margin
    peso_abs1 = 100 * flv_abs1["delta_lula"].sum() / margin

    print("Rendering charts…")
    img_cresc = chart_crescimento(lula_t1, lula_t2, flv_t1, flv_t2)
    img_res = chart_reservatorio(outros, q_abst, q_nulos, q_brancos, d_conj)
    img_dest = chart_destino(pct_lula, pct_flavio)
    img_peso = chart_peso_recortes(
        [
            ("Conversão branco/nulo", float(peso_bn)),
            ("Fora da curva (z)", float(peso_disc)),
            ("Municípios |Δ Flávio|≤1 (Δ Lula)", float(peso_abs1)),
            ("100% urna grande", float(peso_100)),
            ("Queda brusca", float(peso_queda)),
        ]
    )
    img_sj = chart_silva_jardim(sj_sec, sj_row)
    img_hist = chart_hist_mun(mun_br)

    both_plus = painel.filter((pl.col("delta_lula") > 0) & (pl.col("delta_flavio") > 0))
    flv_cai_sec = painel.filter(pl.col("delta_flavio") < 0)

    md: list[str] = []
    md.append("# Dashboard — Presidente 2026 (1º → 2º turno)\n")
    md.append(
        "Versão visual e compacta. Texto completo: [`resumo.md`](resumo.md). "
        "Fonte: arquivos oficiais do TSE (votação e detalhe por seção).\n"
    )

    md.append("## Números-chave\n")
    md.append(
        "| Indicador | Valor |\n"
        "| --- | ---: |\n"
        f"| Crescimento Lula | +{_br_int(d_lula)} |\n"
        f"| Crescimento Flávio | +{_br_int(d_flv)} |\n"
        f"| Crescimento conjunto | +{_br_int(d_conj)} |\n"
        f"| Reservatório (eliminados + abst. + nulo + branco) | {_br_int(pool)} |\n"
        f"| Vantagem final Lula | {_br_int(margin)} |\n"
        f"| Voto sem origem (poço da seção) | **{_br_int(meta.get('q1_excesso_poco', 0))}** |\n"
        f"| Seções pareadas | {_br_int(painel.height)} |\n"
        f"| Seções em que os dois subiram | {_br_int(both_plus.height)} "
        f"({_br_pct(100 * both_plus.height / painel.height, 1)}) |\n"
    )

    md.append("## Conta nacional\n")
    md.append(f"![Crescimento dos finalistas]({img_cresc})\n")
    md.append(f"![Reservatório]({img_res})\n")
    md.append(
        "| Item | Variação T1→T2 |\n"
        "| --- | ---: |\n"
        f"| Outros candidatos | −{_br_int(outros)} |\n"
        f"| Abstenções | −{_br_int(q_abst)} |\n"
        f"| Nulos | −{_br_int(q_nulos)} |\n"
        f"| Brancos | −{_br_int(q_brancos)} |\n"
        f"| **Reservatório** | **{_br_int(pool)}** |\n"
        f"| **Lula + Flávio** | **+{_br_int(d_conj)}** |\n"
    )
    md.append(
        f"Diferença residual: **{_br_int(pool - d_conj)}** votos "
        "(seções não pareadas / cadastro).\n"
    )

    md.append("## Destino do reservatório\n")
    md.append(f"![Destino]({img_dest})\n")
    md.append(
        "| Finalista | Absorção | Votos |\n"
        "| --- | ---: | ---: |\n"
        f"| Lula | {_br_pct(pct_lula)} | {_br_int(d_lula)} |\n"
        f"| Flávio | {_br_pct(pct_flavio)} | {_br_int(d_flv)} |\n"
    )
    md.append(
        f"Flávio recuou em **{_br_int(flv_cai_sec.height)}** seções "
        f"(**{_br_int(int((-flv_cai_sec['delta_flavio']).sum()))}** votos). "
        "No agregado nacional, ainda assim cresceu.\n"
    )

    md.append("## Silva Jardim/RJ — o caso que circula\n")
    md.append(f"![Silva Jardim]({img_sj})\n")
    md.append(
        "| | 1º turno | 2º turno | Δ |\n"
        "| --- | ---: | ---: | ---: |\n"
        f"| Flávio | {_br_int(sj_row['flavio_t1'])} | {_br_int(sj_row['flavio_t2'])} | "
        f"{'+' if sj_row['delta_flavio'] >= 0 else ''}{_br_int(sj_row['delta_flavio'])} |\n"
        f"| Lula | {_br_int(sj_row['lula_t1'])} | {_br_int(sj_row['lula_t2'])} | "
        f"{'+' if sj_row['delta_lula'] >= 0 else ''}{_br_int(sj_row['delta_lula'])} |\n"
        f"| Reservatório municipal | | | {_br_int(sj_row['reservatorio_mun'])} |\n"
        f"| Seções Flávio ↑ / ↓ / = | | | "
        f"{_br_int(sj_row['sec_flavio_sobe'])} / {_br_int(sj_row['sec_flavio_cai'])} / "
        f"{_br_int(sj_row['sec_flavio_igual'])} |\n"
    )
    md.append(
        f"**Leitura rápida:** o +1 é saldo (+{_br_int(sj_row['votos_flavio_sobe_sec'] or 0)} "
        f"e −{_br_int(sj_row['votos_flavio_cai_sec'] or 0)} nas urnas). "
        "O salto de Lula cabe no reservatório. "
        f"Municípios BR com \\|Δ Flávio\\| ≤ 1: **{_br_int(flv_abs1_br.height)}** "
        f"(~1 em {_br_int(mun_br.height / flv_abs1_br.height if flv_abs1_br.height else 0)}) "
        "— não é Mega-Sena.\n"
    )
    md.append(f"![Distribuição municipal]({img_hist})\n")
    md.append(
        "| Recorte municipal | N | Δ Lula | Reservatório |\n"
        "| --- | ---: | ---: | ---: |\n"
        f"| \\|Δ Flávio\\| ≤ 1 (BR+ZZ) | {_br_int(flv_abs1.height)} | "
        f"+{_br_int(flv_abs1['delta_lula'].sum())} | {_br_int(flv_abs1['reservatorio_mun'].sum())} |\n"
        f"| Flávio caiu | {_br_int(flv_cai.height)} | "
        f"+{_br_int(flv_cai['delta_lula'].sum())} | {_br_int(flv_cai['reservatorio_mun'].sum())} |\n"
        f"| Flávio subiu | {_br_int(flv_sobe.height)} | "
        f"+{_br_int(flv_sobe['delta_lula'].sum())} | {_br_int(flv_sobe['reservatorio_mun'].sum())} |\n"
    )

    md.append("## Peso dos recortes na vantagem nacional\n")
    md.append(f"![Peso]({img_peso})\n")
    md.append(
        "| Recorte | Seções / municípios | Peso na margem |\n"
        "| --- | ---: | ---: |\n"
        f"| Conversão branco/nulo | {_br_int(meta['q4_conversao_bn'])} seções | {_br_pct(float(peso_bn), 2)} |\n"
        f"| Fora da curva (z) | {_br_int(meta['q1_discrepancia'])} seções | {_br_pct(float(peso_disc), 2)} |\n"
        f"| Municípios \\|Δ Flávio\\|≤1 (Δ Lula) | {_br_int(flv_abs1.height)} | {_br_pct(float(peso_abs1), 2)} |\n"
        f"| 100% urna grande | 67 seções | {_br_pct(float(peso_100), 2)} |\n"
        f"| Queda brusca | {_br_int(meta['q3_queda'])} seções | {_br_pct(float(peso_queda), 3)} |\n"
        f"| **Vantagem nacional** | | **{_br_int(margin)}** |\n"
    )

    md.append("## O que esta apuração vê × o que não vê\n")
    md.append(
        "| Testa | Resultado |\n"
        "| --- | --- |\n"
        f"| Voto sem origem (poço) | **{_br_int(meta.get('q1_excesso_poco', 0))}** casos |\n"
        f"| Conta aptos / comparecimento | sem quebra; {_br_int(meta['contabil'])} comparecimentos 100% em urna grande |\n"
        f"| Queda brusca | {_br_int(meta['q3_queda'])} seções |\n"
        f"| 100% urna grande | 67 seções |\n"
    )
    md.append(
        "| Não testa | Por quê |\n"
        "| --- | --- |\n"
        "| Troca A→B que preserva o total | Indistinguível de eleitor que mudou de lado |\n"
        "| BU ≠ CSV | Este repo não lê Boletim de Urna |\n"
        "| Software da urna se o BU bate | Fora do CSV público |\n"
        "| Identidade / cadastro fantasma estável | Outras bases |\n"
    )

    md.append("## Fluxo da cadeia × onde olhamos\n")
    md.append(
        "```mermaid\n"
        "flowchart LR\n"
        "  cadastro[Cadastro] --> urna[Urna]\n"
        "  urna --> bu[Boletim]\n"
        "  bu --> tx[Transmissao]\n"
        "  tx --> tot[Totalizacao]\n"
        "  tot --> csv[CSV_TSE]\n"
        "  csv --> dash[Este_dashboard]\n"
        "```\n"
    )

    md.append(
        "Próximo passo se a dúvida for além do CSV: conferir o **Boletim de Urna** das seções "
        "já listadas em `flags_100pct_grandes.csv` e `flags_queda_brusca.csv`.\n"
    )
    md.append(
        "Arquivos: [`resumo.md`](resumo.md) · [`municipios_variacao.csv`](municipios_variacao.csv) · "
        "`flags_*.csv`\n"
    )

    out = REPORTS / "dashboard.md"
    out.write_text("\n".join(md), encoding="utf-8")
    print(f"Wrote {out}")
    print(f"Figures in {FIGS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
