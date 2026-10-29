"""Download TSE 2026 presidential section-level results (T1+T2)."""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
RAW.mkdir(parents=True, exist_ok=True)

URLS = {
    "votacao_secao_2026_BR.zip": (
        "https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_secao/votacao_secao_2026_BR.zip"
    ),
    "detalhe_votacao_secao_2026.zip": (
        "https://cdn.tse.jus.br/estatistica/sead/odsele/detalhe_votacao_secao/detalhe_votacao_secao_2026.zip"
    ),
}

# Fallback: BU per UF for 2nd turn if national votacao_secao lacks NR_TURNO=2
BU_BASE = "https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes2026/buweb/bweb_2t_{uf}_261020261700.zip"
UFS = [
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS",
    "MT", "PA", "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC",
    "SE", "SP", "TO", "ZZ",
]


def download(url: str, dest: Path, force: bool = False) -> Path:
    if dest.exists() and not force and dest.stat().st_size > 0:
        print(f"  skip (exists): {dest.name} ({dest.stat().st_size:,} bytes)")
        return dest
    print(f"  downloading {url}")
    with requests.get(url, stream=True, timeout=600) as r:
        r.raise_for_status()
        tmp = dest.with_suffix(dest.suffix + ".part")
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=8 * 1024 * 1024):
                if chunk:
                    f.write(chunk)
        tmp.replace(dest)
    print(f"  saved {dest.name} ({dest.stat().st_size:,} bytes)")
    return dest


def zip_has_turno2(path: Path) -> bool:
    """Peek CSV headers/sample for NR_TURNO containing 2."""
    import csv
    import io

    with zipfile.ZipFile(path) as z:
        csvs = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if not csvs:
            return False
        # Prefer BR / largest
        csvs.sort(key=lambda n: (-len(n), n))
        name = next((n for n in csvs if "BR" in n.upper()), csvs[0])
        with z.open(name) as fh:
            text = io.TextIOWrapper(fh, encoding="latin-1", errors="replace")
            reader = csv.DictReader(text, delimiter=";")
            if not reader.fieldnames or "NR_TURNO" not in reader.fieldnames:
                # Some files may use different layout — check first 50k rows for ";2;"
                fh.seek(0)
                sample = fh.read(2_000_000).decode("latin-1", errors="replace")
                return "\n" in sample and any(
                    line.split(";")[0:5] and "2" in line.split(";")[:8]
                    for line in sample.splitlines()[1:200]
                )
            turnos = set()
            for i, row in enumerate(reader):
                turnos.add(row.get("NR_TURNO", "").strip())
                if i >= 200_000 or turnos >= {"1", "2"}:
                    break
            print(f"  turnos found in sample of {name}: {sorted(turnos)}")
            return "2" in turnos


def download_bu_fallback() -> None:
    bu_dir = RAW / "bu_2t"
    bu_dir.mkdir(parents=True, exist_ok=True)
    print("Fallback: downloading Boletim de Urna 2º turno por UF…")
    for uf in UFS:
        url = BU_BASE.format(uf=uf)
        dest = bu_dir / f"bweb_2t_{uf}.zip"
        try:
            download(url, dest)
        except requests.HTTPError as e:
            print(f"  WARN {uf}: {e}")


def main() -> int:
    print("=== 01_download ===")
    for name, url in URLS.items():
        download(url, RAW / name)

    votacao = RAW / "votacao_secao_2026_BR.zip"
    has_t2 = zip_has_turno2(votacao)
    marker = RAW / "needs_bu_fallback.txt"
    if has_t2:
        print("OK: votacao_secao contém NR_TURNO=2")
        if marker.exists():
            marker.unlink()
    else:
        print("WARN: votacao_secao sem 2º turno detectado — baixando BUs…")
        marker.write_text("1\n", encoding="utf-8")
        download_bu_fallback()
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
