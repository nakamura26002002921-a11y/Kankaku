# core/mastery.py
"""
習熟度 (mastery) の更新ロジックと、SM-2 簡易版による間隔反復スケジューラ。
PsychoPy にも LLM SDK にも依存しない純粋関数群。
"""

from __future__ import annotations

import time
from typing import Tuple

from core.models import Concept, DifficultyBand, Feedback, Scenario, UserResponse

DAY_SECONDS = 24 * 60 * 60


def mastery_to_band(mastery: float) -> DifficultyBand:
    """mastery (0.0~1.0) から難度バンドを決定する。"""
    if mastery < 0.35:
        return DifficultyBand.EASY
    if mastery < 0.7:
        return DifficultyBand.MEDIUM
    return DifficultyBand.HARD


def compute_mastery_delta(is_correct: bool, confidence: int) -> float:
    """正誤 x 自信度から習熟度デルタを算出する（メタ認知キャリブレーション込み）。

    - 正解 & 高確信(4-5)  : 直感が正しく定着 → 大きく加点
    - 正解 & 低確信(1-3)  : 偶然の正解/未成熟 → 小さく加点
    - 不正解 & 高確信(4-5): 自信過剰バイアス（危険な誤り）→ 大きく減点
    - 不正解 & 低確信(1-3): 純粋な知識不足 → 小さく減点
    """
    if is_correct:
        return 0.10 if confidence >= 4 else 0.05
    return -0.15 if confidence >= 4 else -0.05


def detect_calibration_gap(is_correct: bool, confidence: int) -> str:
    """自信度と正誤のギャップを検出し、ラベルを返す。"""
    if is_correct and confidence >= 4:
        return "well_calibrated_correct"
    if is_correct and confidence < 4:
        return "underconfident_correct"
    if not is_correct and confidence >= 4:
        return "overconfident_incorrect"
    return "underconfident_incorrect"


def apply_feedback_to_concept(concept: Concept, response: UserResponse, feedback: Feedback) -> Concept:
    """フィードバックを概念の mastery に反映する（破壊的更新して返す）。"""
    concept.current_mastery = max(0.0, min(1.0, concept.current_mastery + feedback.updated_mastery_delta))
    return concept


def sm2_update(scenario: Scenario, is_correct: bool, confidence: int) -> Scenario:
    """SM-2 アルゴリズムの簡易版で、問題(Scenario)の次回出題間隔を更新する。

    quality (0-5) は 正誤 と 確信度 から合成する:
      不正解 -> 0-2 (確信度が高いほど低品質＝すぐ再出題)
      正解   -> 3-5 (確信度が高いほど高品質＝間隔を伸ばす)
    """
    if is_correct:
        quality = 3 + min(2, confidence - 3) if confidence >= 4 else 3
        quality = max(3, min(5, quality))
    else:
        quality = max(0, 2 - max(0, confidence - 3))

    scenario.times_used += 1
    if is_correct:
        scenario.times_correct += 1

    if quality < 3:
        # 品質が低い（不正解）場合はリセットして翌日再出題
        scenario.repetitions = 0
        scenario.interval_days = 1.0
    else:
        if scenario.repetitions == 0:
            scenario.interval_days = 1.0
        elif scenario.repetitions == 1:
            scenario.interval_days = 6.0
        else:
            scenario.interval_days = round(scenario.interval_days * scenario.ease_factor, 2)
        scenario.repetitions += 1

    # Ease Factor の更新 (SM-2 標準式)
    ef = scenario.ease_factor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    scenario.ease_factor = max(1.3, round(ef, 3))

    scenario.last_reviewed_at = time.time()
    scenario.due_at = scenario.last_reviewed_at + scenario.interval_days * DAY_SECONDS

    return scenario


def evaluate_response(scenario: Scenario, response: UserResponse) -> Tuple[bool, float, str]:
    """回答を評価し、(正誤, mastery_delta, calibration_label) を返す。"""
    is_correct = response.choice == scenario.correct_answer
    delta = compute_mastery_delta(is_correct, response.confidence)
    label = detect_calibration_gap(is_correct, response.confidence)
    return is_correct, delta, label
