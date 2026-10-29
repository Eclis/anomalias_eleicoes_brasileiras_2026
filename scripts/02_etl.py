"""ETL: votacao_secao + detalhe_votacao_secao → secao_turno.parquet."""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
PROCESSED.mkdir(parents=True, exist_ok=True)

# Official T2 totals for sanity (valid votes)
OFFICIAL_T2 = {
    "13": 64_256_232,  # Lula
    "22": 59_826_041,  # Flávio Bolsonaro
}

KEY = ["SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO"]

VOTACAO_COLS = [
    "NR_TURNO", "SG_UF", "CD_MUNICIPIO", "NM_MUNICIPIO", "NR_ZONA", "NR_SECAO",
    "CD_CARGO", "NR_VOTAVEL", "NM_VOTAVEL", "QT_VOTOS",
]

DETALHE_COLS = [
    "NR_TURNO", "SG_UF", "CD_MUNICIPIO", "NM_MUNICIPIO", "NR_ZONA", "NR_SECAO",
    "CD_CARGO", "QT_APTOS", "QT_COMPARECIMENTO", "QT_ABSTENCOES",
    "QT_VOTOS_NOMINAIS", "QT_VOTOS_BRANCOS", "QT_VOTOS_NULOS",
]


def _read_zip_csvs(path: Path, usecols: list[str], cargo: str = "1") -> pl.DataFrame:
    parts: list[pl.DataFrame] = []
    with zipfile.ZipFile(path) as z:
        csvs = sorted(n for n in z.namelist() if n.lower().endswith(".csv"))
        # Prefer consolidated BR CSV when present (UF files in detalhe often
        # filter cargo differently / empty for presidente-only reads).
        br = [n for n in csvs if n.upper().endswith("_BR.CSV") or "BRASIL" in n.upper()]
        alvos = br if br else csvs
        if path.name.endswith("_BR.zip"):
            alvos = csvs
        print(f"  reading {len(alvos)} CSV(s) from {path.name}")
        for name in alvos:
            with z.open(name) as fh:
                raw = fh.read()
            # Detect available columns
            header = pl.read_csv(
                io.BytesIO(raw), separator=";", encoding="latin1",
                n_rows=0, infer_schema_length=0,
            ).columns
            cols = [c for c in usecols if c in header]
            missing = [c for c in usecols if c not in header]
            if missing:
                # optional detalhe cols
                optional = {"QT_VOTOS_NOMINAIS", "QT_VOTOS_BRANCOS", "QT_VOTOS_NULOS", "NM_MUNICIPIO"}
                critical = [c for c in missing if c not in optional]
                if critical:
                    print(f"  ! {name}: missing {critical}, skip")
                    continue
            df = pl.read_csv(
                io.BytesIO(raw),
                separator=";",
                encoding="latin1",
                columns=cols,
                infer_schema_length=10_000,
                ignore_errors=True,
            )
            if "CD_CARGO" in df.columns:
                df = df.filter(pl.col("CD_CARGO").cast(pl.Utf8).str.strip_chars() == cargo)
            parts.append(df)
            print(f"    ok {name}: {df.height:,} rows (cargo={cargo})")
    if not parts:
        raise SystemExit(f"No rows from {path}")
    out = pl.concat(parts, how="diagonal_relaxed")
    return out


def _normalize_ids(df: pl.DataFrame) -> pl.DataFrame:
    exprs = []
    for c in KEY + ["NR_TURNO", "CD_CARGO"]:
        if c in df.columns:
            exprs.append(pl.col(c).cast(pl.Utf8).str.strip_chars().alias(c))
    if "NR_VOTAVEL" in df.columns:
        exprs.append(pl.col("NR_VOTAVEL").cast(pl.Utf8).str.strip_chars().alias("NR_VOTAVEL"))
    if "QT_VOTOS" in df.columns:
        exprs.append(pl.col("QT_VOTOS").cast(pl.Int64, strict=False).fill_null(0).alias("QT_VOTOS"))
    for c in ["QT_APTOS", "QT_COMPARECIMENTO", "QT_ABSTENCOES",
              "QT_VOTOS_NOMINAIS", "QT_VOTOS_BRANCOS", "QT_VOTOS_NULOS"]:
        if c in df.columns:
            exprs.append(pl.col(c).cast(pl.Int64, strict=False).fill_null(0).alias(c))
    if "NM_MUNICIPIO" in df.columns:
        exprs.append(pl.col("NM_MUNICIPIO").cast(pl.Utf8).alias("NM_MUNICIPIO"))
    if "NM_VOTAVEL" in df.columns:
        exprs.append(pl.col("NM_VOTAVEL").cast(pl.Utf8).alias("NM_VOTAVEL"))
    return df.with_columns(exprs)


def pivot_votacao(vot: pl.DataFrame) -> pl.DataFrame:
    """One row per section×turno with candidate columns."""
    vot = _normalize_ids(vot)
    # Map votável codes
    # 13 Lula, 22 Flávio; 95 branco, 96 nulo (confirm via NM_VOTAVEL if needed)
    blanco_codes = {"95", "96"}
    # Aggregate by section×turno×votavel
    agg = (
        vot.group_by(KEY + ["NR_TURNO", "NR_VOTAVEL"])
        .agg(
            pl.col("QT_VOTOS").sum().alias("QT_VOTOS"),
            pl.col("NM_VOTAVEL").first().alias("NM_VOTAVEL"),
            pl.col("NM_MUNICIPIO").first().alias("NM_MUNICIPIO") if "NM_MUNICIPIO" in vot.columns else pl.lit(None),
        )
    )

    # Classify
    def classify(code: str, name: str | None) -> str:
        c = (code or "").lstrip("0") or "0"
        if code in ("13", "013") or c == "13":
            return "lula"
        if code in ("22", "022") or c == "22":
            return "flavio"
        if code in blanco_codes or c in blanco_codes:
            n = (name or "").upper()
            if "BRANCO" in n or code == "95" or c == "95":
                return "brancos"
            if "NULO" in n or code == "96" or c == "96":
                return "nulos"
            return "brancos" if code == "95" else "nulos"
        n = (name or "").upper()
        if "BRANCO" in n:
            return "brancos"
        if "NULO" in n:
            return "nulos"
        return "outros"

    # Use polars when_then for classification
    agg = agg.with_columns(
        pl.when(pl.col("NR_VOTAVEL").is_in(["13", "013"]))
        .then(pl.lit("lula"))
        .when(pl.col("NR_VOTAVEL").is_in(["22", "022"]))
        .then(pl.lit("flavio"))
        .when(
            pl.col("NR_VOTAVEL").is_in(["95"])
            | pl.col("NM_VOTAVEL").str.to_uppercase().str.contains("BRANCO")
        )
        .then(pl.lit("brancos"))
        .when(
            pl.col("NR_VOTAVEL").is_in(["96"])
            | pl.col("NM_VOTAVEL").str.to_uppercase().str.contains("NULO")
        )
        .then(pl.lit("nulos"))
        .otherwise(pl.lit("outros"))
        .alias("candidato")
    )

    wide = (
        agg.group_by(KEY + ["NR_TURNO", "candidato"])
        .agg(
            pl.col("QT_VOTOS").sum().alias("votos"),
            pl.col("NM_MUNICIPIO").first().alias("NM_MUNICIPIO"),
        )
        .pivot(values="votos", index=KEY + ["NR_TURNO", "NM_MUNICIPIO"], on="candidato", aggregate_function="sum")
        .fill_null(0)
    )
    for col in ["lula", "flavio", "brancos", "nulos", "outros"]:
        if col not in wide.columns:
            wide = wide.with_columns(pl.lit(0).alias(col))
    wide = wide.with_columns(
        (pl.col("lula") + pl.col("flavio") + pl.col("outros")).alias("validos"),
        (pl.col("lula") + pl.col("flavio") + pl.col("outros") + pl.col("brancos") + pl.col("nulos")).alias("nominais_bn"),
    )
    return wide


def load_detalhe(path: Path) -> pl.DataFrame:
    det = _read_zip_csvs(path, DETALHE_COLS, cargo="1")
    det = _normalize_ids(det)
    # One row per section×turno
    det = (
        det.group_by(KEY + ["NR_TURNO"])
        .agg(
            pl.col("NM_MUNICIPIO").first().alias("NM_MUNICIPIO") if "NM_MUNICIPIO" in det.columns else pl.lit(None),
            pl.col("QT_APTOS").max().alias("aptos"),
            pl.col("QT_COMPARECIMENTO").max().alias("comparecimento"),
            pl.col("QT_ABSTENCOES").max().alias("abstencoes"),
            pl.col("QT_VOTOS_BRANCOS").max().alias("brancos_det") if "QT_VOTOS_BRANCOS" in det.columns else pl.lit(0),
            pl.col("QT_VOTOS_NULOS").max().alias("nulos_det") if "QT_VOTOS_NULOS" in det.columns else pl.lit(0),
            pl.col("QT_VOTOS_NOMINAIS").max().alias("nominais_det") if "QT_VOTOS_NOMINAIS" in det.columns else pl.lit(0),
        )
    )
    return det


def main() -> int:
    print("=== 02_etl ===")
    vot_zip = RAW / "votacao_secao_2026_BR.zip"
    det_zip = RAW / "detalhe_votacao_secao_2026.zip"
    if not vot_zip.exists() or not det_zip.exists():
        raise SystemExit("Missing ZIPs — run 01_download.py first")

    print("Loading votacao_secao…")
    vot = _read_zip_csvs(vot_zip, VOTACAO_COLS, cargo="1")
    vot = _normalize_ids(vot)
    turnos = vot["NR_TURNO"].unique().to_list()
    print(f"  turnos: {sorted(turnos)}")
    print(f"  rows: {vot.height:,}")

    if "2" not in turnos:
        print("ERROR: 2º turno absent from votacao_secao — implement BU merge or re-download")
        raise SystemExit(2)

    print("Pivoting candidates…")
    wide = pivot_votacao(vot)
    print(f"  section×turno rows: {wide.height:,}")

    print("Loading detalhe_votacao_secao…")
    det = load_detalhe(det_zip)
    print(f"  detalhe rows: {det.height:,}")

    # Join
    joined = wide.join(
        det.select(KEY + ["NR_TURNO", "aptos", "comparecimento", "abstencoes",
                         "brancos_det", "nulos_det", "nominais_det"]),
        on=KEY + ["NR_TURNO"],
        how="left",
    )
    # Prefer detalhe brancos/nulos when present
    joined = joined.with_columns(
        pl.when(pl.col("brancos_det").fill_null(0) > 0)
        .then(pl.col("brancos_det"))
        .otherwise(pl.col("brancos"))
        .alias("brancos"),
        pl.when(pl.col("nulos_det").fill_null(0) > 0)
        .then(pl.col("nulos_det"))
        .otherwise(pl.col("nulos"))
        .alias("nulos"),
        pl.col("aptos").fill_null(0),
        pl.col("comparecimento").fill_null(0),
        pl.col("abstencoes").fill_null(0),
    ).drop(["brancos_det", "nulos_det", "nominais_det"], strict=False)

    joined = joined.with_columns(
        (pl.col("lula") + pl.col("flavio") + pl.col("outros")).alias("validos"),
        pl.when(pl.col("aptos") < 50).then(pl.lit("<50"))
        .when(pl.col("aptos") < 150).then(pl.lit("50-149"))
        .when(pl.col("aptos") < 300).then(pl.lit("150-299"))
        .otherwise(pl.lit("300+"))
        .alias("faixa_aptos"),
    )

    out = PROCESSED / "secao_turno.parquet"
    joined.write_parquet(out)
    print(f"Wrote {out} ({joined.height:,} rows)")

    # Sanity vs official T2
    t2 = joined.filter(pl.col("NR_TURNO") == "2")
    s_lula = t2["lula"].sum()
    s_flavio = t2["flavio"].sum()
    print(f"Sanity T2 Lula:   {s_lula:,}  (official {OFFICIAL_T2['13']:,})  diff={s_lula - OFFICIAL_T2['13']:,}")
    print(f"Sanity T2 Flavio: {s_flavio:,}  (official {OFFICIAL_T2['22']:,})  diff={s_flavio - OFFICIAL_T2['22']:,}")
    t1 = joined.filter(pl.col("NR_TURNO") == "1")
    print(f"Secoes T1={t1.height:,}  T2={t2.height:,}")
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
