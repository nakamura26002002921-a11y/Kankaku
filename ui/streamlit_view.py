# ui/streamlit_view.py
"""
Streamlit 専用の描画コンポーネント層。

このモジュールだけが `streamlit` に依存する。core/ 及び infra/ は
本モジュールを一切 import しないため、依存の向きは
ui -> core/infra の一方向のみに保たれる（scripts/pre_generate.py など
GUI不要な文脈からは import されない）。

Tailscale 分散構成では、本ファイルはラップトップ（UIクライアント）側でのみ
実行される。LLM 呼び出しは行わず、core/item_bank.py が返す Scenario を
表示し、core/mastery.py の評価結果を表示するだけの「純粋な描画」に徹する。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional, Union

import streamlit as st

from core.models import Feedback, Scenario, UserResponse

# 「この問題はおかしい」で選べる不備の種類。
# ユーザー報告のように、LLMの性能不足で言語が混ざる（例: ロシア語の問題文に
# 中国語が混入する）ケースを想定した項目を含む。
REPORT_REASONS = [
    "言語が混在している（例: 意図しない他言語が混ざっている）",
    "選択肢の意味が重複・矛盾している",
    "文章が破損している / 意味が通らない",
    "その他",
]


@dataclass
class FlagRequest:
    """「この問題はおかしい」ボタンが押されたことを呼び出し側に伝えるための戻り値。"""
    item_id: str
    reason: str


def inject_base_style() -> None:
    """アプリ全体で一度だけ呼ぶ軽量なスタイル調整。"""
    st.markdown(
        """
        <style>
        .ls-situation { font-size: 1.15rem; line-height: 1.7; margin-bottom: 1rem; }
        .ls-badge { display:inline-block; padding: 2px 10px; border-radius: 999px;
                    font-size: 0.75rem; background:#334155; color:#e2e8f0; margin-bottom: .5rem;}
        .ls-correct { color:#22c55e; font-weight:700; }
        .ls-incorrect { color:#ef4444; font-weight:700; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_scenario(scenario: Scenario) -> Optional[Union[UserResponse, FlagRequest]]:
    """状況と選択肢ボタンを表示し、回答が確定したら UserResponse を、
    「この問題はおかしい」が押された場合は FlagRequest を返す。

    直感反応の計測(reaction_time_ms)のため、この関数が最初に呼ばれた
    タイミングを `st.session_state["_scenario_shown_at"]` に記録する。
    確信度(1-5)はボタン選択後の2段階目のUIで取得する。
    """
    if "_scenario_shown_at" not in st.session_state or st.session_state.get("_scenario_item_id") != scenario.item_id:
        st.session_state["_scenario_shown_at"] = time.time()
        st.session_state["_scenario_item_id"] = scenario.item_id
        st.session_state.pop("_pending_choice", None)

    st.markdown(f'<span class="ls-badge">難度: {scenario.difficulty_band.value}</span>', unsafe_allow_html=True)
    st.markdown(f'<div class="ls-situation">{scenario.situation}</div>', unsafe_allow_html=True)

    # ---- 品質不良の報告UI（LLMの性能不足による言語混在などを想定） ----
    with st.expander("⚠️ この問題はおかしい（言語混在・文章破損など）"):
        reason = st.selectbox(
            "不備の種類を選んでください",
            REPORT_REASONS,
            key=f"report_reason_{scenario.item_id}",
        )
        if st.button("この問題を報告してスキップする", key=f"report_btn_{scenario.item_id}"):
            st.session_state.pop("_pending_choice", None)
            st.session_state.pop("_scenario_shown_at", None)
            st.session_state.pop("_scenario_item_id", None)
            return FlagRequest(item_id=scenario.item_id, reason=reason)

    pending_choice = st.session_state.get("_pending_choice")

    if pending_choice is None:
        col_a, col_b = st.columns(2)
        with col_a:
            if st.button(f"A: {scenario.option_a}", use_container_width=True, key=f"opt_a_{scenario.item_id}"):
                st.session_state["_pending_choice"] = "A"
                st.rerun()
        with col_b:
            if st.button(f"B: {scenario.option_b}", use_container_width=True, key=f"opt_b_{scenario.item_id}"):
                st.session_state["_pending_choice"] = "B"
                st.rerun()
        return None

    # ---- 確信度評定ステップ ----
    st.markdown(f"選択: **{pending_choice}**")
    confidence = st.radio(
        "自分の選択への確信度は？",
        options=[1, 2, 3, 4, 5],
        format_func=lambda v: {1: "1: 当てずっぽう", 5: "5: 絶対の自信"}.get(v, str(v)),
        horizontal=True,
        key=f"confidence_{scenario.item_id}",
    )

    if st.button("回答を確定する", type="primary", key=f"confirm_{scenario.item_id}"):
        reaction_time_ms = int((time.time() - st.session_state["_scenario_shown_at"]) * 1000)
        response = UserResponse(
            choice=pending_choice,  # type: ignore[arg-type]
            confidence=int(confidence),
            reaction_time_ms=reaction_time_ms,
        )
        # 次の描画サイクルのために評定用ステートをクリア
        st.session_state.pop("_pending_choice", None)
        st.session_state.pop("_scenario_shown_at", None)
        st.session_state.pop("_scenario_item_id", None)
        return response

    return None


def render_feedback(scenario: Scenario, response: UserResponse, feedback: Feedback) -> None:
    """分析結果(confidence_gap_analysis)とメタファー(discrimination_metaphor)を表示する。"""
    if feedback.is_correct:
        st.markdown('<span class="ls-correct">✅ 正解！</span>', unsafe_allow_html=True)
    else:
        st.markdown('<span class="ls-incorrect">❌ 予測誤差（不正解）</span>', unsafe_allow_html=True)

    st.write(f"あなたの回答: **{response.choice}**（確信度 {response.confidence}/5、反応時間 {response.reaction_time_ms}ms）")

    with st.container(border=True):
        st.markdown("**🔍 メタ認知診断**")
        st.write(feedback.confidence_gap_analysis)

    with st.container(border=True):
        st.markdown("**🔮 専門家の判断基準**")
        st.write(feedback.discrimination_metaphor)

    st.caption(
        f"source={feedback.source} / scenario_prompt_version={scenario.prompt_version} "
        f"/ feedback_prompt_version={feedback.prompt_version}"
    )


def render_mastery_sidebar(concept_name: str, mastery: float, blind_spots: list[str]) -> None:
    """サイドバーに現在の概念と習熟度、ブラインドスポットを表示する。"""
    with st.sidebar:
        st.markdown("### 🧠 現在の学習状況")
        st.write(f"概念: **{concept_name}**")
        st.progress(mastery, text=f"習熟度: {mastery:.2f}")
        if blind_spots:
            st.warning("⚠️ ブラインドスポット（自信過剰バイアス検出）: " + ", ".join(blind_spots))
        else:
            st.success("ブラインドスポットは検出されていません。")


def render_llm_connection_status(base_url: str, ok: bool, detail: str = "") -> None:
    """Tailscale 経由の LLM サーバー接続状態を表示する（診断用）。"""
    with st.sidebar:
        st.markdown("### 🌐 LLM サーバー接続")
        st.code(base_url, language=None)
        if ok:
            st.success("接続OK")
        else:
            st.error(f"接続失敗: {detail}" if detail else "接続失敗")
