#!/usr/bin/env python3
# main_web.py
"""
Streamlit アプリのエントリーポイント（Tailscale 分散構成の「UIクライアント」側）。

分散構成での役割分担:
  - ラップトップ（本アプリ）: Streamlit UI、出題選択(item_bank)、
    習熟度更新(mastery)、ログ記録 — すべてローカルで完結する。
  - デスクトップPC: Ollama を稼働させるだけの「LLMサーバー」。
    本アプリからは config.yaml の llm.base_url (Tailscale IP) 経由でのみ
    通信し、それも「在庫切れ時の緊急生成」または `pre_generate.py` 実行時
    に限られる。

起動:
  streamlit run main_web.py
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import streamlit as st
import yaml

from core.item_bank import ItemBank
from core.mastery import apply_feedback_to_concept, evaluate_response, mastery_to_band, sm2_update
from core.models import Concept, Feedback, TrialRecord, UserState
from infra.data_logger import DataLogger
from infra.llm_client import DefaultScenarioStore, LLMClientError, LLMContentClient, OllamaClient
from infra.prompt_manager import PromptManager
from ui.streamlit_view import (
    FlagRequest,
    inject_base_style,
    render_feedback,
    render_llm_connection_status,
    render_mastery_sidebar,
    render_scenario,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("main_web")

CONFIG_PATH = os.environ.get("LATENTSENSE_CONFIG", "config.yaml")
USER_STATE_PATH = os.environ.get("LATENTSENSE_USER_STATE", "data/user_state.json")
ITEM_BANK_PATH = os.environ.get("LATENTSENSE_ITEM_BANK", "data/item_bank.json")
DEFAULT_SCENARIOS_PATH = os.environ.get("LATENTSENSE_DEFAULT_SCENARIOS", "data/default_scenarios.json")
PROMPTS_DIR = os.environ.get("LATENTSENSE_PROMPTS_DIR", "prompts")
LOGS_DIR = os.environ.get("LATENTSENSE_LOGS_DIR", "data/logs")


# ==========================================
# 初期化 (st.session_state に一度だけロードする)
# ==========================================

import re

_ENV_DEFAULT_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*):-([^}]*)\}")


def _expand_env_with_defaults(raw: str) -> str:
    """${VAR:-default} 形式 (bashライク) と ${VAR} / $VAR の両方を展開する。
    os.path.expandvars は ':-default' 記法を解釈しないため、先にこちらを処理してから渡す。
    """
    def _sub(match: "re.Match[str]") -> str:
        var_name, default = match.group(1), match.group(2)
        return os.environ.get(var_name, default)

    raw = _ENV_DEFAULT_PATTERN.sub(_sub, raw)
    return os.path.expandvars(raw)


@st.cache_resource(show_spinner=False)
def load_config() -> dict:
    path = Path(CONFIG_PATH)
    if not path.exists():
        # 以前はここで黙って {} を返していたため、カレントディレクトリが
        # latentsense/ でない場合などに "設定が空 -> seed_concepts も読めない"
        # という原因不明のエラーにつながっていた。ここで明示的に警告する。
        st.session_state["_config_load_error"] = (
            f"config.yaml が見つかりません: {path.resolve()}\n"
            f"（カレントディレクトリ: {Path.cwd()}）\n"
            "`streamlit run main_web.py` は latentsense/ ディレクトリ直下で実行するか、"
            "環境変数 LATENTSENSE_CONFIG で config.yaml の絶対パスを指定してください。"
        )
        return {}
    raw = path.read_text(encoding="utf-8")
    # ${VAR:-default} / ${ENV_VAR} 形式のプレースホルダーを環境変数で展開する
    raw = _expand_env_with_defaults(raw)
    return yaml.safe_load(raw) or {}


def _seed_concepts_from_config(config: dict) -> dict[str, Concept]:
    concepts: dict[str, Concept] = {}
    for seed in config.get("seed_concepts", []):
        concept = Concept(**seed)
        concepts[concept.id] = concept
    return concepts


def _load_user_state(config: dict) -> UserState:
    state_path = Path(USER_STATE_PATH)
    state: UserState | None = None

    if state_path.exists():
        try:
            state = UserState.model_validate(json.loads(state_path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, ValueError) as exc:
            st.session_state["_config_load_error"] = (
                f"{state_path} の読み込みに失敗しました（{exc}）。seed_concepts から再初期化します。"
            )
            state = None

    if state is None:
        state = UserState()

    # ここが今回の主な修正点:
    # user_state.json が存在していても、中身に concepts が1件も無い場合
    # （壊れた初回実行や、config読み込み失敗時に空のまま保存された場合など）は
    # seed_concepts へフォールバックする。「ファイルが存在する=もう初期化済み」
    # とみなして seed_concepts を無視していたのが元のバグ。
    if not state.concepts:
        seeded = _seed_concepts_from_config(config)
        if not seeded:
            st.session_state["_config_load_error"] = (
                st.session_state.get("_config_load_error", "")
                + "\nconfig.yaml に seed_concepts が見つからないか、config自体が読み込めていません。"
            ).strip()
        state.concepts = seeded

    return state


def _save_user_state(state: UserState) -> None:
    path = Path(USER_STATE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(state.model_dump_json(indent=2), encoding="utf-8")


def init_session() -> None:
    """1回だけ行う「重い」初期化（config, LLMクライアント, ロガー等）。

    以前は state / bank もここに含めていたため、初回ロード時に
    data/user_state.json がまだ無く「概念が0件」で失敗すると、その空の
    状態が st.session_state に固定されてしまい、後から
    scripts/pre_generate.py でデータを生成してもブラウザを開いたままだと
    二度と再読込されない（サーバーの完全再起動が必須）というバグがあった。
    state / bank は refresh_state() で毎回の rerun ごとに読み直す。
    """
    if "initialized" in st.session_state:
        return

    config = load_config()
    st.session_state["config"] = config

    llm_cfg = config.get("llm", {})
    session_cfg = config.get("session", {})
    st.session_state["allow_online_fallback"] = session_cfg.get("allow_online_fallback", False)
    st.session_state["use_llm_feedback"] = session_cfg.get("use_llm_feedback", False)

    if st.session_state["allow_online_fallback"] or st.session_state["use_llm_feedback"]:
        prompt_manager = PromptManager(PROMPTS_DIR)
        ollama = OllamaClient(
            model=llm_cfg.get("model", "qwen2.5"),
            base_url=llm_cfg.get("base_url", "http://localhost:11434"),
            timeout=llm_cfg.get("timeout_seconds", 60),
        )
        st.session_state["content_client"] = LLMContentClient(
            ollama=ollama,
            prompt_manager=prompt_manager,
            default_store=DefaultScenarioStore(DEFAULT_SCENARIOS_PATH),
            max_retries=llm_cfg.get("max_retries", 2),
        )
    else:
        st.session_state["content_client"] = None

    st.session_state["current_item"] = None
    st.session_state["current_concept_id"] = None
    st.session_state["current_response"] = None
    st.session_state["current_feedback"] = None
    st.session_state["phase"] = "select"  # select -> answer -> feedback
    st.session_state["trial_count"] = 0
    st.session_state["initialized"] = True


def refresh_state() -> None:
    """state (user_state.json) と item_bank (item_bank.json) を毎回のrerunで読み直す。

    どちらも小さなJSONファイルの読み込みなのでコストは無視できるレベルであり、
    これにより「別プロセス(pre_generate.py)がバックグラウンドでデータを更新した」
    ケースでもブラウザをリロードするだけで反映されるようになる。
    ただし出題中(phase != 'select')に読み直すと出題内容がズレる恐れがあるため、
    出題選択待ちのタイミングでのみ更新する。
    """
    if st.session_state.get("phase") != "select" and "state" in st.session_state:
        return
    config = st.session_state["config"]
    st.session_state["state"] = _load_user_state(config)
    st.session_state["bank"] = ItemBank(ITEM_BANK_PATH)
    st.session_state["logger"] = DataLogger(user_id=st.session_state["state"].user_id, logs_dir=LOGS_DIR)


def select_focus_concept(state: UserState) -> Concept | None:
    if not state.concepts:
        return None
    for concept_id in state.blind_spots:
        if concept_id in state.concepts:
            return state.concepts[concept_id]
    return min(state.concepts.values(), key=lambda c: c.current_mastery)


def rule_based_gap_message(is_correct: bool, confidence: int) -> str:
    if is_correct and confidence >= 4:
        return "直感が正しく機能しています。この感覚を信頼して定着させましょう。"
    if is_correct and confidence < 4:
        return "正解でしたが確信度は低めでした。まだ『感覚』として定着していない可能性があります。"
    if not is_correct and confidence >= 4:
        return "自信満々でしたが不正解でした。誤った直感パターンが固着している可能性が高いです。要注意。"
    return "不正解でしたが確信度も低めでした。純粋な知識不足として、パターンをインプットしていきましょう。"


# ==========================================
# メインフロー
# ==========================================

def main() -> None:
    st.set_page_config(page_title="LatentSense", page_icon="🧠", layout="centered")
    init_session()
    refresh_state()
    inject_base_style()

    config = st.session_state["config"]
    state: UserState = st.session_state["state"]
    bank: ItemBank = st.session_state["bank"]

    st.title("🧠 LatentSense")
    st.caption("認知科学に基づく適応型学習 — Web UI クライアント (Tailscale分散構成)")

    concept = select_focus_concept(state)
    if concept is None:
        st.error("学習対象の概念がありません。")
        load_error = st.session_state.get("_config_load_error")
        if load_error:
            st.code(load_error, language=None)
        else:
            st.info(
                f"config.yaml のパス: `{Path(CONFIG_PATH).resolve()}`\n\n"
                f"user_state.json のパス: `{Path(USER_STATE_PATH).resolve()}`\n\n"
                "上記に seed_concepts が定義されているか確認してください。"
            )
        st.caption(
            "別プロセス（scripts/pre_generate.py 等）でデータを更新した場合は、"
            "下のボタンで再読込してください。"
        )
        if st.button("🔄 状態を再読込する"):
            st.session_state.pop("state", None)
            st.session_state.pop("bank", None)
            st.session_state.pop("_config_load_error", None)
            load_config.clear()  # st.cache_resource のキャッシュもクリアする
            st.rerun()
        return

    # seed_concepts から新規に初期化された場合はここで一度だけ永続化しておく
    if not Path(USER_STATE_PATH).exists() and state.concepts:
        _save_user_state(state)

    render_mastery_sidebar(concept.name, concept.current_mastery, state.blind_spots)

    llm_cfg = config.get("llm", {})
    with st.sidebar.expander("接続設定 (詳細)"):
        st.write(f"model: `{llm_cfg.get('model', 'qwen2.5')}`")
        st.write(f"base_url: `{llm_cfg.get('base_url', 'http://localhost:11434')}`")
        st.caption(
            "この base_url は Tailscale 経由でデスクトップPC(LLMサーバー)を指します。"
            "通常はローカルの item_bank.json のみを使用するため、この接続はアクセスされません。"
        )

    # ---------- フェーズ: 出題 ----------
    if st.session_state["phase"] == "select":
        band = mastery_to_band(concept.current_mastery)
        item = bank.get_next_item_for_session(concept.id, concept.current_mastery)

        if item is None:
            content_client: LLMContentClient | None = st.session_state["content_client"]
            if content_client is None:
                st.warning(
                    f"「{concept.name}」({band.value}) の在庫が Item Bank にありません。\n\n"
                    "デスクトップPC側で以下を実行し、事前生成してください:\n\n"
                    "```\npython scripts/pre_generate.py --concept-id "
                    f"{concept.id}\n```"
                )
                return
            with st.spinner("在庫切れのため、リモートLLM（デスクトップPC）へ緊急生成をリクエスト中..."):
                try:
                    item = content_client.generate_scenario(concept, concept.current_mastery)
                    bank.add(item)
                    bank.save()
                except LLMClientError as exc:
                    st.error(f"緊急生成にも失敗しました: {exc}")
                    return

        st.session_state["current_item"] = item
        st.session_state["current_concept_id"] = concept.id
        st.session_state["phase"] = "answer"
        st.rerun()

    # ---------- フェーズ: 回答待ち ----------
    elif st.session_state["phase"] == "answer":
        item = st.session_state["current_item"]
        result = render_scenario(item)

        if isinstance(result, FlagRequest):
            bank.flag(result.item_id, reason=result.reason)
            st.session_state["current_item"] = None
            st.session_state["phase"] = "select"
            st.toast(f"問題を報告してスキップしました（理由: {result.reason}）", icon="⚠️")
            st.rerun()

        elif result is not None:
            response = result
            st.session_state["current_response"] = response

            is_correct, mastery_delta, calibration_label = evaluate_response(item, response)

            content_client: LLMContentClient | None = st.session_state["content_client"]
            if content_client is not None and st.session_state["use_llm_feedback"]:
                with st.spinner("リモートLLMからフィードバックを取得中..."):
                    feedback = content_client.generate_feedback(item, response, is_correct, mastery_delta)
            else:
                feedback = Feedback(
                    is_correct=is_correct,
                    confidence_gap_analysis=rule_based_gap_message(is_correct, response.confidence),
                    discrimination_metaphor=f"プロの眼点: {item.hidden_expert_eye}",
                    updated_mastery_delta=mastery_delta,
                    prompt_version="rule_based",
                    source="fallback",
                )

            mastery_before = concept.current_mastery
            apply_feedback_to_concept(concept, response, feedback)
            sm2_update(item, is_correct=is_correct, confidence=response.confidence)
            bank.save()
            _save_user_state(state)

            if not is_correct and response.confidence >= 4:
                if concept.id not in state.blind_spots:
                    state.blind_spots.append(concept.id)
            elif is_correct and response.confidence >= 4 and concept.id in state.blind_spots:
                state.blind_spots.remove(concept.id)
            _save_user_state(state)

            st.session_state["logger"].append(
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

            st.session_state["current_feedback"] = feedback
            st.session_state["trial_count"] += 1
            st.session_state["phase"] = "feedback"
            st.rerun()

    # ---------- フェーズ: フィードバック表示 ----------
    elif st.session_state["phase"] == "feedback":
        item = st.session_state["current_item"]
        response = st.session_state["current_response"]
        feedback = st.session_state["current_feedback"]

        render_feedback(item, response, feedback)

        st.divider()
        if st.button("次の問題へ ▶", type="primary"):
            st.session_state["current_item"] = None
            st.session_state["current_response"] = None
            st.session_state["current_feedback"] = None
            st.session_state["phase"] = "select"
            st.rerun()

        st.caption(f"このセッションでの試行数: {st.session_state['trial_count']}")


if __name__ == "__main__":
    main()
