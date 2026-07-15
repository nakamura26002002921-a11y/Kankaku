# latentsense/app.py

import streamlit as st
import time
from core import LatentSenseOS, Concept, UserState
from llm_engine import OllamaClient, LLMScenarioGenerator, LLMFeedbackGenerator

# ==========================================
# 初期化 & セッションステート管理
# ==========================================
def init_session():
    if "os_instance" not in st.session_state:
        # Ollamaクライアントの初期化
        client = OllamaClient(model="qwen2.5") # または llama3.1
        
        # OSインスタンスの作成と、LLMモジュールの注入
        os_instance = LatentSenseOS(concepts=[
            Concept(id="ru_motion_verbs", domain="language", name="ロシア語：移動動詞の直感", current_mastery=0.4)
        ])
        
        # core.pyのダミー実装をLLM実装に置き換え
        os_instance.generator = LLMScenarioGenerator(client)
        os_instance.evaluator = LLMFeedbackGenerator(client)
        
        st.session_state.os_instance = os_instance
        st.session_state.current_scenario = None
        st.session_state.current_concept = None
        st.session_state.feedback = None
        st.session_state.step = "select_concept" # select_concept -> answer -> feedback

def main():
    st.set_page_config(page_title="LatentSense OS", layout="wide")
    init_session()
    
    os_instance: LatentSenseOS = st.session_state.os_instance
    
    st.title("🧠 LatentSense: Cognitive Extension Interface")
    st.markdown("---")
    
    # サイドバー：認知状態の表示
    with st.sidebar:
        st.header("📊 User Model")
        if os_instance.state.blind_spots:
            st.error(f"⚠️ Blind Spots (要矯正): {os_instance.state.blind_spots}")
        else:
            st.success("✅ No critical blind spots detected.")
            
        st.subheader("Concept Mastery")
        for c in os_instance.concepts:
            st.progress(c.current_mastery, text=f"{c.name}: {c.current_mastery:.2f}")

    # ==========================================
    # メインフロー
    # ==========================================
    
    # Step 1: 概念選定 & シナリオ生成
    if st.session_state.step == "select_concept":
        with st.spinner("🧬 AIが最適な学習戦略を構成中..."):
            concept = os_instance.user_model.get_target_concept(os_instance.state, os_instance.concepts)
            strategy = os_instance.composer.compose(concept, os_instance.state)
            scenario = os_instance.generator.generate(concept, strategy)
            
            st.session_state.current_concept = concept
            st.session_state.current_scenario = scenario
            st.session_state.strategy = strategy
            st.session_state.step = "answer"
            st.rerun()

    # Step 2: ユーザー回答
    elif st.session_state.step == "answer":
        scenario = st.session_state.current_scenario
        concept = st.session_state.current_concept
        
        st.subheader(f"🎯 Target: {concept.name}")
        st.info(f"📖 **Situation:** {scenario.situation}")
        
        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"### [ A ]\n{scenario.option_a}")
            choice_a = st.button("Choose A", use_container_width=True, type="primary")
        with col2:
            st.markdown(f"### [ B ]\n{scenario.option_b}")
            choice_b = st.button("Choose B", use_container_width=True, type="primary")
            
        if choice_a or choice_b:
            choice = "A" if choice_a else "B"
            # 簡易的な反応時間計測（本来はJS側で計る）
            reaction_time = 1500 
            
            # 自信度入力
            confidence = st.slider("Confidence Level (1-5)", 1, 5, 3)
            
            if st.button("Submit Answer"):
                from core import UserResponse
                response = UserResponse(
                    choice=choice,
                    confidence=confidence,
                    reaction_time_ms=reaction_time
                )
                
                with st.spinner("🔍 AIが脳内パターンを分析中..."):
                    feedback = os_instance.evaluator.evaluate(scenario, response, st.session_state.strategy)
                    st.session_state.feedback = feedback
                    st.session_state.response = response
                    st.session_state.step = "feedback"
                    st.rerun()

    # Step 3: フィードバック表示 & 状態更新
    elif st.session_state.step == "feedback":
        feedback = st.session_state.feedback
        scenario = st.session_state.current_scenario
        response = st.session_state.response
        
        # 結果表示
        if feedback.is_correct:
            st.success("🟢 CORRECT: Prediction Matched")
        else:
            st.error("🔴 PREDICTION ERROR: Neural Rewiring Required")
            
        st.markdown(f"**Correct Answer:** {scenario.correct_answer} (You chose: {response.choice})")
        st.markdown(f"**🔍 Diagnosis:** {feedback.confidence_gap_analysis}")
        st.markdown(f"**🔮 Expert Metaphor:** {feedback.discrimination_metaphor}")
        
        # 状態更新
        os_instance.state = os_instance.user_model.update_state(
            os_instance.state, 
            st.session_state.current_concept, 
            response, 
            feedback
        )
        
        st.markdown("---")
        if st.button("Next Scenario ➡️", use_container_width=True):
            st.session_state.step = "select_concept"
            st.rerun()

if __name__ == "__main__":
    main()
