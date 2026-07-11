"""Raw parquet cache: one file per (dataset, date), written before any transformation.

Caching at daily granularity is what makes ingestion incremental — a re-run only
needs to ask gridstatus for the dates that don't already have a raw file on disk.
"""

import datetime as dt
from pathlib import Path

import polars as pl

DEFAULT_RAW_ROOT = Path("data/raw")


class RawCache:
    def __init__(self, root: Path = DEFAULT_RAW_ROOT) -> None:
        self.root = root

    def _dataset_dir(self, dataset: str) -> Path:
        path = self.root / dataset
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _file_for_date(self, dataset: str, date: dt.date) -> Path:
        return self._dataset_dir(dataset) / f"{date.isoformat()}.parquet"

    def has_date(self, dataset: str, date: dt.date) -> bool:
        return self._file_for_date(dataset, date).exists()

    def missing_dates(self, dataset: str, start: dt.date, end: dt.date) -> list[dt.date]:
        """Inclusive [start, end] range of dates not yet cached for this dataset."""
        all_dates = [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]
        return [d for d in all_dates if not self.has_date(dataset, d)]

    def write(self, dataset: str, date: dt.date, df: pl.DataFrame) -> Path:
        path = self._file_for_date(dataset, date)
        df.write_parquet(path)
        return path

    def read_range(self, dataset: str, start: dt.date, end: dt.date) -> pl.DataFrame:
        files = [
            self._file_for_date(dataset, start + dt.timedelta(days=i))
            for i in range((end - start).days + 1)
        ]
        existing = [f for f in files if f.exists()]
        if not existing:
            return pl.DataFrame()
        return pl.concat([pl.read_parquet(f) for f in existing], how="vertical_relaxed")
