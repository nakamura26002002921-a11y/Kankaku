# infra/prompt_manager.py
"""
prompts/ ディレクトリの .txt テンプレートを読み込み、変数を注入してレンダリングする。

標準ライブラリの `string.Template` を採用（外部依存を増やさないため）。
テンプレート中の変数は `${variable_name}` 形式で記述する。
テンプレートファイル名の "拡張子抜きの部分" が prompt_version の既定値になる
（例: scenario_gen.txt -> "scenario_gen"）。ファイル先頭に
`# version: v2` のようなコメント行があればそちらを優先する。
"""

from __future__ import annotations

from pathlib import Path
from string import Template
from typing import Any, Dict


class PromptNotFoundError(FileNotFoundError):
    pass


class PromptManager:
    def __init__(self, prompts_dir: str | Path = "prompts"):
        self.prompts_dir = Path(prompts_dir)
        self._cache: Dict[str, str] = {}

    def _read_raw(self, name: str) -> str:
        """name はファイル名（拡張子省略可）。例: 'scenario_gen'"""
        if name in self._cache:
            return self._cache[name]

        filename = name if name.endswith(".txt") else f"{name}.txt"
        path = self.prompts_dir / filename
        if not path.exists():
            raise PromptNotFoundError(f"プロンプトテンプレートが見つかりません: {path}")

        text = path.read_text(encoding="utf-8")
        self._cache[name] = text
        return text

    def get_version(self, name: str) -> str:
        """テンプレート先頭の `# version: vX` コメントからバージョンを抽出。
        無ければファイル名自体をバージョン識別子として使う。
        """
        raw = self._read_raw(name)
        first_line = raw.splitlines()[0].strip() if raw.splitlines() else ""
        if first_line.startswith("# version:"):
            return first_line.split(":", 1)[1].strip()
        return name

    def render(self, name: str, **variables: Any) -> str:
        """テンプレートを読み込み、${var} を variables で置換してレンダリングする。

        未使用の余剰変数があっても無視し（safe_substitute）、
        テンプレート側にキーが足りない変数がある場合は ${var} のまま残す
        （呼び出し側でのバリデーション漏れに気づきやすくするため）。
        """
        raw = self._read_raw(name)
        # バージョン宣言コメント行はレンダリング対象から除外する
        lines = raw.splitlines()
        if lines and lines[0].strip().startswith("# version:"):
            raw = "\n".join(lines[1:])

        template = Template(raw)
        rendered = template.safe_substitute(**variables)
        return rendered.strip()

    def clear_cache(self) -> None:
        self._cache.clear()
