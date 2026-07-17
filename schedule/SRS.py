# schedule/SRS.py
"""
簡易間隔反復システム (Simple Spaced Repetition System)。

core/mastery.py の SM-2 (sm2_update) が「個々の問題(Scenario)」の
出題間隔を管理するのに対し、本モジュールは「概念(Concept)そのもの」を
次にいつ復習すべきかを管理する、より粗い粒度のスケジューラである。
schedule/interleaving.py の出題概念選定ロジックが、この
`next_review_date` を「復習期限が来ているか」の判定に利用する。

外部ライブラリ(PsychoPy/Streamlit/LLM SDK)には一切依存しない、
core/ と同じ「純粋ロジック」層として実装する。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from core.models import Concept

DATE_FORMAT = "%Y-%m-%d"

DEFAULT_BASE_INTERVAL_DAYS = 1.0
DEFAULT_GROWTH_FACTOR = 2.5
DEFAULT_CONFIDENCE_THRESHOLD = 4  # これ以上を「高確信」とみなす


def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.strptime(value, DATE_FORMAT).date()
    except ValueError:
        return None


def _format_date(d: date) -> str:
    return d.strftime(DATE_FORMAT)


def is_due(concept: Concept, today: Optional[date] = None) -> bool:
    """概念の復習期限が来ているか（未設定の場合は常に True = 未学習として扱う）。"""
    today = today or date.today()
    review_date = _parse_date(concept.next_review_date)
    if review_date is None:
        return True
    return review_date <= today


def update_concept_schedule(
    concept: Concept,
    is_correct: bool,
    confidence: int,
    *,
    base_interval_days: float = DEFAULT_BASE_INTERVAL_DAYS,
    growth_factor: float = DEFAULT_GROWTH_FACTOR,
    confidence_threshold: int = DEFAULT_CONFIDENCE_THRESHOLD,
    today: Optional[date] = None,
) -> Concept:
    """回答結果に応じて概念の `review_interval_days` / `next_review_date` を更新する。

    ロジック（要件通り）:
      - 正解 かつ 高確信(confidence >= confidence_threshold) の場合:
          間隔を拡大する。初回は base_interval_days(既定1日)、
          以降は前回間隔 x growth_factor(既定2.5倍)。
      - それ以外（不正解、または正解でも確信度が低い場合）:
          間隔を base_interval_days にリセットする（＝翌日また復習）。

    Concept を直接書き換えて返す（呼び出し側で core/item_bank.py 等の
    save() と合わせて永続化することを想定）。
    """
    today = today or date.today()
    high_confidence = confidence >= confidence_threshold

    if is_correct and high_confidence:
        if concept.review_interval_days <= 0:
            concept.review_interval_days = base_interval_days
        else:
            concept.review_interval_days = round(concept.review_interval_days * growth_factor, 2)
    else:
        concept.review_interval_days = base_interval_days

    concept.next_review_date = _format_date(today + timedelta(days=concept.review_interval_days))
    return concept


def days_until_due(concept: Concept, today: Optional[date] = None) -> Optional[int]:
    """復習期限まで残り何日か。期限切れ/未設定なら 0 以下・None を返す。"""
    today = today or date.today()
    review_date = _parse_date(concept.next_review_date)
    if review_date is None:
        return None
    return (review_date - today).days
