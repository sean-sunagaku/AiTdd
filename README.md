# AiTdd

Codex が計画とレビューを担当し、Cursor が RED / GREEN / REFACTOR の実装を担当する、
小さな TDD オーケストレータです。Hook の入出力と policy は
`codex-hookkit` を使います。
Codex は Python から公式 `@openai/codex-sdk` を呼びます。
Cursor は既定で Python から公式 `@cursor/sdk` の Composer を使い、
必要なら `cursor-agent` CLI に切り替えられます。

## 役割

- Codex: 次に書くべき最小テストの計画、GREEN 後と REFACTOR 後のレビュー、完了判定
- Cursor: テスト追加、最小実装、リファクタリング
- Hook: RED ではテスト失敗を要求し、GREEN / REFACTOR ではテスト成功を要求する

## 使い方

```sh
uv sync --dev
npm install
uv run aitdd run "FizzBuzz を t-wada 流 TDD で作る" --test-command "pytest" --max-cycles 5
```

PyPI から使う場合も、公式 Node SDK は作業ディレクトリに入れてください。

```sh
pip install aitdd
npm install @openai/codex-sdk @cursor/sdk
aitdd run "FizzBuzz を t-wada 流 TDD で作る" --test-command "pytest"
```

Cursor 実装担当は既定で SDK + Composer alias を使います。

```sh
uv run aitdd run "..." --cursor-backend sdk --cursor-model composer-latest
```

CLI fallback を使いたい場合:

```sh
uv run aitdd run "..." --cursor-backend cli --cursor-model composer-latest
```

SDK は `CURSOR_API_KEY` があればそれを使い、無い場合は SDK 側の認証解決に任せます。

実行内容だけ確認する場合:

```sh
uv run aitdd run "TODO アプリの最小モデルを作る" --dry-run
```

複雑なクラスや業務要件では `aitdd.yaml` を使って、反復する TDD サイクルを固定できます。

```sh
uv run aitdd run "ignored when spec exists" \
  --spec examples/aitdd.yaml \
  --test-command "pytest" \
  --max-cycles 5
```

`aitdd.yaml` では次を指定できます。

- `goal`: 全体ゴール
- `public_api`: 育てる public API
- `constraints`: 設計・進め方の制約
- `forbidden`: 先回り実装や禁止事項
- `acceptance_tests`: 外側の受け入れテスト
- `unit_tests`: 内側のユニットテスト
- `cycles`: 1 サイクル 1 public behavior の反復リスト

各 cycle には `expected_red` を置けます。RED では「テストが失敗したか」だけでなく、
期待した理由で失敗したか、禁止した壊れ方をしていないかも検証します。
REFACTOR フェーズではテストファイル変更を拒否します。

Codex レビューは JSON schema で機械判定します。各サイクルで次の gate がすべて `true` の場合だけ
次に進みます。

- `one_behavior_only`
- `minimal_green`
- `tests_unchanged_in_refactor`
- `acceptance_unit_boundary_ok`
- `forbidden_respected`
- `needs_more_tests`
- `missing_test_perspectives`

CLI には cycle ごとの進捗として `red / green / refactor / complete / one_behavior_only /
minimal_green / boundary_ok` が表示されます。

Codex レビューで「まだテスト観点が足りない」と判断した場合、gate は通しつつ
`missing_test_perspectives` に不足観点を返します。AiTdd はそれを `.aitdd/progress.json` の
`test_backlog` に保存し、次の cycle で RED 候補として優先します。これにより、実装中に見つかった
境界値、例外系、責務分離などの観点も、あとからまとめてではなく TDD のリズムのまま追加できます。

実行中の状態は最小構成で次に保存されます。

- `.aitdd/progress.json`: cycle ごとの `behavior`, `red`, `green`, `refactor`, `review_gate`,
  `issues`, `started_at`, `finished_at` と `test_backlog`
- `.aitdd/cycles/001-red.diff`: phase ごとの git diff snapshot
- `.aitdd/report.md`: TDD の進行ログ

途中から再開する場合:

```sh
aitdd resume --spec aitdd.yaml --max-cycles 5
```

Codex hook として使う場合は `.codex/hooks.json` などに次を登録します。

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "uv run python hooks/aitdd_guard.py",
            "timeout": 30
          }
        ]
      }
    ]
  }
}
```

`AITDD_PHASE=red|green|refactor` と `AITDD_TEST_COMMAND` を渡すと、そのフェーズの
期待に合わない状態を block します。

## ループ

1. Codex が次の最小ステップを計画する
2. Cursor が RED として、失敗するテストだけを書く
3. テストが失敗しなければ RED をやり直す
4. Cursor が GREEN として、通すための最小実装を書く
5. テストが通らなければ GREEN をやり直す
6. Codex がレビューし、不足テスト観点があれば `test_backlog` に積む
7. Cursor が必要なら REFACTOR する
8. テストが通ることを確認し、backlog があれば次の RED に進む
9. backlog が空で完了条件を満たしたら Codex が完了判定する

`--max-cycles` は安全弁です。完璧を目指しつつ、暴走しないように上限を持たせています。
