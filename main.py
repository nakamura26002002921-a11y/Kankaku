#!/usr/bin/env python3
# main.py
"""
PsychoPy UI を起動するエントリーポイント。

設計上の要点:
  - セッション実行中は LLM を直接呼ばない。scripts/pre_generate.py が
    事前に積んだ Item Bank (core/item_bank.py) から即座に出題することで
    レイテンシをゼロに保つ。
  - 在庫切れ（Item Bank に該当 concept/band の問題が無い）場合のみ、
    フォールバックとして緊急のオンライン生成を行う（任意・config で無効化可）。
  - オーケストレーションは本ファイルが担い、UI描画は ui/psychopy_view.py、
    ドメインロジックは core/、外部接続は infra/ にそれぞれ隔離する。
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import List

import yaml

from core.item_bank import ItemBank
from core.mastery import apply_feedback_to_concept, evaluate_response, mastery_to_band, sm2_update
from core.models import Concept, TrialRecord, UserState
from infra.data_logger import DataLogger
from infra.llm_client import DefaultScenarioStore, LLMClientError, LLMContentClient, OllamaClient
from infra.prompt_manager import PromptManager
from schedule.interleaving import select_next_concept
from schedule.SRS import update_concept_schedule

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("main")


def load_config(path: str = "config.yaml") -> dict:
    cfg_path = Path(path)
    if not cfg_path.exists():
        logger.warning("config.yaml が見つかりません。デフォルト設定で起動します。")
        return {}
    return yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}


def load_user_state(path: str, config: dict) -> UserState:
    state_path = Path(path)
    if state_path.exists():
        return UserState.model_validate(json.loads(state_path.read_text(encoding="utf-8")))

    state = UserState()
    for seed in config.get("seed_concepts", []):
        concept = Concept(**seed)
        state.concepts[concept.id] = concept
    return state


def save_user_state(state: UserState, path: str) -> None:
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(state.model_dump_json(indent=2), encoding="utf-8")


def select_focus_concept(state: UserState, config: dict) -> Concept:
    """schedule/interleaving.py の選定ロジックを config.yaml の設定値で呼び出す。"""
    if not state.concepts:
        raise SystemExit("学習対象の概念がありません。config.yaml の seed_concepts を確認してください。")

    interleaving_cfg = config.get("interleaving", {})
    concept = select_next_concept(
        state,
        interleave_probability=interleaving_cfg.get("probability", 0.2),
        high_mastery_threshold=interleaving_cfg.get("high_mastery_threshold", 0.8),
        prefer_due_only=interleaving_cfg.get("prefer_due_only", False),
    )
    assert concept is not None  # state.concepts が空でないことは上でチェック済み
    return concept


def run_session(args: argparse.Namespace) -> None:
    # PsychoPy 依存は main.py 内でのみ import する（core/infra を汚染しない）
    from ui.psychopy_view import PsychoPyView

    config = load_config(args.config)
    session_cfg = config.get("session", {})
    llm_cfg = config.get("llm", {})

    state = load_user_state(args.user_state, config)
    bank = ItemBank(args.item_bank)
    data_logger = DataLogger(user_id=state.user_id, logs_dir=args.logs_dir)

    # 在庫切れ時の緊急オンライン生成（既定では無効。config.session.allow_online_fallback で有効化）
    content_client: LLMContentClient | None = None
    if session_cfg.get("allow_online_fallback", False):
        prompt_manager = PromptManager(args.prompts_dir)
        ollama = OllamaClient(
            model=llm_cfg.get("model", "qwen2.5"),
            base_url=llm_cfg.get("base_url", "http://localhost:11434"),
            timeout=llm_cfg.get("timeout_seconds", 60),
        )
        content_client = LLMContentClient(
            ollama=ollama,
            prompt_manager=prompt_manager,
            default_store=DefaultScenarioStore(args.default_scenarios),
            max_retries=llm_cfg.get("max_retries", 2),
        )

    view = PsychoPyView(fullscreen=session_cfg.get("fullscreen", False))
    num_iterations = args.iterations or session_cfg.get("default_iterations", 5)

    try:
        view.show_message(
            "🧠 LatentSense: 認知科学に基づく学習セッションを開始します。",
            wait_key="space",
        )

        for i in range(num_iterations):
            concept = select_focus_concept(state, config)
            band = mastery_to_band(concept.current_mastery)

            item = bank.get_next_item_for_session(concept.id, concept.current_mastery)

            if item is None:
                if content_client is None:
                    logger.error(
                        "Item Bank に在庫がありません (concept=%s, band=%s)。"
                        "事前に `python scripts/pre_generate.py` を実行してください。",
                        concept.id, band.value,
                    )
                    view.show_message(
                        f"問題の在庫がありません（{concept.name}）。\n"
                        "事前生成スクリプトを実行してから再度お試しください。",
                        wait_key="space",
                    )
                    break
                logger.warning("在庫切れのため緊急オンライン生成を行います: concept=%s", concept.id)
                try:
                    item = content_client.generate_scenario(concept, concept.current_mastery)
                    bank.add(item)
                    bank.save()
                except LLMClientError as exc:
                    logger.error("緊急生成にも失敗しました: %s", exc)
                    break

            response = view.present_scenario_and_get_response(item)

            is_correct, mastery_delta, calibration_label = evaluate_response(item, response)
            logger.info("判定: is_correct=%s calibration=%s", is_correct, calibration_label)

            if content_client is not None and session_cfg.get("use_llm_feedback", False):
                feedback = content_client.generate_feedback(item, response, is_correct, mastery_delta)
            else:
                # セッション中は既定でLLMを呼ばず、規則ベースの即時フィードバックを使う
                from core.models import Feedback

                feedback = Feedback(
                    is_correct=is_correct,
                    confidence_gap_analysis=_rule_based_gap_message(calibration_label),
                    discrimination_metaphor=f"プロの眼点: {item.hidden_expert_eye}",
                    updated_mastery_delta=mastery_delta,
                    prompt_version="rule_based",
                    source="fallback",
                )

            mastery_before = concept.current_mastery
            apply_feedback_to_concept(concept, response, feedback)
            sm2_update(item, is_correct=is_correct, confidence=response.confidence)

            srs_cfg = config.get("srs", {})
            update_concept_schedule(
                concept,
                is_correct=is_correct,
                confidence=response.confidence,
                base_interval_days=srs_cfg.get("base_interval_days", 1.0),
                growth_factor=srs_cfg.get("growth_factor", 2.5),
                confidence_threshold=srs_cfg.get("confidence_threshold", 4),
            )

            bank.save()

            # ブラインドスポットの更新
            if not is_correct and response.confidence >= 4:
                if concept.id not in state.blind_spots:
                    state.blind_spots.append(concept.id)
            elif is_correct and response.confidence >= 4 and concept.id in state.blind_spots:
                state.blind_spots.remove(concept.id)

            view.show_feedback(item, response, feedback)

            data_logger.append(
                TrialRecord(
                    user_id=state.user_id,
                    concept_id=concept.id,
                    item_id=item.item_id,
                    difficulty_band=item.difficulty_band.value,
                    situation=item.situation,
                    option_a=item.option_a,
                    option_b=item.option_b,
                    correct_answer=item.correct_answer,
                    choice=response.choice,
                    confidence=response.confidence,
                    reaction_time_ms=response.reaction_time_ms,
                    is_correct=is_correct,
                    mastery_before=mastery_before,
                    mastery_after=concept.current_mastery,
                    scenario_prompt_version=item.prompt_version,
                    feedback_prompt_version=feedback.prompt_version,
                    scenario_source=item.source,
                    feedback_source=feedback.source,
                )
            )

        view.show_session_summary(num_trials=num_iterations, blind_spots=state.blind_spots)

    except KeyboardInterrupt:
        logger.info("セッションが中断されました。ここまでの状態を保存します。")
    finally:
        save_user_state(state, args.user_state)
        view.close()


def _rule_based_gap_message(calibration_label: str) -> str:
    messages = {
        "well_calibrated_correct": "直感が正しく機能しています。この感覚を信頼して定着させましょう。",
        "underconfident_correct": "正解でしたが確信度は低めでした。まだ『感覚』として定着していない可能性があります。",
        "overconfident_incorrect": "自信満々でしたが不正解でした。誤った直感パターンが固着している可能性が高いです。要注意。",
        "underconfident_incorrect": "不正解でしたが確信度も低めでした。純粋な知識不足として、パターンをインプットしていきましょう。",
    }
    return messages.get(calibration_label, "結果を振り返ってみましょう。")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="LatentSense: 認知科学ベースの適応型学習セッション")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--user-state", default="data/user_state.json")
    parser.add_argument("--item-bank", default="data/item_bank.json")
    parser.add_argument("--default-scenarios", default="data/default_scenarios.json")
    parser.add_argument("--prompts-dir", default="prompts")
    parser.add_argument("--logs-dir", default="data/logs")
    parser.add_argument("--iterations", type=int, default=None, help="このセッションでの試行回数")
    return parser


if __name__ == "__main__":
    args = build_arg_parser().parse_args()
    run_session(args)
