# infra/llm_client.py
"""
Ollama API (ローカル LLM) 呼び出し、Pydantic による厳密な JSON バリデーション、
リトライ、および `data/default_scenarios.json` へのフォールバックを担う層。

core/ は本モジュールに依存しない（依存の向きは infra -> core のみ）。
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from pydantic import ValidationError

from core.mastery import mastery_to_band
from core.models import (
    Concept,
    DifficultyBand,
    Feedback,
    FeedbackLLMPayload,
    Scenario,
    ScenarioLLMPayload,
    UserResponse,
)
from infra.prompt_manager import PromptManager

logger = logging.getLogger(__name__)


class LLMClientError(Exception):
    """LLM呼び出し・パース・バリデーションが全て失敗した場合に送出される。"""


class OllamaClient:
    """Ollama の /api/chat エンドポイントに対する薄いラッパー。"""

    def __init__(self, model: str = "qwen2.5", base_url: str = "http://localhost:11434", timeout: int = 60):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "format": "json",
        }
        response = requests.post(url, json=payload, timeout=self.timeout)
        response.raise_for_status()
        return response.json()["message"]["content"]

    @staticmethod
    def extract_json(raw_text: str) -> Dict[str, Any]:
        """LLM 出力から JSON オブジェクトを抽出する（コードフェンス除去 + 波括弧抽出）。"""
        clean_text = re.sub(r"```json|```", "", raw_text).strip()
        try:
            return json.loads(clean_text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", clean_text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    pass
        return {}


class DefaultScenarioStore:
    """LLM が完全に使えない場合のフォールバック元となる `data/default_scenarios.json`。"""

    def __init__(self, path: str | Path = "data/default_scenarios.json"):
        self.path = Path(path)

    def load(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []

    def pick_for(self, concept_id: str, band: DifficultyBand) -> Optional[Dict[str, Any]]:
        candidates = [
            d for d in self.load()
            if d.get("concept_id") == concept_id and d.get("difficulty_band") == band.value
        ]
        if not candidates:
            # concept 完全一致がなければ domain/band のみ緩く一致するものを許容
            candidates = [d for d in self.load() if d.get("difficulty_band") == band.value]
        return candidates[0] if candidates else None


class LLMContentClient:
    """core.models のスキーマに対して厳密にバリデーションされたコンテンツを返す高レベルクライアント。

    生成フロー:
      1. プロンプトをレンダリング
      2. Ollama へリクエスト (最大 max_retries 回)
      3. JSON抽出 -> Pydantic でバリデーション
      4. 全て失敗した場合は default_scenarios.json にフォールバック
    """

    def __init__(
        self,
        ollama: OllamaClient,
        prompt_manager: PromptManager,
        default_store: Optional[DefaultScenarioStore] = None,
        max_retries: int = 2,
    ):
        self.ollama = ollama
        self.prompts = prompt_manager
        self.default_store = default_store or DefaultScenarioStore()
        self.max_retries = max_retries

    # ---------- シナリオ生成 ----------

    def generate_scenario(self, concept: Concept, mastery: float) -> Scenario:
        band = mastery_to_band(mastery)
        user_prompt_version = self.prompts.get_version("scenario_gen")
        system_prompt_version = self.prompts.get_version("scenario_gen.system")
        prompt_version = f"{user_prompt_version}+sys:{system_prompt_version}"
        user_prompt = self.prompts.render(
            "scenario_gen",
            concept_name=concept.name,
            domain=concept.domain,
            mastery=f"{mastery:.2f}",
            difficulty_band=band.value,
        )
        system_prompt = self.prompts.render("scenario_gen.system")

        payload: Optional[ScenarioLLMPayload] = None
        last_error: Optional[Exception] = None

        for attempt in range(1, self.max_retries + 1):
            try:
                raw = self.ollama.chat(system_prompt, user_prompt)
                data = self.ollama.extract_json(raw)
                payload = ScenarioLLMPayload.model_validate(data)
                break
            except (requests.RequestException, ValidationError, KeyError, ValueError) as exc:
                last_error = exc
                logger.warning("シナリオ生成 試行 %d/%d 失敗: %s", attempt, self.max_retries, exc)
                time.sleep(0.5 * attempt)

        if payload is not None:
            return Scenario(
                concept_id=concept.id,
                domain=concept.domain,
                difficulty_band=band,
                situation=payload.situation,
                option_a=payload.option_a,
                option_b=payload.option_b,
                correct_answer=payload.correct_answer,
                hidden_expert_eye=payload.hidden_expert_eye,
                prompt_version=prompt_version,
                source="llm",
            )

        # ---- フォールバック ----
        logger.error("シナリオ生成に失敗したためフォールバックへ切り替え: %s", last_error)
        fallback = self.default_store.pick_for(concept.id, band)
        if fallback is None:
            raise LLMClientError(
                f"LLM生成にも失敗し、フォールバック候補も見つかりませんでした "
                f"(concept_id={concept.id}, band={band.value})"
            )
        return Scenario(
            concept_id=concept.id,
            domain=concept.domain,
            difficulty_band=band,
            situation=fallback.get("situation", "N/A"),
            option_a=fallback.get("option_a", "N/A"),
            option_b=fallback.get("option_b", "N/A"),
            correct_answer=fallback.get("correct_answer", "A"),
            hidden_expert_eye=fallback.get("hidden_expert_eye", "N/A"),
            prompt_version="fallback",
            source="fallback",
        )

    # ---------- フィードバック生成 ----------

    def generate_feedback(self, scenario: Scenario, response: UserResponse, is_correct: bool, mastery_delta: float) -> Feedback:
        user_prompt_version = self.prompts.get_version("feedback_gen")
        system_prompt_version = self.prompts.get_version("feedback_gen.system")
        prompt_version = f"{user_prompt_version}+sys:{system_prompt_version}"
        user_prompt = self.prompts.render(
            "feedback_gen",
            situation=scenario.situation,
            option_a=scenario.option_a,
            option_b=scenario.option_b,
            correct_answer=scenario.correct_answer,
            choice=response.choice,
            confidence=str(response.confidence),
            is_correct=str(is_correct),
            hidden_expert_eye=scenario.hidden_expert_eye,
        )
        system_prompt = self.prompts.render("feedback_gen.system")

        payload: Optional[FeedbackLLMPayload] = None
        last_error: Optional[Exception] = None

        for attempt in range(1, self.max_retries + 1):
            try:
                raw = self.ollama.chat(system_prompt, user_prompt)
                data = self.ollama.extract_json(raw)
                payload = FeedbackLLMPayload.model_validate(data)
                break
            except (requests.RequestException, ValidationError, KeyError, ValueError) as exc:
                last_error = exc
                logger.warning("フィードバック生成 試行 %d/%d 失敗: %s", attempt, self.max_retries, exc)
                time.sleep(0.5 * attempt)

        if payload is not None:
            return Feedback(
                is_correct=is_correct,
                confidence_gap_analysis=payload.confidence_gap_analysis,
                discrimination_metaphor=payload.discrimination_metaphor,
                updated_mastery_delta=mastery_delta,
                prompt_version=prompt_version,
                source="llm",
            )

        logger.error("フィードバック生成に失敗したため規則ベースへフォールバック: %s", last_error)
        return Feedback(
            is_correct=is_correct,
            confidence_gap_analysis="（LLM応答不可のため定型メッセージ）自身の回答と結果を照らし合わせて振り返ってみましょう。",
            discrimination_metaphor=f"プロの眼点: {scenario.hidden_expert_eye}",
            updated_mastery_delta=mastery_delta,
            prompt_version="fallback",
            source="fallback",
        )
