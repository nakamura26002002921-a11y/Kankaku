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
├── latentsense/
│   ├── main_web.py             # Streamlit Web UI のエントリーポイント
│   ├── config.yaml             # 全体設定 (LLMモデル, Tailscale IP, 難度閾値等)
│   │
│   ├── core/                   # 【純粋なロジック】外部依存なし
│   │   ├── models.py           # Pydantic v2 による厳密なデータ定義
│   │   ├── mastery.py          # 習熟度計算・SM-2 間隔反復スケジューラ
│   │   └── item_bank.py        # 問題バンクの管理（検索・再利用・保存）
│   │
│   ├── infra/                  # 【インフラ】外部システムとの接点
│   │   ├── llm_client.py       # Ollama API 呼び出し & JSON バリデーション
│   │   ├── prompt_manager.py   # prompts/ ディレクトリからのテンプレート読み込み
│   │   └── data_logger.py      # 試行ログ (CSV) の追記
│   │
│   ├── ui/                     # 【UI】Web フロントエンド
│   │   └── streamlit_view.py   # Streamlit 専用の描画・入力ロジック
│   │
│   ├── prompts/                # 【分離】LLM への指示書 (コードから独立)
│   │   ├── scenario_gen.txt    # シナリオ生成用プロンプト
│   │   └── feedback_gen.txt    # フィードバック生成用プロンプト
│   │
│   └── scripts/                # 【CLI】バッチ処理スクリプト
│       └── pre_generate.py     # オフライン事前生成コマンド (GUI 非依存)
│
├── data/                       # 実行時に自動生成 (.gitignore 対象)
│   ├── item_bank.json          # 生成済み問題のバンク (資産)
│   ├── default_scenarios.json  # LLM 失敗時のフォールバック用データ
│   └── logs/                   # 被験者ごとの試行ログ (CSV)
│
├── requirements.txt            # Python 依存パッケージ
└── README.md
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
   OLLAMA_HOST=0.0.0.0 ollama serve
   
   # Windows の場合 (システム環境変数に OLLAMA_HOST=0.0.0.0 を追加して Ollama を再起動)
   ```
3. デスクトップの Tailscale IP アドレスを確認します。
   ```bash
   tailscale ip
   # 例: 100.x.y.z
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
2. `latentsense/config.yaml` を開き、`base_url` をデスクトップの Tailscale IP に書き換えます。
   ```yaml
   llm:
     model: "qwen2.5:14b"
     base_url: "http://100.x.y.z:11434/api/chat" # ここをデスクトップのIPに変更
   ```

---

## 💻 使い方

### ステップ 1: オフライン事前生成 (推奨)
学習セッションをスムーズにするため、事前に問題バンクを構築します。このスクリプトは LLM を呼び出すため、**デスクトップ PC 側**で実行することを推奨します（ラップトップから実行する場合は、Tailscale 経由で LLM にアクセスできます）。

```bash
# 概念 'ru_motion_verbs' に対して、各難度バンドで 20 問ずつ生成
python latentsense/scripts/pre_generate.py --concept-id ru_motion_verbs --target-stock 20
```
※ 生成された問題は `data/item_bank.json` に保存され、次回以降の学習で再利用されます。

### ステップ 2: Web アプリの起動
ラップトップ側で Streamlit アプリを起動します。

```bash
streamlit run latentsense/main_web.py
```
ブラウザで `http://localhost:8501` にアクセスし、学習を開始します。

---

## ⚙️ 設定ファイル (`config.yaml`) の解説

```yaml
llm:
  model: "qwen2.5:14b"               # 使用する Ollama モデル名
  base_url: "http://100.x.y.z:11434/api/chat" # LLM サーバーの URL (Tailscale IP)
  timeout: 60                        # API タイムアウト (秒)
  retry_attempts: 2                  # 失敗時のリトライ回数

generation:
  target_stock_per_band: 20          # 各難度 (easy/medium/hard) ごとの目標問題数
  fallback_file: "data/default_scenarios.json" # LLM 失敗時のフォールバックデータ

logging:
  dir: "data/logs"                   # 試行ログ (CSV) の保存先
```

---

## 🔍 トラブルシューティング

- **`404 Client Error: Not Found`**: `config.yaml` の `model` 名が、デスクトップ側で `ollama list` した際の名前と完全に一致しているか確認してください（例: `qwen2.5` ではなく `qwen2.5:14b`）。
- **接続タイムアウト**: デスクトップ側のファイアウォールが `11434` ポートをブロックしていないか、また `OLLAMA_HOST=0.0.0.0` が正しく設定されているか確認してください。
- **日本語の文字化け**: Streamlit のフォント設定が環境によって異なる場合があります。必要に応じて `ui/streamlit_view.py` 内でカスタム CSS を適用してください。

---

## 📜 ライセンス

このプロジェクトは [MIT License](LICENSE) のもとで公開されています。

--- 

### 💡 使い方
この Markdown テキストをコピーし、リポジトリの `README.md` ファイルの内容として保存・コミットしてください。Tailscale の IP アドレス部分（`100.x.y.z`）は、実際の環境に合わせて適宜書き換えてご利用ください。
