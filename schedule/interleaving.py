# schedule/interleaving.py
"""
インターリービング（交互学習）による出題概念の選定ロジック。

認知科学の知見では、同じ概念を連続して学習し続ける「ブロック学習」よりも、
異なる概念を織り交ぜる「インターリービング」の方が長期定着に優れるとされる。
本モジュールは、設定された確率で「習熟済みの概念」をあえて混ぜ込みつつ、
基本的には「弱点(blind_spots)」または「低習熟度」の概念を優先して選ぶ。

core/ と同じく、外部ライブラリ(PsychoPy/Streamlit/LLM SDK)に依存しない
純粋ロジック層。乱数は呼び出し側から `random.Random` を注入できるように
しておき、テストや再現性のある挙動を確保できるようにしている。
"""

from __future__ import annotations

import random
from typing import List, Optional

from core.models import Concept, UserState
from schedule.SRS import is_due

DEFAULT_INTERLEAVE_PROBABILITY = 0.2   # 習熟済み概念を混ぜ込む確率
DEFAULT_HIGH_MASTERY_THRESHOLD = 0.8   # 「習熟済み」とみなす mastery の閾値


def _high_mastery_concepts(concepts: List[Concept], threshold: float) -> List[Concept]:
    return [c for c in concepts if c.current_mastery >= threshold]


def _weak_concepts(state: UserState, concepts: List[Concept]) -> List[Concept]:
    """弱点(blind_spots)を最優先し、無ければ習熟度の低い順に並べる。"""
    blind_spot_concepts = [c for c in concepts if c.id in state.blind_spots]
    if blind_spot_concepts:
        return blind_spot_concepts
    return sorted(concepts, key=lambda c: c.current_mastery)


def select_next_concept(
    state: UserState,
    *,
    interleave_probability: float = DEFAULT_INTERLEAVE_PROBABILITY,
    high_mastery_threshold: float = DEFAULT_HIGH_MASTERY_THRESHOLD,
    prefer_due_only: bool = False,
    rng: Optional[random.Random] = None,
) -> Optional[Concept]:
    """次に出題する概念を1つ選ぶ。

    選定ロジック:
      1. `interleave_probability` の確率で、習熟済み(mastery >= threshold)の
         概念からランダムに1つ選ぶ（インターリービング＝忘却防止の再確認）。
      2. それ以外の場合は、弱点(blind_spots)を最優先、無ければ
         習熟度が最も低い概念を選ぶ。
      3. `prefer_due_only=True` の場合、schedule/SRS.py の `next_review_date`
         に基づき復習期限が来ている概念のみを候補にする
         （該当が無ければ全概念にフォールバック）。

    概念が1つも無い場合は None を返す。
    """
    rng = rng or random.Random()
    concepts = list(state.concepts.values())
    if not concepts:
        return None

    candidate_pool = concepts
    if prefer_due_only:
        due_concepts = [c for c in concepts if is_due(c)]
        if due_concepts:
            candidate_pool = due_concepts
        # 期限が来ている概念が無ければ全概念にフォールバック（candidate_pool は変更しない）

    if rng.random() < interleave_probability:
        high_mastery = _high_mastery_concepts(candidate_pool, high_mastery_threshold)
        if high_mastery:
            return rng.choice(high_mastery)
        # 習熟済みの概念がまだ無い場合は通常選定にフォールバック

    weak = _weak_concepts(state, candidate_pool)
    return weak[0] if weak else None
