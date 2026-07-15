# latentsense/llm_engine.py
import requests
import json
import re
from typing import List, Dict, Any

# core.py からデータ構造をインポート
from core import (
    Concept, Strategy, Scenario, UserResponse, Feedback,
    ScenarioGenerator, FeedbackGenerator
)

# ==========================================
# Ollama API クライアント
# ==========================================
class OllamaClient:
    def __init__(self, model: str = "qwen2.5", base_url: str = "http://localhost:11434"):
        self.model = model
        self.base_url = base_url

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        """Ollama APIを叩き、テキストレスポンスを取得する"""
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "stream": False,
            "format": "json" # JSON出力を強制
        }
        
        try:
            response = requests.post(url, json=payload, timeout=60)
            response.raise_for_status()
            return response.json()["message"]["content"]
        except Exception as e:
            print(f"❌ Ollama API Error: {e}")
            return "{}" # エラー時は空のJSONを返す

    def parse_json(self, raw_text: str) -> Dict[str, Any]:
        """LLMの出力からJSONを抽出・パースする（堅牢性重視）"""
        # Markdownのコードブロック除去
        clean_text = re.sub(r"```json|```", "", raw_text).strip()
        try:
            return json.loads(clean_text)
        except json.JSONDecodeError:
            # 最初の { と最後の } だけを抽出するフォールバック
            match = re.search(r"\{.*\}", clean_text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    pass
            return {}

# ==========================================
# LLMシナリオジェネレーター
# ==========================================
class LLMScenarioGenerator(ScenarioGenerator):
    def __init__(self, client: OllamaClient):
        self.client = client

    def generate(self, concept: Concept, strategy: Strategy) -> Scenario:
        system_prompt = """
        You are an expert in cognitive linguistics and domain-specific intuition.
        Generate an A/B intuition test scenario based on the provided concept and strategy.
        Output MUST be valid JSON with the following schema:
        {
            "situation": "Brief context in Japanese",
            "option_a": "Option A text",
            "option_b": "Option B text",
            "correct_answer": "A or B",
            "hidden_expert_eye": "The core intuition or nuance difference in Japanese"
        }
        """
        
        user_prompt = f"""
        Target Concept: {concept.name} (Domain: {concept.domain})
        Strategy: {[p.id for p in strategy.primitives]}
        Hypothesis: {strategy.hypothesis}
        
        Generate 1 scenario.
        """
        
        raw_response = self.client.chat(system_prompt, user_prompt)
        data = self.client.parse_json(raw_response)
        
        # デフォルト値でフォールバック
        return Scenario(
            situation=data.get("situation", "エラー：シナリオ生成に失敗しました"),
            option_a=data.get("option_a", "N/A"),
            option_b=data.get("option_b", "N/A"),
            correct_answer=data.get("correct_answer", "A"),
            hidden_expert_eye=data.get("hidden_expert_eye", "N/A")
        )

# ==========================================
# LLMフィードバックジェネレーター
# ==========================================
class LLMFeedbackGenerator(FeedbackGenerator):
    def __init__(self, client: OllamaClient):
        self.client = client

    def evaluate(self, scenario: Scenario, response: UserResponse, strategy: Strategy) -> Feedback:
        is_correct = (response.choice == scenario.correct_answer)
        
        system_prompt = """
        You are a cognitive coach. Analyze the user's response to an A/B test.
        Output MUST be valid JSON:
        {
            "confidence_gap_analysis": "Diagnosis of user's confidence vs accuracy in Japanese",
            "discrimination_metaphor": "A visual or spatial metaphor explaining the difference in Japanese"
        }
        """
        
        user_prompt = f"""
        Scenario: {scenario.situation}
        Options: A={scenario.option_a} / B={scenario.option_b}
        Correct: {scenario.correct_answer}
        User Choice: {response.choice} (Confidence: {response.confidence}/5)
        Expert Eye: {scenario.hidden_expert_eye}
        
        Is Correct: {is_correct}
        """
        
        raw_response = self.client.chat(system_prompt, user_prompt)
        data = self.client.parse_json(raw_response)
        
        # 習熟度変動値のロジック（core.pyのロジックを流用・拡張）
        mastery_delta = 0.0
        if is_correct:
            mastery_delta = 0.1 if response.confidence >= 4 else 0.05
        else:
            mastery_delta = -0.15 if response.confidence >= 4 else -0.05

        return Feedback(
            is_correct=is_correct,
            confidence_gap_analysis=data.get("confidence_gap_analysis", "分析エラー"),
            discrimination_metaphor=data.get("discrimination_metaphor", scenario.hidden_expert_eye),
            updated_mastery_delta=mastery_delta
        )
