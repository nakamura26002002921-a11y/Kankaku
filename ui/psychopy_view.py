# ui/psychopy_view.py
"""
PsychoPy 専用の描画・キー入力・反応時間(RT)計測ロジック。

このモジュールだけが `psychopy` パッケージに依存する。
core/ 及び infra/ は本モジュールを一切 import しないため、
scripts/pre_generate.py など GUI 不要な文脈では import されない。
"""

from __future__ import annotations

from typing import Optional

from psychopy import core as psychopy_core
from psychopy import event, visual

from core.models import Feedback, Scenario, UserResponse


class PsychoPyView:
    """PsychoPy の Window を保持し、シナリオ提示・回答取得・フィードバック表示を行う。"""

    def __init__(self, fullscreen: bool = False, window_size=(1024, 768), bg_color="#1e1e2e"):
        self.win = visual.Window(
            size=window_size,
            fullscr=fullscreen,
            color=bg_color,
            units="height",
        )
        self.clock = psychopy_core.Clock()

    def close(self) -> None:
        self.win.close()

    # ---------- 内部ヘルパー ----------

    def _text(self, text: str, pos=(0, 0), height: float = 0.05, color: str = "white", wrap_width: float = 1.4):
        return visual.TextStim(
            self.win,
            text=text,
            pos=pos,
            height=height,
            color=color,
            wrapWidth=wrap_width,
            alignText="center",
        )

    def _flip_and_wait_keys(self, stims, valid_keys):
        for stim in stims:
            stim.draw()
        self.win.flip()
        keys = event.waitKeys(keyList=valid_keys + ["escape"])
        if "escape" in keys:
            self.close()
            raise KeyboardInterrupt("ユーザーによりセッションが中断されました。")
        return keys[0]

    # ---------- 公開 API ----------

    def show_message(self, message: str, wait_key: str = "space") -> None:
        stim = self._text(message, height=0.045)
        prompt = self._text(f"(続けるには {wait_key.upper()} キー)", pos=(0, -0.4), height=0.03, color="#aaaaaa")
        self._flip_and_wait_keys([stim, prompt], valid_keys=[wait_key])

    def present_scenario_and_get_response(self, scenario: Scenario) -> UserResponse:
        """シナリオを提示し、A/B の選択（キー入力）と反応時間を計測する。
        System 1（直感）を測定する意図から、選択直後に確信度評定へ移行する。
        """
        situation_stim = self._text(scenario.situation, pos=(0, 0.25), height=0.045)
        option_a_stim = self._text(f"[F] {scenario.option_a}", pos=(0, -0.05), height=0.04)
        option_b_stim = self._text(f"[J] {scenario.option_b}", pos=(0, -0.15), height=0.04)
        instruction_stim = self._text(
            "直感で選んでください: F = A / J = B", pos=(0, -0.4), height=0.03, color="#aaaaaa"
        )

        for stim in (situation_stim, option_a_stim, option_b_stim, instruction_stim):
            stim.draw()
        self.win.flip()

        self.clock.reset()
        keys = event.waitKeys(keyList=["f", "j", "escape"])
        reaction_time_ms = int(self.clock.getTime() * 1000)

        if "escape" in keys:
            self.close()
            raise KeyboardInterrupt("ユーザーによりセッションが中断されました。")

        choice = "A" if keys[0] == "f" else "B"

        confidence = self._get_confidence_rating()

        return UserResponse(choice=choice, confidence=confidence, reaction_time_ms=reaction_time_ms)  # type: ignore[arg-type]

    def _get_confidence_rating(self) -> int:
        prompt = self._text(
            "自分の選択への確信度は？\n1 (当てずっぽう) 〜 5 (絶対の自信)",
            pos=(0, 0.1),
            height=0.04,
        )
        hint = self._text("数字キー 1〜5 を押してください", pos=(0, -0.15), height=0.03, color="#aaaaaa")
        key = self._flip_and_wait_keys([prompt, hint], valid_keys=["1", "2", "3", "4", "5"])
        return int(key)

    def show_feedback(self, scenario: Scenario, response: UserResponse, feedback: Feedback) -> None:
        result_label = "✅ 正解！" if feedback.is_correct else "❌ 予測誤差（不正解）"
        result_color = "#7CFC00" if feedback.is_correct else "#FF6347"

        result_stim = self._text(result_label, pos=(0, 0.3), height=0.06, color=result_color)
        gap_stim = self._text(feedback.confidence_gap_analysis, pos=(0, 0.1), height=0.035)
        metaphor_stim = self._text(feedback.discrimination_metaphor, pos=(0, -0.15), height=0.035, color="#87CEFA")
        continue_stim = self._text("(続けるには SPACE キー)", pos=(0, -0.4), height=0.028, color="#aaaaaa")

        self._flip_and_wait_keys(
            [result_stim, gap_stim, metaphor_stim, continue_stim], valid_keys=["space"]
        )

    def show_session_summary(self, num_trials: int, blind_spots: list[str]) -> None:
        lines = [f"セッション終了。全 {num_trials} 試行を完了しました。"]
        if blind_spots:
            lines.append(f"⚠️ 要注意（自信過剰バイアス検出）: {', '.join(blind_spots)}")
        else:
            lines.append("ブラインドスポットは検出されませんでした。")
        self.show_message("\n".join(lines), wait_key="space")
