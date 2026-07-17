# 🧬 LatentSense

**認知科学に基づいた適応型学習システム**

LatentSense は、大規模言語モデル（LLM）と間隔反復（Spaced Repetition）・インターリービング（交互学習）を組み合わせ、学習者の「メタ認知（自信度と正答率のギャップ）」を校正しながら、最適な難度・タイミングで知識の定着を促す学習プラットフォームです。

## ✨ 主な特徴

- **🧠 適応的スキャフォールディング**: 学習者の習熟度（Mastery）に応じて、LLM が生成する問題の「文脈の曖昧さ」や「選択肢の類似度」を動的に調整します。
- **⚡ 高速な Web UI (Tailscale 分散対応)**: 重い LLM 推論はデスクトップ PC 側で行い、軽量な Web UI (Streamlit) はラップトップで実行する分散アーキテクチャを採用。
- **📦 オフライン問題バンク (Item Bank)**: 学習セッション中は原則 LLM を呼ばず、事前に生成・保存された `item_bank.json` から出題するため、体感レイテンシがほぼゼロです。
- **🔄 間隔反復 (SRS)**: 問題ごとのSM-2簡易版（`core/mastery.py`）に加え、概念そのものの復習タイミングを管理する `schedule/SRS.py` を搭載。正解＆高確信のたびに復習間隔を拡大（初回1日→以降2.5倍）し、不正解・低確信では1日にリセットします。すべて `config.yaml` の `srs:` セクションで調整可能です。
- **🔀 インターリービング（交互学習）**: `schedule/interleaving.py` が出題概念を選定。基本は弱点（ブラインドスポット）や低習熟度の概念を優先しつつ、設定された確率（既定20%）で習熟済み概念（mastery >= 0.8）をランダムに混ぜ込み、忘却を防ぎます。`config.yaml` の `interleaving:` セクションで確率や閾値を調整できます。
- **⏱️ 正確な反応時間計測**: 「A/Bの選択肢ボタンを押した瞬間」を反応時間として記録します（確信度の選定に要した時間は含みません）。
- **🔍 フィードバック時の問題文再表示**: 正誤判定やAIの解説を見る際、どの問題に対する結果かが一目で分かるよう、状況文と選択肢（選んだ方・正解をハイライト）を再表示します。
- **🚩 問題品質の報告機能**: LLM生成の品質不良（言語混在・文章破損など）を発見した際、その場で報告してスキップできます。報告された問題は在庫から取り除かれ、次回の事前生成実行時に自動的に代わりが補充されます。
- **🛡️ 堅牢なプロンプト管理**: プロンプトをコードから完全に分離（`prompts/`）し、バージョン管理と微調整を容易にしています。

---

## 📁 ディレクトリ構成

```text
latentsense/
├── main.py                     # PsychoPy 版 UI のエントリーポイント（実験室向け）
├── main_web.py                 # Streamlit Web UI のエントリーポイント（Tailscale分散構成向け）
├── config.yaml                 # 全体設定（環境変数展開・SRS・インターリービング対応）
├── requirements.txt
│
├── core/                       # 【純粋なロジック】外部依存なし
│   ├── models.py               # Pydantic v2 による厳密なデータ定義（Concept に SRS 用フィールドを追加）
│   ├── mastery.py              # 習熟度計算・問題(Scenario)単位のSM-2間隔反復
│   └── item_bank.py            # 問題バンクの管理（検索・再利用・保存・品質報告の退避）
│
├── schedule/                   # 【出題スケジューリング】core/ と同じく外部依存なしの純粋ロジック層
│   ├── SRS.py                  # 概念(Concept)単位の間隔反復（次回復習日の計算・更新）
│   └── interleaving.py         # 出題概念の選定（弱点優先＋一定確率で習熟済み概念を混ぜ込み）
│
├── infra/                      # 【インフラ】外部システムとの接点
│   ├── llm_client.py           # Ollama API 呼び出し & Pydantic バリデーション & フォールバック
│   ├── prompt_manager.py       # prompts/ ディレクトリからのテンプレート読み込み
│   └── data_logger.py          # 試行ログ (CSV) の追記
│
├── ui/
│   ├── streamlit_view.py       # Streamlit 専用の描画・入力・正確なRT計測・品質報告UI・フィードバック時の問題再表示
│   └── psychopy_view.py        # PsychoPy 専用の描画・キー入力・RT計測ロジック
│
├── prompts/                    # 【分離】LLM への指示書（コードから独立）
│   ├── scenario_gen.txt        # シナリオ生成用プロンプト（${mastery} / ${difficulty_band} 対応）
│   └── feedback_gen.txt        # フィードバック生成用プロンプト
│
├── scripts/
│   └── pre_generate.py         # オフライン事前生成 CLI（GUI 非依存、argparse対応）
│
└── data/                       # 実行時に自動生成（.gitignore 対象）
    ├── item_bank.json          # 生成済み問題のバンク（資産）
    ├── flagged_items.json      # 「この問題はおかしい」で報告された問題のアーカイブ
    ├── default_scenarios.json  # LLM 失敗時のフォールバック用データ
    ├── user_state.json         # 習熟度・SRSスケジュール・ブラインドスポットの永続化状態
    └── logs/                   # 被験者ごとの試行ログ (CSV)
```

### アーキテクチャ上のポイント: `schedule/` によるロジックの分離

出題スケジューリングに関する判断は、`core/` からさらに切り出して `schedule/` に集約しています。

- `core/mastery.py` の SM-2 は「**個々の問題(Scenario)**」の再出題間隔を管理する、細かい粒度のロジックです。
- `schedule/SRS.py` は「**概念(Concept)そのもの**」を次にいつ復習すべきかを管理する、粗い粒度のロジックです。
- `schedule/interleaving.py` は、上記2つの状態（弱点・習熟度・SRSの復習期限）を踏まえて「次にどの概念を出題するか」を決定します。

`core/` と同様、`schedule/` も PsychoPy・Streamlit・LLM SDK のいずれにも依存しない純粋な関数群として実装されているため、`main.py`（PsychoPy版）・`main_web.py`（Streamlit版）の両方から同じロジックを呼び出せます。

---

## 🚀 セットアップ

本システムは **LLM サーバー（デスクトップ PC）** と **Web UI クライアント（ラップトップ）** の 2 台構成を想定しています。両方のマシンに [Tailscale](https://tailscale.com/) をインストールし、同じ tailnet に接続しておいてください。

### 1. 前提条件
- Python 3.10 以上
- [Ollama](https://ollama.com/)（デスクトップ PC のみ）
- [Tailscale](https://tailscale.com/)（両方のマシン）

### 2. デスクトップ側（LLM Server）の設定

```bash
ollama pull qwen2.5

# Linux / macOS
export OLLAMA_HOST=0.0.0.0
ollama serve

# Windows の場合はシステム環境変数に OLLAMA_HOST=0.0.0.0 を追加し、Ollamaアプリを再起動
```

```bash
tailscale ip -4
# 例: 100.101.102.103
```

ファイアウォールでポート `11434` が Tailscale インターフェースからアクセス可能になっているか確認してください（`tailscale status` で相互到達も確認）。

### 3. ラップトップ側（Web UI Client）の設定

```bash
git clone https://github.com/nakamura26002002921-a11y/Kankaku.git
cd Kankaku/latentsense
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

**接続テスト**:

```bash
curl http://<DESKTOP_IP>:11434/api/tags
# {"models":[...]} のようなJSONが返れば成功
```

### 4. `config.yaml` の編集

学習内容や挙動は `config.yaml` を直接編集して調整します。最低限、`seed_concepts`（学習したい概念）を自分用に書き換えてください。

```yaml
seed_concepts:
  - id: "my_topic"
    domain: "language"
    name: "自分が学習したい概念の名前"
    current_mastery: 0.3   # 0.0〜1.0（初期習熟度の見積もり）
```

SRSやインターリービングの挙動を変えたい場合は、後述の該当セクションを編集してください（未編集でも既定値で動作します）。

---

## 💻 使い方

### ステップ 1: オフライン事前生成（推奨）

```bash
export OLLAMA_BASE_URL="http://<DESKTOP_IP>:11434"

python scripts/pre_generate.py --concept-id ru_motion_verbs --target-stock 20
python scripts/pre_generate.py --all-bands --target-stock 15   # 全概念・全難度バンドを均等に埋める
python scripts/pre_generate.py --dry-run                       # 不足数だけ確認（LLMは呼ばない）
```

### ステップ 2: Web アプリの起動

```bash
export OLLAMA_BASE_URL="http://<DESKTOP_IP>:11434"
streamlit run main_web.py
```

`http://localhost:8501` を開くと学習が始められます。出題される概念は `schedule/interleaving.py` により、弱点優先＋確率的な習熟済み概念の混ぜ込みで自動的に選ばれます。

### ステップ 3: 品質不良の問題を報告する

出題画面の **「⚠️ この問題はおかしい（言語混在・文章破損など）」** を開き、不備の種類を選んで報告できます。報告された問題は `item_bank.json` から取り除かれ `data/flagged_items.json` に退避、次回 `pre_generate.py` 実行時に自動補充されます。習熟度や試行ログには影響しません。

---

## ⚙️ 設定ファイル (`config.yaml`) の解説

```yaml
llm:
  model: "qwen2.5"
  base_url: "${OLLAMA_BASE_URL:-http://localhost:11434}"   # ${VAR:-default} 記法対応
  timeout_seconds: 60
  max_retries: 2

item_bank:
  target_stock_per_band: 20   # 各 (concept_id, difficulty_band) の目標ストック数

# 概念レベルの間隔反復 (schedule/SRS.py)
srs:
  base_interval_days: 1.0     # 初回の復習間隔（日）
  growth_factor: 2.5          # 正解&高確信のたびに間隔を掛け合わせる倍率
  confidence_threshold: 4     # これ以上を「高確信」とみなす閾値 (1-5)

# インターリービング（混ぜ込み学習）による出題概念選定 (schedule/interleaving.py)
interleaving:
  probability: 0.2                # 習熟済み概念をランダムに混ぜ込む確率
  high_mastery_threshold: 0.8     # 「習熟済み」とみなす mastery の閾値
  prefer_due_only: false          # true にすると、SRSの復習期限が来ている概念のみを優先候補にする

session:
  default_iterations: 5
  fullscreen: false
  allow_online_fallback: false   # 在庫切れ時のみ緊急でリモートLLM生成を許可するか
  use_llm_feedback: false        # フィードバックをLLM生成にするか（false=規則ベース、ローカル完結）

seed_concepts:
  - id: "ru_motion_verbs"
    domain: "language"
    name: "ロシア語：接頭辞による移動動詞の局面変化"
    current_mastery: 0.4
  - id: "en_articles"
    domain: "language"
    name: "英語：冠詞 (a/the/無冠詞) の使い分け"
    current_mastery: 0.3
```

---

## 🔍 トラブルシューティング

- **「学習対象の概念がありません」と表示される**: `streamlit run main_web.py` を **`latentsense/` ディレクトリの直下**（`config.yaml` と同じ場所）で実行しているか確認してください。エラー画面の「🔄 状態を再読込する」ボタンで、サーバー再起動なしに `data/user_state.json` を再読込できます。
- **`404 Client Error: Not Found`**: `config.yaml` の `llm.model` が、デスクトップ側の `ollama list` の名前と完全に一致しているか確認してください。
- **接続タイムアウト**: `OLLAMA_HOST=0.0.0.0` の設定とファイアウォールを確認し、`curl http://<DESKTOP_IP>:11434/api/tags` で到達確認してください。
- **在庫切れによる応答遅延**: `session.allow_online_fallback: true` のときのみ緊急生成が走ります。事前に `pre_generate.py` で在庫を確保してください。
- **同じ概念ばかり出題される / 全然出ない**: `interleaving.probability` や `high_mastery_threshold` を調整してください。弱点(blind_spots)が多いと、そちらが優先され続けます。
- **品質不良の問題が繰り返し出る**: `data/flagged_items.json` を確認し、`prompts/scenario_gen.txt` の見直しや `llm.model` の変更を検討してください。

---

## 📜 ライセンス

このプロジェクトは [MIT License](LICENSE) のもとで公開されています。
