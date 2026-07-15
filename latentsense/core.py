# latentsense/core.py

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Literal


# ==========================================
# 1. データ構造の定義
# ==========================================

@dataclass
class Concept:
    """学習対象の概念"""
    id: str
    domain: str
    name: str
    current_mastery: float  # 0.0 ~ 1.0

@dataclass
class Primitive:
    """学習プリミティブ (遺伝子)"""
    id: str  # e.g., "interleaving", "generation_effect", "metacognition"
    params: Dict[str, Any] = field(default_factory=dict)

@dataclass
class Strategy:
    """AIが動的に組み立てた学習戦略"""
    primitives: List[Primitive]
    hypothesis: str

@dataclass
class Scenario:
    """LLMが生成したA/Bシナリオ"""
    situation: str
    option_a: str
    option_b: str
    correct_answer: Literal["A", "B"]
    hidden_expert_eye: str

@dataclass
class UserResponse:
    """ユーザーの回答とメタ認知データ"""
    choice: Literal["A", "B"]
    confidence: int  # 1 ~ 5
    reaction_time_ms: int

@dataclass
class Feedback:
    """LLMが生成するフィードバック"""
    is_correct: bool
    confidence_gap_analysis: str
    discrimination_metaphor: str
    updated_mastery_delta: float

@dataclass
class UserState:
    """ユーザーの認知状態モデル"""
    blind_spots: List[str] = field(default_factory=list)  # 誤った確信を持つ概念ID
    concept_history: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)


# ==========================================
# 2. 各モジュールの具現化・改善実装
# ==========================================

class UserModelManager:
    """ユーザーの認知状態を管理・更新するモジュール"""
    
    def get_target_concept(self, state: UserState, available_concepts: List[Concept]) -> Concept:
        """苦手分野（ブラインドスポット）や習熟度が低い概念を優先的に選定する"""
        if not available_concepts:
            raise ValueError("利用可能な概念リストが空です。")
            
        # 1. ブラインドスポット（自信満々で間違えた）にある概念を最優先
        for concept_id in state.blind_spots:
            target = next((c for c in available_concepts if c.id == concept_id), None)
            if target:
                return target
                
        # 2. それ以外は習熟度（current_mastery）が最も低いものを選択
        return min(available_concepts, key=lambda c: c.current_mastery)

    def update_state(self, state: UserState, concept: Concept, response: UserResponse, feedback: Feedback) -> UserState:
        """応答結果から認知状態のバグ（自信過剰バイアスなど）を検出して状態を更新"""
        concept_id = concept.id
        
        if concept_id not in state.concept_history:
            state.concept_history[concept_id] = []
            
        # 履歴の保存
        state.concept_history[concept_id].append({
            "response": response.__dict__,
            "feedback": feedback.__dict__,
            "timestamp": time.time()
        })
        
        # 習熟度の更新（簡易反映）
        concept.current_mastery = max(0.0, min(1.0, concept.current_mastery + feedback.updated_mastery_delta))

        # 【改善ロジック】認知ギャップの検出: 自信度が高く(4以上)かつ不正解の場合、ブラインドスポットに認定
        if not feedback.is_correct and response.confidence >= 4:
            if concept_id not in state.blind_spots:
                state.blind_spots.append(concept_id)
        # 正解かつ高確信度ならブラインドスポットから解除
        elif feedback.is_correct and response.confidence >= 4:
            if concept_id in state.blind_spots:
                state.blind_spots.remove(concept_id)
                
        return state


class StrategyComposer:
    """学習プリミティブを組み合わせるAI Scientistモジュール"""
    
    def compose(self, concept: Concept, state: UserState) -> Strategy:
        """ユーザーの認知状態に合わせた最適な認知工学アプローチをブレンドする"""
        primitives = []
        
        # ユーザーが該当概念でブラインドスポット（誤った固着）に陥っている場合
        if concept.id in state.blind_spots:
            hypothesis = f"【自信過剰バイアスの破壊】{concept.name}に対する誤った直感を揺さぶるため、強烈な判別学習とメタ認知モニタリングをブレンド。"
            primitives.append(Primitive(id="discrimination_learning", params={"difficulty_bias": "high"}))
            primitives.append(Primitive(id="metacognitive_monitoring"))
        else:
            hypothesis = f"【直感の結晶化】標準的な習熟度向上を目指し、間隔反復の文脈と生成エフェクトを適用。"
            primitives.append(Primitive(id="generation_effect"))
            primitives.append(Primitive(id="spaced_repetition"))
            
        return Strategy(primitives=primitives, hypothesis=hypothesis)


class ScenarioGenerator:
    """A/Bシナリオを生成するLLMインターフェース (PoC用擬似実装)"""
    
    def generate(self, concept: Concept, strategy: Strategy) -> Scenario:
        """
        実際の実装では、ここでLLM（OllamaやOpenAI）に構築したプロンプトを投げ、
        JSON形式でパースして返却します。
        """
        # プロンプトの組み立てイメージ
        primitive_ids = [p.id for p in strategy.primitives]
        prompt = f"""
        ターゲット概念: {concept.name}
        適用する認知工学戦略: {primitive_ids}
        仮説: {strategy.hypothesis}
        上記に基づいて、ネイティブの直感を揺さぶるA/Bテストのシチュエーションを1つ作成してください。
        """
        
        # ここではロシア語の移動動詞（пойти / поехать）を想定したダミーデータを返却
        return Scenario(
            situation="友人と電話中、明日急に雨が降らなければ、新しくできた郊外のショッピングモールへ『行く』と伝える局面。",
            option_a="Я пойду в торговый центр. (歩いて行くニュアンス)",
            option_b="Я поеду в торговый центр. (乗り物で行くニュアンス)",
            correct_answer="B",
            hidden_expert_eye="郊外のモールという『距離感』と、天候の不確定要素がある場合、ネイティブは無意識に乗り物での移動（поехать）の局面として脳内処理します。"
        )


class InteractionInterface:
    """ユーザーインターフェース (CLI/Streamlitの仲介)"""
    
    def present_and_get_response(self, scenario: Scenario) -> UserResponse:
        """画面またはコンソールに提示し、System 1（直感）を測定するために回答時間を計る"""
        print(f"\n📖 【局面】\n{scenario.situation}")
        print(f"[A] {scenario.option_a}")
        print(f"[B] {scenario.option_b}")
        
        start_time = time.time()
        
        # 本来はUIでボタンタップさせるが、ここではCLI入力
        choice = ""
        while choice not in ["A", "B"]:
            choice = input("👉 直感で選べ！ (A / B): ").strip().upper()
            
        end_time = time.time()
        reaction_time_ms = int((end_time - start_time) * 1000)
        
        confidence = 0
        while confidence not in range(1, 6):
            try:
                confidence = int(input("🧠 自分の選択への確信度は？ (1:当てずっぽう ~ 5:絶対の自信): "))
            except ValueError:
                continue
                
        return UserResponse(
            choice=choice, # type: ignore
            confidence=confidence,
            reaction_time_ms=reaction_time_ms
        )


class FeedbackGenerator:
    """評価およびフィードバックを行うLLMインターフェース"""
    
    def evaluate(self, scenario: Scenario, response: UserResponse, strategy: Strategy) -> Feedback:
        is_correct = (response.choice == scenario.correct_answer)
        
        # 認知ギャップ分析のロジック化
        if is_correct:
            if response.confidence >= 4:
                gap_analysis = "【直感の完全同調】正しい認知パターンが素早く呼び出されています。"
                mastery_delta = 0.1
            else:
                gap_analysis = "【偶然の正解 / 直感の未成熟】正解ですが、まだ『感覚』として定着していません。"
                mastery_delta = 0.05
        else:
            if response.confidence >= 4:
                gap_analysis = "【自信過剰バイアスの発生】誤った認知パターンが強力に固着しています！脳の書き換えが必要です。"
                mastery_delta = -0.15
            else:
                gap_analysis = "【純粋な知識不足】正しいパターンがまだインプットされていません。"
                mastery_delta = -0.05
                
        return Feedback(
            is_correct=is_correct,
            confidence_gap_analysis=gap_analysis,
            discrimination_metaphor=f"プロの眼点: {scenario.hidden_expert_eye}",
            updated_mastery_delta=mastery_delta
        )


# ==========================================
# 3. 全体の制御フロー (オーケストレーター)
# ==========================================

class LatentSenseOS:
    def __init__(self, concepts: List[Concept]):
        self.user_model = UserModelManager()
        self.composer = StrategyComposer()
        self.generator = ScenarioGenerator()
        self.ui = InteractionInterface()
        self.evaluator = FeedbackGenerator()
        
        self.concepts = concepts
        self.state = UserState()

    def run_session(self, num_iterations: int = 3):
        print("🧠 =========================================")
        print("🧠 LatentSense OS: Cognitive Boot Sequence...")
        print("🧠 =========================================\n")
        
        for i in range(num_iterations):
            print(f"\n🔄 --- 認知変革ループ [Iteration {i+1}/{num_iterations}] ---")
            
            # 1. 概念選定
            concept = self.user_model.get_target_concept(self.state, self.concepts)
            print(f"🎯 フォーカス概念: {concept.name} (現在の脳内マスター度: {concept.current_mastery:.2f})")

            # 2. 戦略コンポーズ
            strategy = self.composer.compose(concept, self.state)
            print(f"🧬 動的生成戦略: {[p.id for p in strategy.primitives]}")
            print(f"🔬 認知仮説: {strategy.hypothesis}")

            # 3. シナリオ生成
            scenario = self.generator.generate(concept, strategy)

            # 4. ユーザー対話 (回答と応答速度計測)
            response = self.ui.present_and_get_response(scenario)
            print(f"⏱️ 応答速度: {response.reaction_time_ms} ms (System 1 閾値チェック)")

            # 5. 評価 & 認知デバッグ
            feedback = self.evaluator.evaluate(scenario, response, strategy)
            
            print("\n============ 💡 脳内デバッグ結果 ============")
            if feedback.is_correct:
                print("🟢 RESULT: SUCCESS")
            else:
                print("🔴 RESULT: PREDICTION ERROR (予測誤差発火)")
            print(f"🔍 診断: {feedback.confidence_gap_analysis}")
            print(f"🔮 {feedback.discrimination_metaphor}")
            print("=============================================\n")

            # 6. 状態更新
            self.state = self.user_model.update_state(self.state, concept, response, feedback)
            
            # ブラインドスポットの可視化
            if self.state.blind_spots:
                print(f"⚠️ 現在の脳内バグ（要矯正概念）: {self.state.blind_spots}")
            
            time.sleep(1)

        print("\n✅ セッション終了。あなたの認知モデルは正常に更新され、バックプロパゲーションが完了しました。")


# ==========================================
# 4. テスト実行
# ==========================================
if __name__ == "__main__":
    # 初期シードデータ（ロシア語の移動動詞の例）
    init_concepts = [
        Concept(id="ru_motion_verbs", domain="language", name="ロシア語：接頭辞による移動動詞の局面変化", current_mastery=0.4)
    ]
    
    os_instance = LatentSenseOS(concepts=init_concepts)
    # 実効時はコンソール入力待ちになります
    os_instance.run_session(num_iterations=2)
