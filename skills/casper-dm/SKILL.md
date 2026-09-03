---
name: casper-dm
description: |
  Casper が社員個人へDMを送るための宛先解決+承認機構配線スキル。roster完全一致
  照合(部分一致は使わぬ)と資格三層(出所不在/is_active/形/自己宛送信の禁)で
  「綴りが一意」と「送ってよい」を分離し、casper_outbox の propose→approve→
  mark_sent 状態遷移を配線する。「DM送る」「社員へ連絡」「<社員名>宛に送って」
  「〜さんに伝えて」等、Casperが特定個人への一対一メッセージを起票・送信しよう
  とする場面で起動。
  Do NOT use for: actor_idの無言既定(殿uid28へのフォールバック)——actor_id
  は必須引数であり呼出元が実際の話者uidを明示すること(uid28宛の正当なDM自体は
  禁じない)、グループ/複数人への一斉通知(本skillは単一宛先のみ)、REST /api/dm
  エンドポイント経由の送信(本skillが使う送信路は casper_mcp.call_tool のみ・
  HTTP直叩きは実装が禁じ検問で赤化する)、実際の送信実行そのもの(本skillが
  提供するのは resolve→propose→approve→mark_sentの状態遷移までで、実送信
  APIコール自体は別便のコードが担う)。
argument-hint: "[宛先の人名] [本文]"
allowed-tools: Read, Bash
---

# casper-dm — Casper個人DM 宛先解決+承認機構配線

## North Star

DM送信は不可逆な行為である。「迷えば送信側へ倒す」の通常則の**逆**を取り、
宛先決定は「迷えば止まる」へ倒す。本skillは実際の送信API呼出を一切行わない
——`resolve.py`・`send_flow.py` が提供するのは「送ってよい宛先か」の判定と
「承認を経て送信済状態へ遷移させる」ための機構配線のみである。

## 構成

- `scripts/resolve.py` — ①宛先解決(roster完全一致・三値) + 資格三層判定(`qualified_resolve`)
- `scripts/send_flow.py` — ②③承認機構配線(`propose_dm` / `approve_and_prepare_send` /
  `mark_sent_after_send`)。`casper_outbox.py` の状態機械をそのまま呼ぶだけで、
  承認ロジック自体はここへ写さない。

## 実行フロー(resolve → propose → 承認待ち → approve → send)

1. **resolve** — `resolve.qualified_resolve(query_name, actor_id=...)` を呼ぶ。
   内部で以下を行う:
   - `resolve()`: roster_cache.json 上で人名を正規化(小文字化・前後空白除去)
     した完全一致のみで照合し、三値を返す(`unique` / `ambiguous` / `none`)。
     部分一致へのフォールバックは行わない。
   - `unique` の場合のみ資格三層を適用: 自己宛送信の禁
     (`self_send_actor_match` / `self_uid_casper`) → 実ソース
     (`/users?limit=200`・casper_tools経由)への引き直し → 出所不在
     (`absent_from_source`) → 非アクティブ(`inactive`) → サービス的な形
     (`service_form`)。すべて通過して初めて `qualified=True`。
   - 実ソースへの照会自体が失敗した場合は `qualified=None`、
     `disqualify_reason="roster_freshness_unknown"` で停止する(答えられぬなら
     送らぬ)。roster_cache.json の新旧(fresh/stale)は監査用の付帯情報に
     留まり、資格判定の分岐には使わない。

2. **propose** — `send_flow.propose_dm(query_name, body, actor_id, thread=None, origin="user")`
   を呼ぶ。内部で `qualified_resolve` を呼び、`resolution.status == "unique"`
   かつ `qualified == True` の場合のみ `casper_outbox.propose(...)` で
   `state=proposed` の承認カードを起票する。それ以外(`ambiguous` / `none` /
   `qualified in (False, None)`)は送信APIに一切触れず、その場で停止し
   `proposal=None` を返す。`actor_id` は必須引数(既定値なし)——省略すると
   `TypeError`。殿(uid28)への無言フォールバックは存在しない。

3. **承認待ち** — 起票されたカードは `casper_outbox.pending(uid=...)` で
   宛先本人が確認できる状態(`proposed`)のまま待機する。

4. **approve** — `send_flow.approve_and_prepare_send(proposal_id, approver_uid=...)`
   を呼ぶ。`casper_outbox.approve(...)` → `casper_outbox.mark_executing(...)`
   の順に状態を進める。audience外の `uid` で approve すると `None` を返し
   拒否する(承認権限の強制)。**この時点でもまだ実送信は行っていない。**

5. **send(実送信・本skill外)** — 呼出元の別コードが
   `casper_mcp.call_tool(SEND_TOOL_NAME, args)` を実際に叩き、送信APIを
   呼ぶ。`SEND_TOOL_NAME` は `casper_tool_ledger.get("send_message")["name"]`
   から引く(綴りを直接書かない)。本skill自身(`resolve.py`・`send_flow.py`)
   はこの呼出を一度も行わない——`send_flow.py` 内の `FORBIDDEN_SEND_PATHS`
   がAST検問で `casper_mcp` / `call_tool` / `/api/dm` / `requests.` /
   `urllib.request` / `http.client` の使用を禁じ、混入すれば赤化する。

6. **mark_sent** — 実送信が成功したら、呼出元が結果文字列を持って
   `send_flow.mark_sent_after_send(proposal_id, result_text)` を呼び、
   `executing → sent` へ遷移させる。失敗時は
   `mark_failed_after_send(proposal_id, err_text)` を呼ぶ。

## disqualify_reason を利用者へどう見せるか(★必須)

`qualified_resolve` / `propose_dm` の戻り値には常に `disqualify_reason` が
含まれる。**これを黙って握り潰さず、必ず利用者への応答文面へ通すこと。**
「送れません」とだけ言うのは沈黙による失敗であり禁止する。

disqualify_reason は `resolution.status != "unique"` の間(none/ambiguous)は
常に `None` である——この2件は `resolution.status` 由来であり
`disqualify_reason` 自体には現れない。分岐は
`disqualify_reason or resolution.status` の形で書くこと(disqualify_reason
だけで分岐すると none/ambiguous は素通りする)。

| 分岐元 | 値 | 利用者への言い方(例) |
|---|---|---|
| `resolution.status` | `none` | 「『{query}』という名前はroster上に見当たりませんでした。綴りをご確認ください」 |
| `resolution.status` | `ambiguous` | 「『{query}』という名前の方が複数(候補: …)おり、一意に特定できませんでした。フルネームか社員IDでご指定ください」 |
| `disqualify_reason` | `self_send_actor_match` / `self_uid_casper` | 「ご自身(または私自身)宛のDMは起票できません」 |
| `disqualify_reason` | `absent_from_source` | 「確認済・この宛先へは送れません(名簿の実ソースに見当たりませんでした)」 |
| `disqualify_reason` | `inactive` | 「確認済・この宛先へは送れません(在籍状態が非アクティブと確認されました)」 |
| `disqualify_reason` | `service_form` | 「確認済・この宛先へは送れません(個人アカウントでなくサービス的な形のIDと判定されました)」 |
| `disqualify_reason` | `roster_freshness_unknown` | 「宛先の資格を今は確かめられぬゆえ送りません(名簿の実ソースに今は到達できませんでした。時間をおいて再度お試しください)」 |

`absent_from_source` / `inactive` / `service_form` は実ソースを引いて
**確かめた結果の確定した否**である(再試行しても変わらぬ)。「確認済・
この宛先へは送れません」等、確定を示す文型を用いる。
`roster_freshness_unknown` のみ実ソースへ届かず**確かめられなかった不明**
であり(後で変わりうる)、「今は確かめられぬ」の文型を保つ。この区別を
文面で潰して両者を同じ言い方にしてはならない——確定の否を不明と伝えると、
利用者は退職者宛などに無駄な再試行を繰り返す。

## actor_id は必須(省略不可)

`propose_dm` の `actor_id` に既定値はない。呼出側(Casper本体)は必ず
実際の話者のuidを明示して渡すこと。省略すると `TypeError` で例外送出され、
殿(uid28)への無言フォールバックには絶対に落ちない。

## 運用上の注意 — Calendar停止時は全員停止(仕様であり欠陥ではない)

資格層は常に実ソース(`/users?limit=200`・Calendar(接続先はconfig/settings.yamlを参照)経由)を
引き直す設計であり、cacheのfresh/staleでは分岐しない。**Calendarが落ちて
いる間は、宛先が誰であってもDMを起票できない**(全員 `qualified=None`・
`roster_freshness_unknown` で停止)。これはDM送信という不可逆な行為の宛先を
「答えられぬまま通す」ことを防ぐための意図的な仕様であり、欠陥ではない。

## Out of scope(本skillが行わないこと)

- 実際の送信APIコール(`casper_mcp.call_tool`)——呼出元の別コードが担う
- グループ/複数人への一斉送信
- REST `/api/dm` エンドポイント経由の送信
- `chat_server.py` の `_resolve_person`(部分一致ロジック)の使用・改変
- 実送信テスト(実在社員への実際の送信)——本skill完成後、殿の
  御指図を得てから別便で実施する
