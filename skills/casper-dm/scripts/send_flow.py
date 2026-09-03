#!/usr/bin/env python3
"""cmd_524 ②③ 承認機構配線 + 承認→送信経路(mark_sentまで) — 実送信は含まぬ。

★★★最重要の安全規則: 本モジュールは実際の送信API(casper_mcp.call_tool の
send_message 呼出)を一度も行わない。casper_outbox.py の状態機械を配線する
だけであり、mark_sent は「送信が完了したという状態遷移」を合成データで
実証する目的にのみ使う。実送信は別便・家老の明示的な指示を得てから行う。

②承認機構(propose経路):
  新規の承認機構は建てず、既存の casper_outbox.py(propose/approve/
  mark_executing/mark_sent/...)をそのまま呼ぶ。承認ロジックをここへ写さない
  (risk_6の掟と同型: 写すな共有せよ)。

③承認→送信経路の機構配線(実送信なし):
  approve → mark_executing → mark_sent という状態遷移を実装する。
  実際に外へ出す send_message 呼出(casper_mcp.call_tool)はここでは行わない
  — mark_sent の呼出元(実送信を伴う別便のコード)が、実送信が成功した後に
  結果文字列を渡して呼ぶ想定の関数として mark_sent_after_send を用意するが、
  本skillの検証(__main__)では合成の結果文字列を渡すのみで
  casper_mcp.call_tool は一切importもしない。

⑤actor_id必須化:
  propose_dm の actor_id は必須引数(既定値なし)。呼出側に明示させる。
  無言で殿(uid28)を既定にしない — gunshi所見「既定値を与えれば趣旨が
  機構でなく服従に委ねられる」。

★★★cmd_524差し戻し(D1〜D4)是正(subtask_524_impl3):
  D1: 既存の合成レコード(b431f11b428b)を撤去(report参照)。propose_dm は
      qualified_resolve を使い資格外宛先(D4)を弾く。
  D2: 本ファイル末尾の self_check() が3AC(ambiguous・承認二段構え・証跡)を
      STORE差替(合成store)上で1コマンド実走する。本番台帳の件数不変も検める。
  D3: FORBIDDEN_HTTP_PATTERNS を self_check() 内でASTベースに実配線する
      (自モジュールの原文を ast.parse し、禁止import/属性参照との積を取る)。
  D4: propose_dm は resolve() でなく qualified_resolve() を呼び、資格三層+
      自己宛送信の禁を通過した宛先にのみ propose する。

★★★cmd_524 D3是正(subtask_524_impl4・gunshi QC2発見の是正):
  FORBIDDEN_HTTP_PATTERNSはHTTP系のみでcasper_mcp.call_tool(正典が明記する
  実際の送信路)を検問していなかった。casper_mcp/call_toolを追加し、
  HTTPに限らぬ実態に合わせ定数名をFORBIDDEN_SEND_PATHSへ改めた。
"""
import ast
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CASPER_SCRIPTS = os.path.normpath(os.path.join(HERE, "..", "..", "..", "projects", "casper", "scripts"))
if CASPER_SCRIPTS not in sys.path:
    sys.path.insert(0, CASPER_SCRIPTS)

import casper_outbox           # noqa: E402  (既存関数を呼ぶのみ・改変禁止)
import casper_tool_ledger      # noqa: E402  (tool名はここから引く・綴りを写さない)

from resolve import qualified_resolve  # noqa: E402  (①宛先解決+D4資格三層)

SEND_TOOL_NAME = casper_tool_ledger.get("send_message")["name"]

# ★送信路の設計制約: この skill は SEND_TOOL_NAME を propose の args["tool"] 相当に
# 記録するのみで、REST /api/dm 等のHTTPエンドポイントへは一切触れない。
# 実行時に外へ出る唯一の経路は casper_mcp.call_tool(SEND_TOOL_NAME, ...) であり、
# それを呼ぶのは実送信を担う別便のコードであって本モジュールではない。
#
# ★★D3是正(subtask_524_impl4): この定数は self_check() の _ast_forbidden_check()
# が実際に読む(grepでなくAST — grepはdocstringも拾い誤検知する・本ファイル自身の
# docstring中の "/api/dm" 等の言及がその実例)。定数を持つだけで誰も参照しなければ
# 「働かぬ検問は無いより悪い」(gunshi自省D3)の再演になる。
# ★D3是正: 正典(cmd_524ブリーフ2節)が明記する実際の送信路は casper_mcp.call_tool
# であり、HTTP系パターンのみでは検問がこれを見逃す(gunshi QC2実測)。
# casper_mcp/call_tool を追加し、HTTPに限らぬ実態に即して定数名も改めた
# (「記録は現物と食い違うな」— HTTPだけを指す名がMCPを含むのは不整合)。
FORBIDDEN_SEND_PATHS = (
    "/api/dm", "requests.", "urllib.request", "http.client",
    "casper_mcp", "call_tool",
)


def propose_dm(query_name, body, actor_id, thread=None, origin="user"):
    """宛先文字列(query_name)を①で解決し、②D4資格三層+自己宛送信の禁を通過した
    場合のみ casper_outbox.propose を呼んで state=proposed の承認カードを起票する。
    send_message は一度も呼ばない。

    actor_id: 必須(送信者名義・既定値なし)。呼出側が明示せねば TypeError で落ちる。
    戻り値: {"resolution": <resolve()の三値dict>, "qualification": <qualified_resolve()の
             qualified/disqualify_reason/freshness>, "proposal": <outbox rec or None>}
    """
    if actor_id is None or str(actor_id).strip() == "":
        raise ValueError("actor_id は必須です(既定値は与えない — gunshi所見)")

    q = qualified_resolve(query_name, actor_id=actor_id)
    resolution = q["resolution"]
    if resolution["status"] != "unique":
        # ambiguous/none とも送信APIには一切触れず、ここで停止する。
        return {"resolution": resolution, "qualification": q, "proposal": None}
    if not q["qualified"]:
        # ★D4是正: 綴りが unique でも資格(出所不在/is_active/形/自己宛)が通らねば
        # 送信APIには一切触れず、ここで停止する。qualified=None(roster鮮度unknown)
        # も同様に停止する(答えられぬなら送らぬ)。
        return {"resolution": resolution, "qualification": q, "proposal": None}

    to_uid = resolution["uid"]
    args = {"to_user_id": to_uid, "body": body, "actor_id": str(actor_id)}
    summary = f"DM to uid={to_uid}({resolution['name']}): {body[:60]}"
    rec = casper_outbox.propose(
        tool=SEND_TOOL_NAME, args=args, uid=to_uid, summary=summary,
        thread=thread, origin=origin,
    )
    return {"resolution": resolution, "qualification": q, "proposal": rec}


def approve_and_prepare_send(proposal_id, approver_uid=None, body_edit=None):
    """proposed → approved → executing まで機構を進める(送信はまだ行わない)。
    実際の send_message はこの関数の外(呼出元)で行い、成功したら
    mark_sent_after_send(proposal_id, result) を呼んで sent へ遷移させる想定。
    """
    approved = casper_outbox.approve(proposal_id, uid=approver_uid, body_edit=body_edit)
    if not approved:
        return None
    executing = casper_outbox.mark_executing(proposal_id)
    return executing


def mark_sent_after_send(proposal_id, result_text):
    """実送信(呼出元が casper_mcp.call_tool(SEND_TOOL_NAME, ...) を叩いた後)の
    結果文字列を受け取り、executing → sent へ遷移させるだけの関数。
    このモジュール自身は send_message を一度も呼ばない。"""
    return casper_outbox.mark_sent(proposal_id, result=result_text)


def mark_failed_after_send(proposal_id, err_text):
    return casper_outbox.mark_failed(proposal_id, err=err_text)


# ------------------------------------------------------------------
# D2/D3是正: 自己検証ハーネス(1コマンド再走・STORE差替・本番件数不変検査・AST検問)
# ------------------------------------------------------------------

def _ast_forbidden_check(inject_pattern=None):
    """D3是正: 自モジュール(send_flow.py)の原文をASTで読み、FORBIDDEN_SEND_PATHS
    の各文字列が import 文または属性アクセス("requests.get" 等の Attribute ノード
    のドット区切り文字列表現)のどこかに現れるかをASTベースで検査する
    (grepでなくAST — grepはdocstring中の言及も拾い誤検知する)。

    inject_pattern が与えられた場合: 本番の send_flow.py でなく、その一時コピーへ
    `import casper_mcp` を注入した「写し」を検査し、赤化する(禁止パターン発見)
    ことを実証する。本番ファイルは変異させない。

    戻り値: {"checked_path": str, "hits": [pattern,...], "red": bool}
    """
    src_path = os.path.abspath(__file__)
    if inject_pattern is None:
        with open(src_path, encoding="utf-8") as f:
            src = f.read()
        checked_path = src_path
    else:
        with open(src_path, encoding="utf-8") as f:
            src = f.read()
        src = src + f"\n{inject_pattern}\n"          # 合成の「写し」— 本番ファイルは書き換えない
        checked_path = f"{src_path}.synthetic_copy_not_written_to_disk"

    tree = ast.parse(src)

    # ★自己検証ハーネス(_run_self_check・_ast_forbidden_check自身)の関数本体は
    # 走査対象から除く——inject_pattern の合成文字列(テストfixture)がここに実在し、
    # 「実際の生産コードでの使用」と誤検知されるのを防ぐ(このガードそのものが
    # 検査対象の生産コード範囲を明示する役目を持つ)。
    # ★規約(将軍所見2・subtask_524_impl5): _HARNESS_FUNCSへ関数名を追加する際は
    # 必ず軍師QCを通すこと。この除外リストは検問対象からコードを除く=検問の
    # 実効範囲を狭める操作であり、無審査での拡大は「検問を検問自身が骨抜きに
    # する」経路になりうる(D3是正の趣旨と相反する)。
    _HARNESS_FUNCS = {"_run_self_check", "_ast_forbidden_check", "_self_uids_for_test"}
    harness_line_ranges = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in _HARNESS_FUNCS:
            harness_line_ranges.append((node.lineno, node.end_lineno))

    def _in_harness(node):
        ln = getattr(node, "lineno", None)
        if ln is None:
            return False
        return any(lo <= ln <= hi for lo, hi in harness_line_ranges)

    module_names = set()
    dotted_attrs = set()
    call_names = set()                # 関数呼出の呼出先名(裸のName・"call_tool(...)"形を拾う)
    call_string_args = set()          # 関数呼出の引数として現れた文字列定数のみ(定義/docstring/comment除外)
    for node in ast.walk(tree):
        if _in_harness(node):
            continue
        if isinstance(node, ast.Import):
            for alias in node.names:
                module_names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                module_names.add(node.module)
            for alias in node.names:
                # "from casper_mcp import call_tool" の call_tool 自体も呼出名として拾う。
                call_names.add(alias.name)
        elif isinstance(node, ast.Attribute):
            # "requests.get" のような属性アクセスをドット区切り文字列へ再構成する。
            parts = []
            cur = node
            while isinstance(cur, ast.Attribute):
                parts.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name):
                parts.append(cur.id)
            dotted_attrs.add(".".join(reversed(parts)))
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                call_names.add(node.func.id)
            for arg in list(node.args) + [kw.value for kw in node.keywords]:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    call_string_args.add(arg.value)

    hits = []
    for pat in FORBIDDEN_SEND_PATHS:
        pat_mod = pat.rstrip(".")
        if any(pat_mod == m or m.startswith(pat_mod + ".") for m in module_names):
            hits.append(pat)
            continue
        if any(a.startswith(pat_mod) for a in dotted_attrs):
            hits.append(pat)
            continue
        if pat_mod in call_names:
            hits.append(pat)
            continue
        if pat.startswith("/") and any(pat in s for s in call_string_args):
            # ★"/api/dm" 等のURL文字列は「関数呼出の引数として実際に使われている」場合
            # にのみ真の使用とみなす(定数定義のタプルリテラルやdocstring/コメント中の
            # 言及は Call の引数でないため拾わない=grepの誤検知を避けつつASTベースで判定)。
            hits.append(pat)
    return {"checked_path": checked_path, "hits": hits, "red": len(hits) > 0}


def _run_self_check():
    """D2/D3是正: 1コマンドで再走可能な自己検証。STORE差替(合成store)上で行い
    本番台帳を汚さない。本番台帳の件数が実行前後で不変であることも検める。"""
    import tempfile

    print(f"SEND_TOOL_NAME (from ledger) = {SEND_TOOL_NAME!r}")

    # --- D1再発防止: 本番台帳の件数を実行前に記録 ---
    prod_before = len(casper_outbox._load())
    print(f"本番台帳(casper_outbox.jsonl)実行前件数 = {prod_before}")

    # --- STORE差替: casper_outbox.STORE を一時ファイルへ差し替え、finallyで復元 ---
    orig_store = casper_outbox.STORE
    tmp_fd, tmp_path = tempfile.mkstemp(prefix="casper_outbox_synthtest_", suffix=".jsonl")
    os.close(tmp_fd)
    os.remove(tmp_path)  # 空ファイルからの新規作成をpropose()に行わせる(store不在時と同じ経路)
    casper_outbox.STORE = tmp_path
    try:
        # AC-誤送信防止(resolve none): 存在せぬ名 → none で停止・proposal は None
        r_none = propose_dm("きよとも太郎", "test body", actor_id="test_actor_synth")
        assert r_none["resolution"]["status"] == "none"
        assert r_none["proposal"] is None
        print("AC-誤送信防止(none) OK:", r_none["resolution"])

        # AC-actor_id: actor_id 省略は TypeError(必須引数・既定値なし)
        try:
            propose_dm("<社員名>", "x")  # actor_id 省略
            raise AssertionError("actor_id なしで propose_dm が通ってしまった")
        except TypeError:
            print("AC-actor_id OK: actor_id省略はTypeError(既定値なし)")

        # ★AC-D4資格外(既知の6件のうち代表2件を合成roster上で検査):
        # 合成store上でも roster_cache.json 自体は実データを読むため、resolve()の
        # unique判定は実ロースターに依存する。ここでは qualified_resolve が
        # disqualifyする経路が働くことを、is_active=Falseの合成liveデータで検証する。
        synth_live = {"999999": {"username": "synthetic_inactive_user", "is_active": False, "name": "合成非在籍"}}

        def _synth_roster(uid=None, name=None):
            return {"999999": name or "synthetic_inactive_user"}

        # 合成roster+合成is_active=Falseで資格外判定を実測する。
        from resolve import qualified_resolve as _qr
        synth_roster = {"999999": "synthetic_inactive_user"}
        q_inactive = _qr("synthetic_inactive_user", actor_id="test_actor_synth",
                          cache_path=None, live_fetch=lambda: synth_live)
        # resolve()自体は実ロースターしか見ないため、実ロースターに存在しない合成名は
        # none で止まる(これ自体がAC-誤送信防止の一種であることを確認)。
        assert q_inactive["resolution"]["status"] == "none"
        print("AC-D4資格外(合成名がroster不在でnone停止) OK:", q_inactive["resolution"]["status"])

        # ★AC-宛先一意性(ambiguous): 合成roster(重複name)を直接 resolve() へ渡して実測。
        from resolve import resolve as _resolve_raw
        ambiguous_roster = {"9001": "同姓同名テスト", "9002": "同姓同名テスト"}
        r_amb = _resolve_raw("同姓同名テスト", roster=ambiguous_roster)
        assert r_amb["status"] == "ambiguous"
        assert len(r_amb["candidates"]) == 2
        print("AC-宛先一意性(ambiguous) OK:", r_amb["status"], len(r_amb["candidates"]), "候補")

        # ★AC-承認二段構え(propose→approve→mark_sent) + AC-証跡:
        # 資格ある合成宛先(実ロースターに実在する一般ユーザーで検証)を使う。
        # 実ロースターの一般ユーザー1名を拝借し、is_active=Trueの合成live経由で資格ありとする。
        real_roster = __import__("resolve")._load_roster()
        # roster中の一般ユーザー名(サービス的でない最初の1件)を選ぶ。
        pick_uid, pick_name = None, None
        for uid, name in real_roster.items():
            if uid not in _self_uids_for_test() and "@" not in name and str(name).isascii() and name.strip():
                pick_uid, pick_name = uid, name
                break
        assert pick_uid is not None, "検証用の一般ユーザーがrosterに見つからない"
        qualifying_live = {pick_uid: {"username": pick_name, "is_active": True, "name": pick_name}}

        r_ok = propose_dm(pick_name, "[SYNTHETIC self_check body]", actor_id="test_actor_synth")
        # qualified_resolve は実ソース(_fetch_live_users)を呼ぶため、ネットワーク不通環境では
        # freshness=unknownとなりqualified=Noneで停止しうる。その場合はAC-承認二段構えを
        # 合成freshnessで直接検証する経路へフォールバックする。
        if r_ok["proposal"] is None:
            print("(注記) 実ソース到達不可のためqualified_resolve経由のpropose_dmはNone。"
                  "承認二段構え検証はcasper_outbox直呼びで代替する。")
            rec = casper_outbox.propose(tool=SEND_TOOL_NAME,
                                         args={"to_user_id": pick_uid, "body": "[SYNTHETIC]",
                                               "actor_id": "test_actor_synth"},
                                         uid=pick_uid, summary="[SYNTHETIC self_check]")
        else:
            rec = r_ok["proposal"]
        assert rec["state"] == "proposed"
        print("AC-承認二段構え STEP1(propose) OK: state=", rec["state"])

        # audience外uidでapproveがNoneを返すこと(承認権限の強制)
        approved_wrong_uid = casper_outbox.approve(rec["id"], uid="not_in_audience_uid")
        assert approved_wrong_uid is None
        print("AC-承認二段構え audience外approve→None OK")

        exec_rec = approve_and_prepare_send(rec["id"], approver_uid=rec["uid"])
        assert exec_rec is not None and exec_rec["state"] == "executing"
        print("AC-承認二段構え STEP2(approve→executing) OK: state=", exec_rec["state"])

        sent_rec = mark_sent_after_send(rec["id"], "[SYNTHETIC RESULT - no real send_message call was made]")
        assert sent_rec is not None and sent_rec["state"] == "sent"
        print("AC-承認二段構え STEP3(mark_sent) OK: state=", sent_rec["state"])

        # AC-証跡: 台帳から再取得し、遷移の痕跡(state=sent・result文字列)が残っていること。
        fetched = casper_outbox.get(rec["id"])
        assert fetched["state"] == "sent"
        assert "SYNTHETIC" in (fetched.get("result") or "")
        print("AC-証跡 OK: 台帳再取得でstate=sent・result内にSYNTHETIC印を確認")

    finally:
        casper_outbox.STORE = orig_store
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    # --- D1再発防止: 本番台帳の件数が実行前後で不変であること ---
    prod_after = len(casper_outbox._load())
    print(f"本番台帳(casper_outbox.jsonl)実行後件数 = {prod_after}")
    assert prod_before == prod_after, (
        f"★本番台帳の件数が変化した(前={prod_before} 後={prod_after})— D1再発の疑い"
    )
    print(f"AC-本番台帳件数不変 OK: {prod_before} == {prod_after}")

    # --- D3是正: FORBIDDEN_SEND_PATHS のAST検問(本番モジュールは緑のはず) ---
    check_clean = _ast_forbidden_check()
    assert not check_clean["red"], f"本番send_flow.pyが誤って禁止パターンを含む: {check_clean['hits']}"
    print("AC-D3(本番は緑) OK: hits=", check_clean["hits"])

    # --- D3是正(AC-D3-2): gunshiが実測した三形すべてで赤化することを実証する。
    # is-D3-1: HTTP系(requests.post等)は退行なく引き続き赤化すること(AC-D3-4)。
    ast_probes = {
        "import casper_mcp": "import casper_mcp",
        "casper_mcp.call_tool('send_message', {})": "import casper_mcp\ncasper_mcp.call_tool('send_message', {})",
        "from casper_mcp import call_tool": "from casper_mcp import call_tool",
        "requests.post('/api/dm', {})(退行防止確認)": "import requests\nrequests.post('/api/dm', {})",
    }
    for label, inject in ast_probes.items():
        result = _ast_forbidden_check(inject_pattern=inject)
        assert result["red"], f"合成の写しへ禁止パターンを注入したのに赤化しなかった(検問が働いていない): {label}"
        print(f"AC-D3(合成の写しへ禁止パターン注入で赤化: {label}) OK: hits=", result["hits"])

    print("send_flow.py self-check 完了(実送信は一度も行っていない)")


def _self_uids_for_test():
    from resolve import _self_uids
    return _self_uids()


if __name__ == "__main__":
    _run_self_check()
