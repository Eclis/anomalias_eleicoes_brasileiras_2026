"""Detectores de anomalias T1→T2 para presidente 2026."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
REPORTS = ROOT / "reports"
REPORTS.mkdir(parents=True, exist_ok=True)

KEY = ["SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO"]


def mad_z(df: pl.DataFrame, value_col: str, group_cols: list[str], out_col: str) -> pl.DataFrame:
    """Robust z-score = 0.6745 * (x - median) / MAD within groups."""
    stats = df.group_by(group_cols).agg(
        pl.col(value_col).median().alias("_med"),
        (pl.col(value_col) - pl.col(value_col).median()).abs().median().alias("_mad"),
    )
    out = df.join(stats, on=group_cols, how="left")
    out = out.with_columns(
        pl.when(pl.col("_mad") > 0)
        .then(0.6745 * (pl.col(value_col) - pl.col("_med")) / pl.col("_mad"))
        .otherwise(0.0)
        .alias(out_col)
    ).drop(["_med", "_mad"])
    return out


def detector_discrepancia(p: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Q1: alteração discrepante T1→T2 (z-MAD; estrito = z + excesso sobre poço)."""
    p = mad_z(p, "delta_pct_lula", ["SG_UF", "faixa_aptos"], "z_delta_pct_lula")
    p = mad_z(p, "delta_pct_flavio", ["SG_UF", "faixa_aptos"], "z_delta_pct_flavio")
    p = mad_z(p, "delta_lula", ["SG_UF", "faixa_aptos"], "z_delta_lula")
    p = mad_z(p, "delta_flavio", ["SG_UF", "faixa_aptos"], "z_delta_flavio")

    p = p.with_columns(
        pl.max_horizontal(
            pl.col("z_delta_pct_lula").abs(),
            pl.col("z_delta_pct_flavio").abs(),
            pl.col("z_delta_lula").abs(),
            pl.col("z_delta_flavio").abs(),
        ).alias("z_max")
    )
    # Ranking: outliers estatísticos (|z|>4) em urnas com aptos>=50
    z_flags = p.filter(
        (pl.col("z_max") > 4) & (pl.col("aptos_t2") >= 50)
    ).with_columns(pl.lit("discrepancia_z").alias("detector"))
    # Estrito: também excede o poço disponível
    strict = z_flags.filter(
        (pl.col("excesso_lula") > 5) | (pl.col("excesso_flavio") > 5)
    ).with_columns(pl.lit("discrepancia_excesso_poco").alias("detector"))
    return z_flags, strict


def detector_100pct(p: pl.DataFrame, secao_turno: pl.DataFrame) -> pl.DataFrame:
    """Q2: seções 100% / ≥95% para 1 candidato."""
    st = secao_turno.with_columns(
        pl.when(pl.col("validos") > 0)
        .then(pl.col("lula") / pl.col("validos"))
        .otherwise(None)
        .alias("pct_lula"),
        pl.when(pl.col("validos") > 0)
        .then(pl.col("flavio") / pl.col("validos"))
        .otherwise(None)
        .alias("pct_flavio"),
    )
    rows = []
    for turno in ("1", "2"):
        t = st.filter(pl.col("NR_TURNO") == turno)
        for thr, label in [(1.0, "100pct"), (0.95, "ge95pct")]:
            for cand, col in [("lula", "pct_lula"), ("flavio", "pct_flavio")]:
                f = t.filter(
                    (pl.col(col) >= thr) & (pl.col("validos") > 0) & (pl.col("aptos") >= 1)
                ).with_columns(
                    pl.lit(f"{label}_{cand}_t{turno}").alias("detector"),
                    pl.col(col).alias("pct_candidato"),
                    pl.lit(cand).alias("candidato"),
                    pl.lit(turno).alias("turno"),
                )
                rows.append(f)
            # zero votes for a finalist in large sections
            if cand == "lula":
                zero = t.filter(
                    (pl.col("lula") == 0) & (pl.col("validos") >= 50) & (pl.col("aptos") >= 150)
                ).with_columns(
                    pl.lit(f"zero_lula_t{turno}").alias("detector"),
                    pl.lit(0.0).alias("pct_candidato"),
                    pl.lit("lula").alias("candidato"),
                    pl.lit(turno).alias("turno"),
                )
                rows.append(zero)
                zero_f = t.filter(
                    (pl.col("flavio") == 0) & (pl.col("validos") >= 50) & (pl.col("aptos") >= 150)
                ).with_columns(
                    pl.lit(f"zero_flavio_t{turno}").alias("detector"),
                    pl.lit(0.0).alias("pct_candidato"),
                    pl.lit("flavio").alias("candidato"),
                    pl.lit(turno).alias("turno"),
                )
                rows.append(zero_f)
    return pl.concat(rows, how="diagonal_relaxed")


def detector_queda_brusca(p: pl.DataFrame) -> pl.DataFrame:
    """Q3: queda brusca de finalista no T2 com comparecimento estável/maior."""
    flags = []
    for cand, dcol, vcol in [
        ("lula", "delta_lula", "lula_t1"),
        ("flavio", "delta_flavio", "flavio_t1"),
    ]:
        f = p.filter(
            (pl.col(dcol) < 0)
            & (pl.col(dcol).abs() >= 20)
            & (pl.col(dcol).abs() >= 0.15 * pl.col(vcol))
            & (pl.col("delta_comparecimento") >= 0)
            & (pl.col(vcol) >= 30)
        ).with_columns(
            pl.lit(f"queda_brusca_{cand}").alias("detector"),
            pl.lit(cand).alias("candidato"),
        )
        flags.append(f)
    # Rare: drop of A AND excess gain of B
    rare = p.filter(
        (
            ((pl.col("delta_lula") < -20) & (pl.col("excesso_flavio") > 5))
            | ((pl.col("delta_flavio") < -20) & (pl.col("excesso_lula") > 5))
        )
        & (pl.col("aptos_t2") >= 100)
    ).with_columns(pl.lit("queda_e_excesso_adversario").alias("detector"))
    flags.append(rare)
    return pl.concat(flags, how="diagonal_relaxed")


def detector_abst_nulos(p: pl.DataFrame) -> tuple[dict, pl.DataFrame]:
    """Q4: abstenções/nulos diminuíram? + conversão unilateral."""
    stats = {
        "n_secoes": p.height,
        "mediana_delta_abstencoes": p["delta_abstencoes"].median(),
        "p5_delta_abstencoes": p["delta_abstencoes"].quantile(0.05),
        "p95_delta_abstencoes": p["delta_abstencoes"].quantile(0.95),
        "pct_secoes_queda_abstencoes": float((p["delta_abstencoes"] < 0).mean() * 100),
        "mediana_delta_nulos": p["delta_nulos"].median(),
        "p5_delta_nulos": p["delta_nulos"].quantile(0.05),
        "p95_delta_nulos": p["delta_nulos"].quantile(0.95),
        "pct_secoes_queda_nulos": float((p["delta_nulos"] < 0).mean() * 100),
        "mediana_delta_brancos": p["delta_brancos"].median(),
        "pct_secoes_queda_brancos": float((p["delta_brancos"] < 0).mean() * 100),
        "soma_delta_abstencoes": int(p["delta_abstencoes"].sum()),
        "soma_delta_nulos": int(p["delta_nulos"].sum()),
        "soma_delta_brancos": int(p["delta_brancos"].sum()),
    }
    # Unilateral conversion: big drop in blank+null, almost all goes to one candidate, opponent stable
    queda_bn = (-pl.col("delta_brancos") - pl.col("delta_nulos")).alias("queda_bn")
    p2 = p.with_columns(queda_bn)
    flags = p2.filter(
        (pl.col("queda_bn") >= 15)
        & (
            (
                (pl.col("delta_lula") >= 0.8 * pl.col("queda_bn"))
                & (pl.col("delta_flavio").abs() <= 5)
            )
            | (
                (pl.col("delta_flavio") >= 0.8 * pl.col("queda_bn"))
                & (pl.col("delta_lula").abs() <= 5)
            )
        )
        & (pl.col("aptos_t2") >= 100)
    ).with_columns(pl.lit("conversao_unilateral_bn").alias("detector"))
    return stats, flags


def detector_contabil(secao_turno: pl.DataFrame) -> pl.DataFrame:
    """Identidades contábeis e comparecimento 100%."""
    st = secao_turno.with_columns(
        (pl.col("comparecimento") + pl.col("abstencoes") - pl.col("aptos")).alias("err_aptos"),
        (
            pl.col("lula") + pl.col("flavio") + pl.col("outros") + pl.col("brancos") + pl.col("nulos")
            - pl.col("comparecimento")
        ).alias("err_comparecimento"),
    )
    viol = st.filter(
        (pl.col("err_aptos").abs() > 0) | (pl.col("err_comparecimento").abs() > 1)
        | ((pl.col("lula") + pl.col("flavio") + pl.col("outros") + pl.col("brancos") + pl.col("nulos")) > pl.col("aptos") + 1)
    ).with_columns(pl.lit("violacao_contabil").alias("detector"))

    full = st.filter(
        (pl.col("aptos") >= 150)
        & (pl.col("comparecimento") == pl.col("aptos"))
        & (pl.col("aptos") > 0)
    ).with_columns(pl.lit("comparecimento_100pct").alias("detector"))
    return pl.concat([viol, full], how="diagonal_relaxed")


def clusters(flags_paired: pl.DataFrame) -> pl.DataFrame:
    """Concentração de flags por município/zona."""
    if flags_paired.height == 0:
        return pl.DataFrame()
    by_mun = (
        flags_paired.group_by(["SG_UF", "CD_MUNICIPIO", "NM_MUNICIPIO"])
        .agg(pl.len().alias("n_flags"), pl.col("NR_SECAO").n_unique().alias("n_secoes"))
        .filter(pl.col("n_secoes") >= 3)
        .sort("n_secoes", descending=True)
    )
    by_zona = (
        flags_paired.group_by(["SG_UF", "CD_MUNICIPIO", "NM_MUNICIPIO", "NR_ZONA"])
        .agg(pl.len().alias("n_flags"), pl.col("NR_SECAO").n_unique().alias("n_secoes"))
        .filter(pl.col("n_secoes") >= 3)
        .sort("n_secoes", descending=True)
    )
    by_mun.write_csv(REPORTS / "clusters_municipio.csv")
    by_zona.write_csv(REPORTS / "clusters_zona.csv")
    return by_mun


def main() -> int:
    print("=== 04_anomalias ===")
    painel = pl.read_parquet(PROCESSED / "painel_t1_t2.parquet")
    secao = pl.read_parquet(PROCESSED / "secao_turno.parquet")

    # Enrich z-scores on full painel for reporting
    painel = mad_z(painel, "delta_pct_lula", ["SG_UF", "faixa_aptos"], "z_delta_pct_lula")
    painel = mad_z(painel, "delta_pct_flavio", ["SG_UF", "faixa_aptos"], "z_delta_pct_flavio")
    painel = mad_z(painel, "delta_lula", ["SG_UF", "faixa_aptos"], "z_delta_lula")
    painel = mad_z(painel, "delta_flavio", ["SG_UF", "faixa_aptos"], "z_delta_flavio")
    painel.write_parquet(PROCESSED / "painel_t1_t2.parquet")

    f1_z, f1_strict = detector_discrepancia(painel)
    f1_export_cols = KEY + [
        "NM_MUNICIPIO", "faixa_aptos", "aptos_t1", "aptos_t2",
        "lula_t1", "lula_t2", "flavio_t1", "flavio_t2", "outros_t1",
        "delta_lula", "delta_flavio", "delta_pct_lula", "delta_pct_flavio",
        "z_delta_pct_lula", "z_delta_pct_flavio", "z_max",
        "excesso_lula", "excesso_flavio", "poco_base", "detector",
    ]
    f1_z.select([c for c in f1_export_cols if c in f1_z.columns]).sort(
        "z_max", descending=True,
    ).write_csv(REPORTS / "flags_discrepancia.csv")
    f1_strict.select([c for c in f1_export_cols if c in f1_strict.columns]).sort(
        "z_max", descending=True,
    ).write_csv(REPORTS / "flags_discrepancia_excesso_poco.csv")
    print(f"Q1 discrepancia |z|>4: {f1_z.height:,}; excesso_poco: {f1_strict.height:,}")

    f2 = detector_100pct(painel, secao)
    f2_cols = [c for c in KEY + ["NM_MUNICIPIO", "NR_TURNO", "aptos", "validos", "lula", "flavio",
                                  "pct_candidato", "candidato", "turno", "detector", "faixa_aptos"] if c in f2.columns]
    f2.select(f2_cols).sort("aptos", descending=True).write_csv(REPORTS / "flags_100pct.csv")
    # Focus large sections 100%
    f2_big = f2.filter(
        pl.col("detector").str.starts_with("100pct") & (pl.col("aptos") >= 150)
    )
    f2_big.write_csv(REPORTS / "flags_100pct_grandes.csv")
    print(f"Q2 100% / ≥95% / zero: {f2.height:,} (100% aptos≥150: {f2_big.height:,})")

    f3 = detector_queda_brusca(painel)
    f3.select([c for c in f1_export_cols + ["candidato"] if c in f3.columns]).sort(
        "delta_lula" if "delta_lula" in f3.columns else KEY[0]
    ).write_csv(REPORTS / "flags_queda_brusca.csv")
    print(f"Q3 queda brusca: {f3.height:,}")

    stats_q4, f4 = detector_abst_nulos(painel)
    (REPORTS / "stats_abstencoes_nulos.json").write_text(
        json.dumps(stats_q4, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    f4.select([c for c in f1_export_cols + ["queda_bn"] if c in f4.columns]).write_csv(
        REPORTS / "flags_conversao_bn.csv"
    )
    print(f"Q4 stats: {stats_q4}")
    print(f"Q4 conversão unilateral BN: {f4.height:,}")

    f5 = detector_contabil(secao)
    f5.write_csv(REPORTS / "flags_contabil.csv")
    print(f"Extra contábil/comparecimento100: {f5.height:,}")

    # Combined paired flags for clusters (strict Q1 + Q3 + unilateral BN)
    cluster_parts = []
    for part in (f1_strict, f1_z.head(500), f3, f4):
        cols = [c for c in KEY + ["NM_MUNICIPIO", "detector"] if c in part.columns]
        if part.height and cols:
            cluster_parts.append(part.select(cols))
    paired_flags = pl.concat(cluster_parts, how="diagonal_relaxed") if cluster_parts else pl.DataFrame()
    cl = clusters(paired_flags) if paired_flags.height else pl.DataFrame()
    print(f"Clusters municipio (>=3 secoes): {cl.height if cl.height else 0}")

    # Per-UF summary of flags
    if paired_flags.height:
        uf_summary = (
            paired_flags.group_by("SG_UF")
            .agg(pl.len().alias("n_flags"))
            .sort("n_flags", descending=True)
        )
        uf_summary.write_csv(REPORTS / "flags_por_uf.csv")

    meta = {
        "n_pareadas": painel.height,
        "q1_discrepancia": f1_z.height,
        "q1_excesso_poco": f1_strict.height,
        "q2_total": f2.height,
        "q2_100pct_grandes": f2_big.height,
        "q3_queda": f3.height,
        "q4_conversao_bn": f4.height,
        "contabil": f5.height,
        "clusters_mun": cl.height if isinstance(cl, pl.DataFrame) else 0,
        "abst_nulos": stats_q4,
    }
    (REPORTS / "anomalias_meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
