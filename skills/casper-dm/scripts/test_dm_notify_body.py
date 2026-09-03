#!/usr/bin/env python3
"""dm_notify_body.py 自己検証(cmd_525差し戻しF2手当)。

★配置理由: skills/casper-dm/scripts/ は casper_supervisor.sh:20 の
SCR($ROOT/projects/casper/scripts)の外にあり、sig()監視の対象外
(SCR直下でない時点で対象外・test_プレフィックスは念のための二重の備え)。
★1コマンドで再走可能: python3 skills/casper-dm/scripts/test_dm_notify_body.py
subtask_525_impl1でscratchpad(/tmp配下)に置かれ将軍検品でF2として差し戻された
検証群(AC-body-1/2・AC-prefs-1/2・AC-state-1・AC-mutation・AC-state-coverage)を
リポジトリ内へ移設したもの(cmd_524 D2と同型の病の再演を断つ)。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dm_notify_body as dmb  # noqa: E402

FAILURES = []


def check(label, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {label}" + (f" — {detail}" if detail else ""))
    if not cond:
        FAILURES.append(label)


def ac_body_1():
    """五出口: no_messages/self_sent/body欠落/empty_body/通常"""
    r = dmb.extract_dm_body("u1", [])
    check("AC-body-1 no_messages", r == {"body": None, "reason": "no_messages"}, str(r))

    r = dmb.extract_dm_body("u1", [{"sender_id": "u1", "body": "hi", "created_at": "2026-09-03T10:00:00"}])
    check("AC-body-1 self_sent", r == {"body": None, "reason": "self_sent"}, str(r))

    r = dmb.extract_dm_body("u1", [{"sender_id": "u2", "created_at": "2026-09-03T10:00:00"}])
    check("AC-body-1 body欠落", r == {"body": None, "reason": "body欠落"}, str(r))

    r = dmb.extract_dm_body("u1", [{"sender_id": "u2", "body": "", "created_at": "2026-09-03T10:00:00"}])
    check("AC-body-1 empty_body", r == {"body": "", "reason": "empty_body"}, str(r))

    r = dmb.extract_dm_body("u1", [{"sender_id": "u2", "body": "こんにちは", "created_at": "2026-09-03T10:00:00"}])
    check("AC-body-1 通常", r == {"body": "こんにちは", "reason": None}, str(r))


def ac_body_2():
    """200字切り詰め: 250字→200字+「…」、境界の200字は無変更"""
    text_250 = "あ" * 250
    r = dmb.truncate_body(text_250)
    check("AC-body-2 250字→201文字(200+…)", len(r) == 201 and r.endswith("…"), f"len={len(r)}")

    text_200 = "あ" * 200
    r = dmb.truncate_body(text_200)
    check("AC-body-2 境界200字は無変更", r == text_200, f"len={len(r)}")


def ac_prefs_1_2():
    """casper_push.set_prefs/type_enabled による dm_body ON/OFF、本文露出の有無"""
    here = os.path.dirname(os.path.abspath(__file__))
    casper_scripts = os.path.normpath(os.path.join(here, "..", "..", "..", "projects", "casper", "scripts"))
    if casper_scripts not in sys.path:
        sys.path.insert(0, casper_scripts)
    import casper_push  # noqa: E402

    added = False
    if "dm_body" not in casper_push.NOTIFY_TYPES:
        casper_push.NOTIFY_TYPES.append("dm_body")
        added = True

    orig_prefs_file = casper_push.PREFS_FILE
    tmpdir = tempfile.mkdtemp(prefix="test_dm_notify_body_")
    tmp_prefs = os.path.join(tmpdir, "notify_prefs.json")
    casper_push.PREFS_FILE = tmp_prefs
    try:
        uid = "test_uid_1"
        before = casper_push.type_enabled(uid, "dm_body")
        casper_push.set_prefs(uid, {"dm_body": False})
        after = casper_push.type_enabled(uid, "dm_body")
        check("AC-prefs-1 ON→OFF反映", before is True and after is False, f"before={before} after={after}")

        msgs = [{"sender_id": "u2", "body": "秘密の本文です", "created_at": "2026-09-03T10:00:00"}]
        extracted = dmb.extract_dm_body(uid, msgs)
        fresh_off = [{"id": "t1", "peer": "u2", "updated_at": "2026-09-03T10:00:00",
                      "body": extracted["body"], "reason": extracted["reason"]}]
        if casper_push.type_enabled(uid, "dm_body"):
            _, body_off = dmb.compose_multi_body(fresh_off)
        else:
            body_off = "u2 より"
        check("AC-prefs-2 OFF時は本文が現れない", "秘密の本文です" not in body_off, body_off)

        casper_push.set_prefs(uid, {"dm_body": True})
        if casper_push.type_enabled(uid, "dm_body"):
            _, body_on = dmb.compose_multi_body(fresh_off)
        else:
            body_on = "u2 より"
        check("AC-prefs-2対照 ON時は本文が現れる", "秘密の本文です" in body_on, body_on)
    finally:
        casper_push.PREFS_FILE = orig_prefs_file
        if added:
            casper_push.NOTIFY_TYPES.remove("dm_body")


def ac_state_1():
    """状態ファイル検問: 正常=緑/本文混入=赤/dict化=赤/空文字=赤。書込拒否/写しへの正常書込も実測"""
    good = {"u1": {"t1": "2026-09-03T10:00:00"}}
    bad_freeform = {"u1": {"t1": "こんにちは"}}
    bad_dict = {"u1": {"t1": {"nested": True}}}
    bad_empty = {"u1": {"t1": ""}}

    check("AC-state-1 正常=緑(空リスト)", dmb.validate_dm_notify_state(good) == [], str(dmb.validate_dm_notify_state(good)))
    check("AC-state-1 本文混入=赤", len(dmb.validate_dm_notify_state(bad_freeform)) == 1, str(dmb.validate_dm_notify_state(bad_freeform)))
    check("AC-state-1 dict化=赤", len(dmb.validate_dm_notify_state(bad_dict)) == 1, str(dmb.validate_dm_notify_state(bad_dict)))
    check("AC-state-1 空文字=赤", len(dmb.validate_dm_notify_state(bad_empty)) == 1, str(dmb.validate_dm_notify_state(bad_empty)))

    tmpdir = tempfile.mkdtemp(prefix="test_dm_notify_body_state_")
    bad_path = os.path.join(tmpdir, "bad.json")
    raised = False
    try:
        dmb.safe_dump_dm_notify_state(bad_freeform, bad_path)
    except RuntimeError:
        raised = True
    check("AC-state-1 不正値はRuntimeError送出", raised)
    check("AC-state-1 不正値は書込を行わない", not os.path.exists(bad_path))

    good_path = os.path.join(tmpdir, "good.json")
    dmb.safe_dump_dm_notify_state(good, good_path)
    check("AC-state-1 正常値は写しへ書込済", os.path.exists(good_path))


def ac_mutation():
    """AC7: extract_dm_body を『常にNoneを返す』へ差し替え→赤化→復元→緑化"""
    orig = dmb.extract_dm_body
    msgs = [{"sender_id": "u2", "body": "こんにちは", "created_at": "2026-09-03T10:00:00"}]

    before = dmb.extract_dm_body("u1", msgs)
    check("AC-mutation 変異前は正常値", before["body"] == "こんにちは", str(before))

    def mutated(uid, msgs):
        return {"body": None, "reason": None}

    try:
        dmb.extract_dm_body = mutated
        mutated_result = dmb.extract_dm_body("u1", msgs)
        check("AC-mutation 変異後はNoneへ赤化", mutated_result["body"] is None, str(mutated_result))
    finally:
        dmb.extract_dm_body = orig

    after = dmb.extract_dm_body("u1", msgs)
    check("AC-mutation 復元後は再び緑化", after["body"] == "こんにちは", str(after))


def ac_state_coverage():
    """prefs ON/OFF(2)×本文4状態(あり/空文字/欠落/取得失敗)(4)の全8通り + 単数/複数件"""
    combos = []
    for prefs_on in (True, False):
        for kind, msgs in [
            ("あり", [{"sender_id": "u2", "body": "本文あり", "created_at": "2026-09-03T10:00:00"}]),
            ("空文字", [{"sender_id": "u2", "body": "", "created_at": "2026-09-03T10:00:00"}]),
            ("欠落", [{"sender_id": "u2", "created_at": "2026-09-03T10:00:00"}]),
            ("取得失敗(msgs空)", []),
        ]:
            r = dmb.extract_dm_body("u1", msgs)
            combos.append((prefs_on, kind, r["reason"]))

    expected_reasons = {"あり": None, "空文字": "empty_body", "欠落": "body欠落", "取得失敗(msgs空)": "no_messages"}
    all_ok = all(reason == expected_reasons[kind] for (_prefs, kind, reason) in combos)
    check("AC-state-coverage 8通りのreasonが意図通り", all_ok, str(combos))

    single = [{"id": "t1", "peer": "u2", "updated_at": "2026-09-03T10:00:00", "body": "最新の本文", "reason": None}]
    n, body = dmb.compose_multi_body(single)
    check("AC-state-coverage 単数件(「他」表記なし)", n == 1 and "他" not in body, f"n={n} body={body}")

    multi = [
        {"id": "t1", "peer": "u2", "updated_at": "2026-09-03T09:00:00", "body": "古い本文", "reason": None},
        {"id": "t2", "peer": "u3", "updated_at": "2026-09-03T10:00:00", "body": "新しい本文", "reason": None},
    ]
    n, body = dmb.compose_multi_body(multi)
    check("AC-state-coverage 複数件(「他1件」・最新1件を採用)",
          n == 2 and "新しい本文" in body and "他1件" in body, f"n={n} body={body}")


def main():
    ac_body_1()
    ac_body_2()
    ac_prefs_1_2()
    ac_state_1()
    ac_mutation()
    ac_state_coverage()

    print()
    if FAILURES:
        print(f"RESULT: FAIL ({len(FAILURES)}件) — {FAILURES}")
        sys.exit(1)
    print("RESULT: ALL PASS")
    sys.exit(0)


if __name__ == "__main__":
    main()
