"""Parear seções T1 ∩ T2 e reportar não pareadas / mudança de aptos."""
from __future__ import annotations

import sys
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
REPORTS = ROOT / "reports"
REPORTS.mkdir(parents=True, exist_ok=True)

KEY = ["SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO"]


def main() -> int:
    print("=== 03_parear ===")
    src = PROCESSED / "secao_turno.parquet"
    if not src.exists():
        raise SystemExit("Run 02_etl.py first")

    df = pl.read_parquet(src)
    t1 = df.filter(pl.col("NR_TURNO") == "1").rename(
        {c: f"{c}_t1" for c in df.columns if c not in KEY}
    )
    t2 = df.filter(pl.col("NR_TURNO") == "2").rename(
        {c: f"{c}_t2" for c in df.columns if c not in KEY}
    )

    only_t1 = t1.join(t2.select(KEY), on=KEY, how="anti")
    only_t2 = t2.join(t1.select(KEY), on=KEY, how="anti")
    paired = t1.join(t2, on=KEY, how="inner")

    print(f"T1 seções: {t1.height:,}")
    print(f"T2 seções: {t2.height:,}")
    print(f"Pareadas:  {paired.height:,}")
    print(f"Só T1:     {only_t1.height:,}")
    print(f"Só T2:     {only_t2.height:,}")

    # Deltas
    paired = paired.with_columns(
        (pl.col("lula_t2") - pl.col("lula_t1")).alias("delta_lula"),
        (pl.col("flavio_t2") - pl.col("flavio_t1")).alias("delta_flavio"),
        (pl.col("outros_t2") - pl.col("outros_t1")).alias("delta_outros"),
        (pl.col("brancos_t2") - pl.col("brancos_t1")).alias("delta_brancos"),
        (pl.col("nulos_t2") - pl.col("nulos_t1")).alias("delta_nulos"),
        (pl.col("abstencoes_t2") - pl.col("abstencoes_t1")).alias("delta_abstencoes"),
        (pl.col("comparecimento_t2") - pl.col("comparecimento_t1")).alias("delta_comparecimento"),
        (pl.col("aptos_t2") - pl.col("aptos_t1")).alias("delta_aptos"),
        (pl.col("validos_t2") - pl.col("validos_t1")).alias("delta_validos"),
        pl.when(pl.col("validos_t1") > 0)
        .then(pl.col("lula_t1") / pl.col("validos_t1"))
        .otherwise(None)
        .alias("pct_lula_t1"),
        pl.when(pl.col("validos_t2") > 0)
        .then(pl.col("lula_t2") / pl.col("validos_t2"))
        .otherwise(None)
        .alias("pct_lula_t2"),
        pl.when(pl.col("validos_t1") > 0)
        .then(pl.col("flavio_t1") / pl.col("validos_t1"))
        .otherwise(None)
        .alias("pct_flavio_t1"),
        pl.when(pl.col("validos_t2") > 0)
        .then(pl.col("flavio_t2") / pl.col("validos_t2"))
        .otherwise(None)
        .alias("pct_flavio_t2"),
        # Prefer T2 faixa; fallback T1
        pl.coalesce([pl.col("faixa_aptos_t2"), pl.col("faixa_aptos_t1")]).alias("faixa_aptos"),
        pl.coalesce([pl.col("NM_MUNICIPIO_t2"), pl.col("NM_MUNICIPIO_t1")]).alias("NM_MUNICIPIO"),
        # Pool available for a candidate's gain beyond "natural" sources
        # eliminados (outros_t1) + max(0, Δcomparecimento) + max(0, -Δadversário) + max(0, -Δbrancos-nulos)
        pl.col("outros_t1").alias("poco_eliminados"),
    )
    paired = paired.with_columns(
        (pl.col("pct_lula_t2") - pl.col("pct_lula_t1")).alias("delta_pct_lula"),
        (pl.col("pct_flavio_t2") - pl.col("pct_flavio_t1")).alias("delta_pct_flavio"),
        (
            pl.col("poco_eliminados")
            + pl.max_horizontal(pl.col("delta_comparecimento"), pl.lit(0))
            + pl.max_horizontal(-pl.col("delta_brancos") - pl.col("delta_nulos"), pl.lit(0))
        ).alias("poco_base"),
    )
    # Excess gain beyond pool + opponent loss
    paired = paired.with_columns(
        (
            pl.col("delta_lula")
            - pl.col("poco_base")
            - pl.max_horizontal(-pl.col("delta_flavio"), pl.lit(0))
        ).alias("excesso_lula"),
        (
            pl.col("delta_flavio")
            - pl.col("poco_base")
            - pl.max_horizontal(-pl.col("delta_lula"), pl.lit(0))
        ).alias("excesso_flavio"),
    )

    out = PROCESSED / "painel_t1_t2.parquet"
    paired.write_parquet(out)
    print(f"Wrote {out}")

    only_t1.select(KEY + [c for c in only_t1.columns if c.endswith("_t1")][:8]).write_csv(
        REPORTS / "secoes_so_t1.csv"
    )
    only_t2.select(KEY + [c for c in only_t2.columns if c.endswith("_t2")][:8]).write_csv(
        REPORTS / "secoes_so_t2.csv"
    )

    # Aptos shift report
    big_aptos = paired.filter(pl.col("delta_aptos").abs() >= 20).sort(
        pl.col("delta_aptos").abs(), descending=True
    )
    big_aptos.head(500).write_csv(REPORTS / "mudanca_aptos.csv")
    print(f"Seções com |Δaptos|≥20: {big_aptos.height:,}")

    summary = {
        "pareadas": paired.height,
        "so_t1": only_t1.height,
        "so_t2": only_t2.height,
        "mudanca_aptos_ge20": big_aptos.height,
        "mediana_delta_abstencoes": paired["delta_abstencoes"].median(),
        "mediana_delta_nulos": paired["delta_nulos"].median(),
        "mediana_delta_brancos": paired["delta_brancos"].median(),
        "pct_queda_abstencoes": (paired["delta_abstencoes"] < 0).mean() * 100,
        "pct_queda_nulos": (paired["delta_nulos"] < 0).mean() * 100,
        "pct_queda_brancos": (paired["delta_brancos"] < 0).mean() * 100,
    }
    (REPORTS / "pareamento_summary.json").write_text(
        __import__("json").dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(summary)
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
