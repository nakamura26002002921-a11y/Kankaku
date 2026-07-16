# core/models.py
"""
外部ライブラリ (PsychoPy / LLM SDK 等) に一切依存しない、純粋なデータ定義層。
Pydantic v2 を用いて、LLM の出力や永続化データを厳密にバリデーションする。
"""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


# ==========================================
# 基本概念
# ==========================================

class Concept(BaseModel):
    """学習対象の概念"""
    id: str
    domain: str
    name: str
    current_mastery: float = Field(ge=0.0, le=1.0, default=0.3)

    @field_validator("current_mastery")
    @classmethod
    def clamp_mastery(cls, v: float) -> float:
        return max(0.0, min(1.0, v))


class DifficultyBand(str, Enum):
    """mastery から導出される難度バンド。プロンプトの条件分岐に用いる。"""
    EASY = "easy"          # mastery < 0.35
    MEDIUM = "medium"      # 0.35 <= mastery < 0.7
    HARD = "hard"          # mastery >= 0.7


# ==========================================
# シナリオ (問題) 関連
# ==========================================

class Scenario(BaseModel):
    """LLM が生成する A/B 直感テスト問題。Item Bank に永続化される最小単位。"""
    item_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    concept_id: str
    domain: str
    difficulty_band: DifficultyBand
    situation: str
    option_a: str
    option_b: str
    correct_answer: Literal["A", "B"]
    hidden_expert_eye: str

    # トレーサビリティ
    prompt_version: str = "v1"
    generated_at: float = Field(default_factory=time.time)
    source: Literal["llm", "fallback"] = "llm"

    # 間隔反復 (SM-2 簡易版) のスケジューリング状態
    repetitions: int = 0
    ease_factor: float = 2.5
    interval_days: float = 0.0
    due_at: float = Field(default_factory=time.time)  # unix timestamp
    last_reviewed_at: Optional[float] = None
    times_used: int = 0
    times_correct: int = 0

    @field_validator("ease_factor")
    @classmethod
    def clamp_ease(cls, v: float) -> float:
        return max(1.3, v)


class ScenarioLLMPayload(BaseModel):
    """LLM の生レスポンス(JSON)を検証するための厳密スキーマ。
    Scenario に変換する前段のバリデーションゲート。
    """
    situation: str = Field(min_length=1)
    option_a: str = Field(min_length=1)
    option_b: str = Field(min_length=1)
    correct_answer: Literal["A", "B"]
    hidden_expert_eye: str = Field(min_length=1)


# ==========================================
# ユーザー応答・メタ認知
# ==========================================

class UserResponse(BaseModel):
    """ユーザーの回答とメタ認知データ"""
    choice: Literal["A", "B"]
    confidence: int = Field(ge=1, le=5)
    reaction_time_ms: int = Field(ge=0)


class Feedback(BaseModel):
    """LLM または規則ベースで生成されるフィードバック"""
    is_correct: bool
    confidence_gap_analysis: str
    discrimination_metaphor: str
    updated_mastery_delta: float
    prompt_version: str = "v1"
    source: Literal["llm", "fallback"] = "llm"


class FeedbackLLMPayload(BaseModel):
    """フィードバック生成 LLM 応答の検証スキーマ"""
    confidence_gap_analysis: str = Field(min_length=1)
    discrimination_metaphor: str = Field(min_length=1)


# ==========================================
# ユーザー状態
# ==========================================

class UserState(BaseModel):
    """ユーザーの認知状態モデル(概念ごとの習熟度・ブラインドスポット等)"""
    user_id: str = "default"
    concepts: Dict[str, Concept] = Field(default_factory=dict)
    blind_spots: List[str] = Field(default_factory=list)

    def get_or_init_concept(self, concept_id: str, domain: str, name: str) -> Concept:
        if concept_id not in self.concepts:
            self.concepts[concept_id] = Concept(id=concept_id, domain=domain, name=name)
        return self.concepts[concept_id]


# ==========================================
# ログ用トライアルレコード
# ==========================================

class TrialRecord(BaseModel):
    """1試行分のログ。data_logger.py が CSV へ追記する際の型。"""
    timestamp: float = Field(default_factory=time.time)
    user_id: str
    concept_id: str
    item_id: str
    difficulty_band: str
    situation: str
    option_a: str
    option_b: str
    correct_answer: str
    choice: str
    confidence: int
    reaction_time_ms: int
    is_correct: bool
    mastery_before: float
    mastery_after: float
    scenario_prompt_version: str
    feedback_prompt_version: str
    scenario_source: str
    feedback_source: str
