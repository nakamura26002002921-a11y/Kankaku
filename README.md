# 🧬 LatentSense OS

**認知科学に基づいた適応型学習システム**

LatentSense OS は、大規模言語モデル（LLM）と間隔反復（Spaced Repetition）アルゴリズムを組み合わせ、学習者の「メタ認知（自信度と正答率のギャップ）」を校正しながら、最適な難度で知識の定着を促す学習プラットフォームです。

## ✨ 主な特徴

- **🧠 適応的スキャフォールディング**: 学習者の習熟度（Mastery）に応じて、LLM が生成する問題の「文脈の曖昧さ」や「選択肢の類似度」を動的に調整します。
- **⚡ 高速な Web UI (Tailscale 分散対応)**: 重厚な LLM 推論はデスクトップ PC で行い、軽量な Web UI (Streamlit) はラップトップで実行する分散アーキテクチャを採用。Tailscale を介した安全なローカルネットワーク接続に対応しています。
- **📦 オフライン問題バンク (Item Bank)**: 学習セッション中は LLM への問い合わせを行わず、事前に生成・保存された問題バンクから出題するため、体感レイテンシがゼロです。
- **🔄 間隔反復 (SM-2)**: 正答率と反応時間に基づいて次回の出題タイミングを自動スケジューリングし、長期記憶への定着を最適化します。
- **🛡️ 堅牢なプロンプト管理**: プロンプトをコードから完全に分離（`prompts/`）し、バージョン管理と微調整を容易にしています。

---

## 📁 ディレクトリ構成

```text
Kankaku/
├── main_web.py                 # Streamlit Web UI のエントリーポイント
├── config.yaml                 # 全体設定 (環境変数展開対応)
│
├── core/                       # 【純粋なロジック】外部依存なし
│   ├── models.py               # Pydantic v2 による厳密なデータ定義
│   ├── mastery.py              # 習熟度計算・SM-2 間隔反復スケジューラ
│   └── item_bank.py            # 問題バンクの管理（検索・再利用・保存）
│
├── infra/                      # 【インフラ】外部システムとの接点
│   ├── llm_client.py           # Ollama API 呼び出し & JSON バリデーション
│   ├── prompt_manager.py       # prompts/ ディレクトリからのテンプレート読み込み
│   └── data_logger.py          # 試行ログ (CSV) の追記
│
├── ui/                         # 【UI】Web フロントエンド
│   └── streamlit_view.py       # Streamlit 専用の描画・入力・RT計測ロジック
│
├── prompts/                    # 【分離】LLM への指示書 (コードから独立)
│   ├── scenario_gen.txt        # シナリオ生成用プロンプト (${mastery} 対応)
│   └── feedback_gen.txt        # フィードバック生成用プロンプト
│
├── scripts/                    # 【CLI】バッチ処理スクリプト
│   └── pre_generate.py         # オフライン事前生成コマンド (GUI 非依存)
│
└── data/                       # 実行時に自動生成 (.gitignore 対象)
    ├── item_bank.json          # 生成済み問題のバンク (資産)
    ├── default_scenarios.json  # LLM 失敗時のフォールバック用データ
    └── logs/                   # 被験者ごとの試行ログ (CSV)
```

---

## 🚀 セットアップ

本システムは **LLM サーバー（デスクトップ PC）** と **Web UI クライアント（ラップトップ）** の 2 台構成を想定しています。両方のマシンに [Tailscale](https://tailscale.com/) がインストールされ、同じネットワークに接続されている必要があります。

### 1. 前提条件
- Python 3.10 以上
- [Ollama](https://ollama.com/) (デスクトップ PC のみ)
- [Tailscale](https://tailscale.com/) (両方のマシン)

### 2. デスクトップ側 (LLM Server) の設定
1. Ollama をインストールし、モデルをダウンロードします。
   ```bash
   ollama pull qwen2.5:14b
   ```
2. Tailscale 経由での接続を許可するため、Ollama を外部公開モードで起動します。
   ```bash
   # Linux / macOS の場合
   export OLLAMA_HOST=0.0.0.0
   ollama serve
   
   # Windows の場合
   # システム環境変数に OLLAMA_HOST=0.0.0.0 を追加し、Ollama アプリを再起動
   ```
3. デスクトップの Tailscale IP アドレスを確認します。
   ```bash
   tailscale ip -4
   # 例: 100.101.102.103 が表示される
   ```

### 3. ラップトップ側 (Web UI Client) の設定
1. リポジトリをクローンし、仮想環境を作成します。
   ```bash
   git clone https://github.com/nakamura26002002921-a11y/Kankaku.git
   cd Kankaku
   python -m venv venv
   source venv/bin/activate  # Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```
2. **接続テスト**: ラップトップからデスクトップの Ollama に到達できるか確認します。
   ```bash
   # <DESKTOP_IP> を手順2で確認したIPに置き換えてください
   curl http://<DESKTOP_IP>:11434/api/tags
   # {"models":[...]} のようなJSONが返ってくれば成功です
   ```

---

## 💻 使い方

### ステップ 1: オフライン事前生成 (推奨)
学習セッションをスムーズにするため、事前に問題バンクを構築します。ラップトップ側で以下の環境変数を設定して実行します。

```bash
# デスクトップの Tailscale IP を指定
export OLLAMA_BASE_URL="http://<DESKTOP_IP>:11434"

# 概念 'ru_motion_verbs' に対して、各難度バンドで 20 問ずつ生成
python scripts/pre_generate.py --concept-id ru_motion_verbs --target-stock 20
```
※ 生成された問題は `data/item_bank.json` に保存され、次回以降の学習で再利用されます。

### ステップ 2: Web アプリの起動
同じくラップトップ側で、環境変数を設定したまま Streamlit アプリを起動します。

```bash
export OLLAMA_BASE_URL="http://<DESKTOP_IP>:11434"
streamlit run main_web.py
```
ブラウザで `http://localhost:8501` にアクセスし、学習を開始します。

---

## ⚙️ 設定ファイル (`config.yaml`) の解説

本システムは、環境変数 `OLLAMA_BASE_URL` が設定されていない場合、自動的に `http://localhost:11434` にフォールバックするように設計されています。

```yaml
llm:
  model: "qwen2.5:14b"
  # Python側で ${OLLAMA_BASE_URL:-http://localhost:11434} を展開して使用します
  base_url: "${OLLAMA_BASE_URL:-http://localhost:11434}"
  timeout: 60
  retry_attempts: 2

generation:
  target_stock_per_band: 20
  fallback_file: "data/default_scenarios.json"

logging:
  dir: "data/logs"
```

---

## 🔍 トラブルシューティング

- **`404 Client Error: Not Found`**: `config.yaml` の `model` 名が、デスクトップ側で `ollama list` した際の名前と完全に一致しているか確認してください（例: `qwen2.5` ではなく `qwen2.5:14b`）。
- **接続タイムアウト**: デスクトップ側のファイアウォールが `11434` ポートをブロックしていないか、また `OLLAMA_HOST=0.0.0.0` が正しく設定されているか確認してください。`curl` コマンドでの到達確認が最も確実です。
- **在庫切れによる遅延**: `item_bank.json` に問題が不足している場合、緊急で LLM 生成が行われるため応答が遅くなります。事前に `pre_generate.py` で十分な在庫を確保してください。

---

## 📜 ライセンス

このプロジェクトは [MIT License](LICENSE) のもとで公開されています。
```

