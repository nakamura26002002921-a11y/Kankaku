# latentsense/app.py
import sys
from core import LatentSenseOS, Concept, UserResponse
from llm_engine import OllamaClient, LLMScenarioGenerator, LLMFeedbackGenerator
from view import PsychoPyView

def main():
    # 1. 初期化
    view = PsychoPyView(size=(1280, 720), fullscr=False)
    
    # 起動時のローディング表示（モデルロード時間用）
    view.show_loading("🚀 システムを初期化中...")
    
    client = OllamaClient(model="qwen2.5")
    os_instance = LatentSenseOS(concepts=[
        Concept(id="ru_motion_verbs", domain="language", name="ロシア語：移動動詞の直感", current_mastery=0.4)
    ])
    os_instance.generator = LLMScenarioGenerator(client)
    os_instance.evaluator = LLMFeedbackGenerator(client)

    # 2. メインループ
    while True:
        # --- State 1: シナリオ生成 ---
        view.show_loading("🧬 AIが最適な学習戦略を構成中...\nしばらくお待ちください")
        
        concept = os_instance.user_model.get_target_concept(os_instance.state, os_instance.concepts)
        strategy = os_instance.composer.compose(concept, os_instance.state)
        current_scenario = os_instance.generator.generate(concept, strategy)
        current_concept = concept

        # --- State 2: ユーザー回答 ---
        view.show_scenario(
            concept_name=current_concept.name,
            situation=current_scenario.situation,
            option_a=current_scenario.option_a,
            option_b=current_scenario.option_b
        )
        
        # ⚠️ wait_for_choice 内部でタイマーがスタートし、RTが返ってくる
        choice, reaction_time_ms = view.wait_for_choice()
        if choice == 'ESCAPE':
            break
        
        # --- State 3: 自信度入力 ---
        view.show_loading(f"選択: {choice}\n\nあなたの回答に対する「自信度」を教えてください。\n(1:低い 〜 5:高い)")
        confidence = view.wait_for_confidence()
        if confidence == 'ESCAPE':
            break

        # --- State 4: AIフィードバック生成 ---
        view.show_loading("🔍 AIが脳内パターンを分析中...\n(LLM推論中...)")
        
        response = UserResponse(
            choice=choice,
            confidence=confidence,
            reaction_time_ms=reaction_time_ms
        )
        
        feedback = os_instance.evaluator.evaluate(current_scenario, response, strategy)
        os_instance.state = os_instance.user_model.update_state(
            os_instance.state, current_concept, response, feedback
        )

        # --- State 5: フィードバック表示 ---
        view.show_feedback(
            is_correct=feedback.is_correct,
            correct_answer=current_scenario.correct_answer,
            user_choice=choice,
            analysis=feedback.confidence_gap_analysis,
            metaphor=feedback.discrimination_metaphor
        )
        
        cont = view.wait_for_continue()
        if cont == 'ESCAPE':
            break

    # 3. 終了処理
    view.close()
    
if __name__ == "__main__":
    main()
