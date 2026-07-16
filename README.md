# 🧬 LatentSense

**認知科学に基づいた適応型学習システム**

LatentSense は、大規模言語モデル（LLM）と間隔反復（Spaced Repetition）アルゴリズムを組み合わせ、学習者の「メタ認知（自信度と正答率のギャップ）」を校正しながら、最適な難度で知識の定着を促す学習プラットフォームです。

## ✨ 主な特徴

- **🧠 適応的スキャフォールディング**: 学習者の習熟度（Mastery）に応じて、LLM が生成する問題の「文脈の曖昧さ」や「選択肢の類似度」を動的に調整します。
- **⚡ 高速な Web UI (Tailscale 分散対応)**: 重い LLM 推論はデスクトップ PC 側で行い、軽量な Web UI (Streamlit) はラップトップで実行する分散アーキテクチャを採用。Tailscale を介したローカルネットワーク接続に対応しています。
- **📦 オフライン問題バンク (Item Bank)**: 学習セッション中は原則 LLM を呼ばず、事前に生成・保存された `item_bank.json` から出題するため、体感レイテンシがほぼゼロです。
- **🔄 間隔反復 (SM-2 簡易版)**: 正答率と自信度に基づいて次回の出題タイミングを自動スケジューリングし、長期記憶への定着を最適化します。
- **🛡️ 堅牢なプロンプト管理**: プロンプトをコードから完全に分離（`prompts/`）し、バージョン管理と微調整を容易にしています。

---

## 📁 ディレクトリ構成

```text
latentsense/
├── main.py                     # PsychoPy 版 UI のエントリーポイント（実験室向け）
├── main_web.py                 # Streamlit Web UI のエントリーポイント（Tailscale分散構成向け）
├── config.yaml                 # 全体設定（環境変数展開対応）
├── requirements.txt
│
├── core/                       # 【純粋なロジック】外部依存なし
│   ├── models.py               # Pydantic v2 による厳密なデータ定義
│   ├── mastery.py              # 習熟度計算・SM-2 間隔反復スケジューラ
│   └── item_bank.py            # 問題バンクの管理（検索・再利用・保存）
│
├── infra/                      # 【インフラ】外部システムとの接点
│   ├── llm_client.py           # Ollama API 呼び出し & Pydantic バリデーション & フォールバック
│   ├── prompt_manager.py       # prompts/ ディレクトリからのテンプレート読み込み
│   └── data_logger.py          # 試行ログ (CSV) の追記
│
├── ui/
│   ├── streamlit_view.py       # Streamlit 専用の描画・入力・RT計測ロジック
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
    ├── default_scenarios.json  # LLM 失敗時のフォールバック用データ
    ├── user_state.json         # 習熟度・ブラインドスポットの永続化状態
    └── logs/                   # 被験者ごとの試行ログ (CSV)
```

---

## 🚀 セットアップ

本システムは **LLM サーバー（デスクトップ PC）** と **Web UI クライアント（ラップトップ）** の 2 台構成を想定しています。両方のマシンに [Tailscale](https://tailscale.com/) をインストールし、同じ tailnet に接続しておいてください。

### 1. 前提条件
- Python 3.10 以上
- [Ollama](https://ollama.com/)（デスクトップ PC のみ）
- [Tailscale](https://tailscale.com/)（両方のマシン）

### 2. デスクトップ側（LLM Server）の設定

```bash
# モデルを取得（config.yaml の llm.model と名前を一致させること）
ollama pull qwen2.5

# Tailscale 経由でのアクセスを許可するため、全インターフェースで待受させる
# Linux / macOS
export OLLAMA_HOST=0.0.0.0
ollama serve

# Windows の場合はシステム環境変数に OLLAMA_HOST=0.0.0.0 を追加し、Ollamaアプリを再起動
```

Tailscale IP を確認します。

```bash
tailscale ip -4
# 例: 100.101.102.103
```

ファイアウォールでポート `11434` が Tailscale インターフェースからアクセス可能になっているか確認してください（`tailscale status` で相互到達も確認）。

### 3. ラップトップ側（Web UI Client）の設定

```bash
git clone https://github.com/nakamura26002002921-a11y/Kankaku.git
cd Kankaku/latentsense        # config.yaml と同じ階層に移動すること（後述の注意点を参照）
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

**接続テスト**: ラップトップからデスクトップの Ollama に到達できるか確認します。

```bash
curl http://<DESKTOP_IP>:11434/api/tags
# {"models":[...]} のようなJSONが返れば成功
```

---

## 💻 使い方

### ステップ 1: オフライン事前生成（推奨）

学習セッション中のレイテンシをゼロにするため、事前に問題バンクを構築しておきます。

```bash
export OLLAMA_BASE_URL="http://<DESKTOP_IP>:11434"

# 概念 'ru_motion_verbs' の在庫を、各難度バンドで target_stock 件まで補充する
python scripts/pre_generate.py --concept-id ru_motion_verbs --target-stock 20

# 全概念・全難度バンドを均等に埋めたい場合（夜間バッチ向け）
python scripts/pre_generate.py --all-bands --target-stock 15

# 何件不足しているかだけ確認したい場合（LLMは呼ばない）
python scripts/pre_generate.py --dry-run
```

生成された問題は `data/item_bank.json` に保存され、次回以降の学習で再利用されます。

### ステップ 2: Web アプリの起動

```bash
export OLLAMA_BASE_URL="http://<DESKTOP_IP>:11434"
streamlit run main_web.py
```

ブラウザで `http://localhost:8501` を開くと学習が始められます。

> `OLLAMA_BASE_URL` を設定しなくても起動はできますが、その場合 `config.yaml` の `session.allow_online_fallback` / `use_llm_feedback` が `false`（既定値）である限りローカルの `item_bank.json` だけで完結するため、LLMサーバーへの接続は発生しません。事前生成をまだ行っていない概念に当たったときのみ在庫切れ警告が出ます。

---

## ⚙️ 設定ファイル (`config.yaml`) の解説

`llm.base_url` は `${OLLAMA_BASE_URL:-http://localhost:11434}` という bash ライクな記法で書かれており、`main_web.py` / `scripts/pre_generate.py` の双方が起動時に正規表現ベースの展開処理（`${VAR:-default}` にも対応）を通してから YAML をパースします。環境変数 `OLLAMA_BASE_URL` が未設定の場合は自動的に `http://localhost:11434` にフォールバックします。

```yaml
llm:
  model: "qwen2.5"
  base_url: "${OLLAMA_BASE_URL:-http://localhost:11434}"
  timeout_seconds: 60
  max_retries: 2

item_bank:
  target_stock_per_band: 20   # 各 (concept_id, difficulty_band) の目標ストック数

session:
  default_iterations: 5
  fullscreen: false
  allow_online_fallback: false   # 在庫切れ時のみ緊急でリモートLLM生成を許可するか
  use_llm_feedback: false        # フィードバックをLLM生成にするか（false=規則ベース、ローカル完結）

seed_concepts:                   # user_state.json が無い/空の場合の初期概念
  - id: "ru_motion_verbs"
    domain: "language"
    name: "ロシア語：接頭辞による移動動詞の局面変化"
    current_mastery: 0.4
  - id: "en_articles"
    domain: "language"
    name: "英語：冠詞 (a/the/無冠詞) の使い分け"
    current_mastery: 0.3
```

ログ出力先（`data/logs/`）や `default_scenarios.json` のパスは `config.yaml` ではなく、`main_web.py` / `pre_generate.py` それぞれの環境変数（`LATENTSENSE_LOGS_DIR`、`LATENTSENSE_DEFAULT_SCENARIOS` など）または `--item-bank` / `--user-state` 等の CLI 引数で指定します。

---

## 🔍 トラブルシューティング

- **「学習対象の概念がありません」と表示される**:
  `streamlit run main_web.py` を **`latentsense/` ディレクトリの直下**（`config.yaml` と同じ場所）で実行しているか確認してください。作業ディレクトリが違うと `config.yaml` が見つからず `seed_concepts` を読み込めません。この場合エラー画面に解決済みのパスと現在のカレントディレクトリが表示されるので、それを手がかりに修正してください。
  また、過去に空の `data/user_state.json` が作成されてしまっている場合は削除してから再起動してください。
- **`404 Client Error: Not Found`**: `config.yaml` の `llm.model` が、デスクトップ側で `ollama list` した際のモデル名と完全に一致しているか確認してください。
- **接続タイムアウト**: デスクトップ側のファイアウォールが `11434` をブロックしていないか、`OLLAMA_HOST=0.0.0.0` が正しく設定されているか確認してください。`curl http://<DESKTOP_IP>:11434/api/tags` での到達確認が最も確実です。
- **在庫切れによる応答遅延**: `item_bank.json` に該当 concept/band の問題が無い場合、`session.allow_online_fallback: true` のときのみ緊急でリモートLLM生成が行われるため応答が遅くなります。事前に `pre_generate.py` で在庫を確保しておくことを推奨します（既定 `false` の場合は在庫切れ時にエラーメッセージが表示されます）。

---

## 📜 ライセンス

このプロジェクトは [MIT License](LICENSE) のもとで公開されています。
