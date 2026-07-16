# core/item_bank.py
"""
問題バンク (Item Bank) の管理。

- 外部ライブラリ(PsychoPy/LLM SDK)に依存しない、純粋な JSON 永続化ロジック。
- scripts/pre_generate.py (CLI, オフライン) と ui/psychopy_view.py 経由の
  セッション実行(main.py, オンライン) の両方から呼び出される「共通の入口」。
- セッション中は基本的に LLM を呼ばず、ここに蓄積された問題を
  SM-2 スケジューラの due_at に従って取り出すだけにすることで、
  体感レイテンシをゼロに保つ。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import List, Optional

from core.mastery import mastery_to_band, sm2_update
from core.models import DifficultyBand, Scenario


class ItemBank:
    """`data/item_bank.json` を読み書きする問題バンクリポジトリ。"""

    def __init__(self, path: str | Path = "data/item_bank.json"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._items: List[Scenario] = self._load()

    # ---------- 永続化 ----------

    def _load(self) -> List[Scenario]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return [Scenario.model_validate(item) for item in raw]
        except (json.JSONDecodeError, ValueError):
            # 壊れたバンクファイルは空として扱う（上書き保存で自然に修復される）
            return []

    def save(self) -> None:
        payload = [item.model_dump(mode="json") for item in self._items]
        tmp_path = self.path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(self.path)  # アトミックに置換し、書き込み中のクラッシュに備える

    # ---------- 追加 (pre_generate.py から呼ばれる) ----------

    def add(self, scenario: Scenario) -> None:
        self._items.append(scenario)

    def add_many(self, scenarios: List[Scenario]) -> None:
        self._items.extend(scenarios)

    # ---------- 検索・出題選択 (main.py / ui から呼ばれる) ----------

    def count_available(self, concept_id: str, band: DifficultyBand) -> int:
        """指定 concept x band の在庫数（出題可能かに関わらず全件）。
        pre_generate.py が「あとどれだけ生成すべきか」を判断するのに使う。
        """
        return sum(1 for it in self._items if it.concept_id == concept_id and it.difficulty_band == band)

    def next_due_item(self, concept_id: str, band: Optional[DifficultyBand] = None) -> Optional[Scenario]:
        """SM-2 の due_at を過ぎている問題の中から、最も期限切れ度合いが高いものを返す。
        band を指定しない場合は mastery バンドに関わらず最優先の期限切れ問題を探す。
        """
        now = time.time()
        candidates = [
            it for it in self._items
            if it.concept_id == concept_id and it.due_at <= now
            and (band is None or it.difficulty_band == band)
        ]
        if not candidates:
            return None
        # もっとも due_at が過去（＝長く待たされている）ものを優先
        return min(candidates, key=lambda it: it.due_at)

    def pick_new_item(self, concept_id: str, band: DifficultyBand) -> Optional[Scenario]:
        """まだ一度も使われていない (times_used == 0) 問題を優先的に取り出す。
        事前生成された新規ストックを使い切ってから間隔反復に回すための入口。
        """
        candidates = [
            it for it in self._items
            if it.concept_id == concept_id and it.difficulty_band == band and it.times_used == 0
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda it: it.generated_at)

    def get_next_item_for_session(self, concept_id: str, mastery: float) -> Optional[Scenario]:
        """セッション中に呼ばれる唯一の出題エントリポイント。
        1. 現在の mastery バンドの未使用問題があればそれを出す
        2. なければ、期限切れの復習問題を出す（バンド不問）
        3. どちらも無ければ None（呼び出し側は在庫切れとして扱う＝
           理想的には pre_generate.py が事前に埋めておくべき状態）
        """
        band = mastery_to_band(mastery)
        item = self.pick_new_item(concept_id, band)
        if item is not None:
            return item
        return self.next_due_item(concept_id)

    def record_result(self, item_id: str, is_correct: bool, confidence: int) -> Optional[Scenario]:
        """回答結果を反映し、SM-2 スケジュールを更新して保存する。"""
        item = next((it for it in self._items if it.item_id == item_id), None)
        if item is None:
            return None
        sm2_update(item, is_correct=is_correct, confidence=confidence)
        self.save()
        return item

    def all_for_concept(self, concept_id: str) -> List[Scenario]:
        return [it for it in self._items if it.concept_id == concept_id]

    def __len__(self) -> int:
        return len(self._items)
