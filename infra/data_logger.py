# infra/data_logger.py
"""
被験者ごとの試行ログを CSV に追記する。
説明可能性・トレーサビリティのため、prompt_version や正誤・確信度・mastery遷移などを
すべて1行(1トライアル)として記録する。
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import List

from core.models import TrialRecord

FIELDNAMES: List[str] = list(TrialRecord.model_fields.keys())


class DataLogger:
    def __init__(self, user_id: str, logs_dir: str | Path = "data/logs"):
        self.user_id = user_id
        self.logs_dir = Path(logs_dir)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.logs_dir / f"{user_id}.csv"

    def append(self, record: TrialRecord) -> None:
        file_exists = self.log_path.exists()
        with self.log_path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            if not file_exists:
                writer.writeheader()
            writer.writerow(record.model_dump(mode="json"))
