#!/usr/bin/env python3
# scripts/pre_generate.py
"""
🚨 最重要: オフライン事前生成 CLI スクリプト

学習者がセッションを開始していない時間帯に、cron やタスクスケジューラから
実行することを想定した「純粋な Python スクリプト」。

PsychoPy (GUI) には一切依存しない。依存するのは以下のみ:
  - core/  (models, mastery, item_bank)
  - infra/ (llm_client, prompt_manager)
  - config.yaml

現在の習熟度(mastery)を `data/user_state.json` から読み取り、
その mastery に対応する難度バンドの問題が Item Bank に
`--target-stock` 件ストックされるまで LLM 生成を繰り返す。

使い方の例:
  # 全概念について、設定ファイルの既定値まで補充する
  python scripts/pre_generate.py

  # 特定の概念だけ、40問ストックされるまで生成する
  python scripts/pre_generate.py --concept-id ru_motion_verbs --target-stock 40

  # 各難度バンドを均等に埋める（cron 夜間バッチ向け）
  python scripts/pre_generate.py --all-bands --target-stock 15

  # ドライラン（何件生成が必要かだけ確認、LLMは呼ばない）
  python scripts/pre_generate.py --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import List

# main.py と同じ latentsense/ をルートとして import できるようにする
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml  # noqa: E402

from core.item_bank import ItemBank  # noqa: E402
from core.mastery import mastery_to_band  # noqa: E402
from core.models import Concept, DifficultyBand, UserState  # noqa: E402
from infra.llm_client import DefaultScenarioStore, LLMClientError, LLMContentClient, OllamaClient  # noqa: E402
from infra.prompt_manager import PromptManager  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("pre_generate")


def load_config(config_path: str) -> dict:
    path = Path(config_path)
    if not path.exists():
        logger.warning("config.yaml が見つかりません。デフォルト設定で続行します: %s", path)
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_user_state(path: str) -> UserState:
    state_path = Path(path)
    if not state_path.exists():
        logger.warning("user_state.json が見つかりません。新規状態で開始します: %s", state_path)
        return UserState()
    import json

    return UserState.model_validate(json.loads(state_path.read_text(encoding="utf-8")))


def save_user_state(state: UserState, path: str) -> None:
    import json

    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(state.model_dump_json(indent=2), encoding="utf-8")


def resolve_target_concepts(state: UserState, config: dict, concept_id_filter: str | None) -> List[Concept]:
    """生成対象の概念一覧を決定する。
    優先順位: --concept-id 指定 > user_state.json 内の概念 > config.yaml の seed_concepts
    """
    if concept_id_filter:
        if concept_id_filter in state.concepts:
            return [state.concepts[concept_id_filter]]
        # user_state にまだ無ければ config の seed から探す
        for seed in config.get("seed_concepts", []):
            if seed["id"] == concept_id_filter:
                return [Concept(**seed)]
        raise SystemExit(f"指定された concept_id が見つかりません: {concept_id_filter}")

    if state.concepts:
        return list(state.concepts.values())

    seeds = config.get("seed_concepts", [])
    if not seeds:
        raise SystemExit(
            "生成対象の概念がありません。user_state.json を作成するか、"
            "config.yaml に seed_concepts を定義してください。"
        )
    return [Concept(**seed) for seed in seeds]


def bands_to_fill(args: argparse.Namespace, concept: Concept) -> List[DifficultyBand]:
    if args.all_bands:
        return [DifficultyBand.EASY, DifficultyBand.MEDIUM, DifficultyBand.HARD]
    return [mastery_to_band(concept.current_mastery)]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="LLM を用いて Item Bank (問題バンク) をオフラインで事前生成する CLI スクリプト。"
    )
    parser.add_argument("--config", default="config.yaml", help="config.yaml へのパス")
    parser.add_argument("--user-state", default="data/user_state.json", help="ユーザー習熟度状態のJSONパス")
    parser.add_argument("--item-bank", default="data/item_bank.json", help="Item Bank JSON のパス")
    parser.add_argument("--default-scenarios", default="data/default_scenarios.json", help="フォールバック問題集のパス")
    parser.add_argument("--prompts-dir", default="prompts", help="プロンプトテンプレートのディレクトリ")
    parser.add_argument("--concept-id", default=None, help="このコンセプトIDのみ生成対象にする")
    parser.add_argument(
        "--target-stock",
        type=int,
        default=None,
        help="各 (concept, band) の目標ストック数。未指定なら config.yaml の値を使用（既定20）",
    )
    parser.add_argument(
        "--all-bands",
        action="store_true",
        help="現在の mastery バンドだけでなく easy/medium/hard 全バンドを均等に埋める",
    )
    parser.add_argument("--max-generate-per-item", type=int, default=200, help="1回の実行での総生成上限（暴走防止）")
    parser.add_argument("--dry-run", action="store_true", help="実際にはLLMを呼ばず、不足数の集計のみ行う")
    args = parser.parse_args()

    config = load_config(args.config)
    llm_cfg = config.get("llm", {})
    target_stock = args.target_stock or config.get("item_bank", {}).get("target_stock_per_band", 20)

    state = load_user_state(args.user_state)
    concepts = resolve_target_concepts(state, config, args.concept_id)

    bank = ItemBank(args.item_bank)
    prompt_manager = PromptManager(args.prompts_dir)
    ollama = OllamaClient(
        model=llm_cfg.get("model", "qwen2.5"),
        base_url=llm_cfg.get("base_url", "http://localhost:11434"),
        timeout=llm_cfg.get("timeout_seconds", 60),
    )
    default_store = DefaultScenarioStore(args.default_scenarios)
    content_client = LLMContentClient(
        ollama=ollama,
        prompt_manager=prompt_manager,
        default_store=default_store,
        max_retries=llm_cfg.get("max_retries", 2),
    )

    total_generated = 0
    total_failed = 0

    for concept in concepts:
        for band in bands_to_fill(args, concept):
            current_count = bank.count_available(concept.id, band)
            deficit = max(0, target_stock - current_count)

            logger.info(
                "概念=%s band=%s 現在庫=%d 目標=%d 不足=%d",
                concept.id, band.value, current_count, target_stock, deficit,
            )

            if deficit == 0:
                continue

            if args.dry_run:
                continue

            # band に対応する mastery の代表値を使ってプロンプトを条件分岐させる
            band_repr_mastery = {
                DifficultyBand.EASY: 0.2,
                DifficultyBand.MEDIUM: 0.5,
                DifficultyBand.HARD: 0.85,
            }[band]

            generated_for_band = 0
            while generated_for_band < deficit and total_generated < args.max_generate_per_item:
                try:
                    scenario = content_client.generate_scenario(concept, band_repr_mastery)
                    bank.add(scenario)
                    total_generated += 1
                    generated_for_band += 1
                    logger.info(
                        "  [+] 生成完了 item_id=%s source=%s prompt_version=%s",
                        scenario.item_id, scenario.source, scenario.prompt_version,
                    )
                except LLMClientError as exc:
                    total_failed += 1
                    logger.error("  [!] 生成失敗（フォールバックも不可）: %s", exc)
                    break  # このband/conceptはこれ以上進めても無駄な可能性が高い

            bank.save()

    if args.dry_run:
        logger.info("--dry-run のため、実際の生成は行いませんでした。")
    else:
        logger.info("完了: 合計 %d 件生成, %d 件失敗。Item Bank 総件数: %d", total_generated, total_failed, len(bank))

    # user_state.json が存在しなかった場合は、seed から作った状態を書き戻しておく
    save_user_state(state, args.user_state)


if __name__ == "__main__":
    main()
