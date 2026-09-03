#!/usr/bin/env python3
"""DM着信プッシュ本文重視化(cmd_525)— 抽出ロジック単体モジュール。

★本日は同日デプロイ禁につき本番chat_server.py/casper_push.pyへは一切差し込まない
(gunshi戦略review subtask_525_strategy1の裁定・A案)。翌日、本ファイル内の関数を
chat_server.py/casper_push.pyへ配線する(下部の「■ 明日の差し込みパッチ」参照)。

依存ゼロ(標準ライブラリのみ)。chat_server.py既存の_thread_is_newが持つ
「最新メッセージ」特定の作法(created_at→ts→id の順でmax)をここへ括り出し、
本モジュールと(翌日配線後の)判定側とで共有する(写すな共有せよ・鉄則)。
"""
import json
import os
import re
import tempfile


# ── 最新メッセージ特定(chat_server.py _thread_is_new と同一の作法を共有) ──
def latest_message(msgs):
    """msgsの中から最新の1件を返す(空ならNone)。
    chat_server.py L4951の作法(max key=created_at→ts→id)をそのまま踏襲——
    判定側(_thread_is_new)と本文側とで別々にmaxを書かない(写すな共有せよ)。"""
    msgs = msgs or []
    if not msgs:
        return None
    return max(msgs, key=lambda m: str(m.get("created_at") or m.get("ts") or m.get("id") or ""))


# ── 200字切り詰め(一箇所でのみ・len()=文字数で数える。byte数でない) ──
TRUNCATE_LEN = 200


def truncate_body(text):
    """本文を200字で切り詰める。超過時のみ末尾に「…」1字を付す。一箇所でのみ行う(写すな共有せよ)。"""
    text = text or ""
    if len(text) <= TRUNCATE_LEN:
        return text
    return text[:TRUNCATE_LEN] + "…"


# ── 五出口の本文抽出 ──────────────────────────────────────────────
# reason 値: None(通常) / "empty_body" / "body欠落" / "no_messages" / "self_sent"
def extract_dm_body(uid, msgs):
    """新着DMの本文を抽出する。五出口を明示的に区別して返す:
      {"body": str|None, "reason": None|"empty_body"|"body欠落"|"no_messages"|"self_sent"}

    - msgsが空            → body=None, reason="no_messages"
    - 最新が自分の送信      → body=None, reason="self_sent"
    - 最新にbodyキー自体が無い → body=None, reason="body欠落"
    - 最新のbodyが空文字     → body="",   reason="empty_body"
    - それ以外(通常)        → body=切り詰め済み文字列, reason=None

    ★現行_dm_notify_check既存の「失敗」と「ゼロ」の区別(取得失敗→ts進めず次回再試行/
    msgs空→既知化のためts更新)は呼び出し側(chat_server.py側のtry/except)の責務のまま
    保つ——本関数は「msgsが既に手元にある」前提の抽出のみを担い、取得失敗を混同しない。"""
    latest = latest_message(msgs)
    if latest is None:
        return {"body": None, "reason": "no_messages"}
    if str(latest.get("sender_id")) == str(uid):
        return {"body": None, "reason": "self_sent"}
    if "body" not in latest and "text" not in latest and "content" not in latest:
        return {"body": None, "reason": "body欠落"}
    raw = latest.get("body")
    if raw is None:
        raw = latest.get("text")
    if raw is None:
        raw = latest.get("content")
    if raw is None:
        return {"body": None, "reason": "body欠落"}
    if raw == "":
        return {"body": "", "reason": "empty_body"}
    return {"body": truncate_body(str(raw)), "reason": None}


# ── 複数件処理: freshリストの各要素が持つupdated_atで並べ、最新1件の本文+「他N件」 ──
def compose_multi_body(fresh_with_bodies):
    """fresh_with_bodies = [{"id":..., "peer":..., "updated_at":..., "body":str|None, "reason":...}, ...]
    「最新」の決め方は新たに書かない——updated_atの文字列比較で並べる
    (chat_server.py dm_threads/L5019と同じ並べ方=str比較でreverse=True)。
    返り: (title_suffix_n, body_text)"""
    items = sorted(fresh_with_bodies or [], key=lambda x: str(x.get("updated_at") or ""), reverse=True)
    if not items:
        return (0, "")
    top = items[0]
    n = len(items)
    body = top.get("body") or ""
    if not body:
        peer = top.get("peer") or ""
        body = f"{peer} より" if peer else "新しいDMが届きました"
    if n > 1:
        body = f"{body}（他{n - 1}件）"
    return (n, body)


# ── 状態ファイル検問: json.dumpの前に置く。ISO8601 ts形式であることを許可条件とする ──
# 「40字超を弾く」ではなく「値の形」を許可条件にする(gunshi裁定と同型の判定基準・許可を定める形の方が強い)。
_ISO8601_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?)?$"
)


def is_valid_dm_notify_state_value(v):
    """dm_notify_state.jsonへ書く1スレッド分の値(=updated_atの文字列)がISO8601 ts形式か。
    構造(dict化等)や本文混入(自由文字列)は形が合わず自動的に弾かれる(許可条件が値の形そのものゆえ)。
    空文字は形が合わないので不許可(仕様上ts欠落を許すならNoneで表現し、この関数の対象外とする)。"""
    if not isinstance(v, str):
        return False
    return bool(_ISO8601_RE.match(v))


def validate_dm_notify_state(state_dict):
    """state_dict = {uid: {thread_id: ts_value, ...}, ...} 全体を検問。
    (uid, thread_id, 実際の値)の一覧のうち不正な物のリストを返す(空なら全緑)。
    json.dumpの直前でこれを呼び、非空なら書込を中止する(書いてから検めるな)。"""
    bad = []
    for uid, threads in (state_dict or {}).items():
        if not isinstance(threads, dict):
            bad.append((uid, None, threads))
            continue
        for tid, v in threads.items():
            if not is_valid_dm_notify_state_value(v):
                bad.append((uid, tid, v))
    return bad


def safe_dump_dm_notify_state(state_dict, path):
    """検問を通過した場合のみjson.dumpする。不正値があれば書込を拒否しRuntimeErrorを送出。
    ★本モジュール自身の自己検証内でも本番dm_notify_state.jsonへは書き込まない
    (呼び出し側がtempfile等の写しパスを渡すこと)。"""
    bad = validate_dm_notify_state(state_dict)
    if bad:
        raise RuntimeError(f"dm_notify_state検問NG: 不正値 {len(bad)}件 (例: {bad[0]})")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state_dict, f, ensure_ascii=False)


# ══════════════════════════════════════════════════════════════════
# ■ 明日の差し込みパッチ(翌日、本番chat_server.py/casper_push.pyへ実際に当てる形)
#
# --- casper_push.py L172 ---
# NOTIFY_TYPES = ["morning_brief", "new_overdue", "stalled_fb", "dm", "dm_body", "open_loop"]
#
# --- chat_server.py 冒頭 import群の近く ---
# import dm_notify_body as _dmbody
#
# --- chat_server.py _thread_is_new (L4944付近) を書き換え、maxの作法を共有 ---
# def _thread_is_new(uid, msgs):
#     msgs = msgs or []
#     if not msgs:
#         return False
#     newest = _dmbody.latest_message(msgs)
#     if str(newest.get("sender_id")) == str(uid):
#         return False
#     return any(str(m.get("sender_id")) != str(uid) and not m.get("read_at") for m in msgs)
#
# --- chat_server.py _dm_notify_check (L5055-5097) の fresh.append 直後に本文を同梱 ---
#     if _thread_is_new(uid, msgs):
#         peers = "、".join(str(p.get("name") or p.get("user_id")) for p in peers[:3])
#         extracted = _dmbody.extract_dm_body(uid, msgs)
#         fresh.append({"id": tid, "peer": peers, "updated_at": ts,
#                       "body": extracted["body"], "reason": extracted["reason"]})
#
# --- chat_server.py _dm_notify_check の json.dump 直前(L5093-5096)を検問付きに置換 ---
#     try:
#         _dmbody.safe_dump_dm_notify_state(st, _DM_NOTIFY_STATE)
#     except Exception:
#         pass
#
# --- chat_server.py _dm_loop (L13712-13731) のpush本文組み立てを差し替え ---
#     for uid in _targets():
#         if not (casper_push and casper_push.type_enabled(uid, "dm")):
#             continue
#         fresh = _dm_notify_check(uid)
#         if fresh:
#             if casper_push.type_enabled(uid, "dm_body"):
#                 n, body = _dmbody.compose_multi_body(fresh)
#                 title = (f"💬 新着DM {n}件" if n > 1 else "💬 新着DM")
#             else:
#                 n = len(fresh)
#                 peers = "、".join(sorted({f["peer"] for f in fresh if f.get("peer")}))
#                 title = (f"💬 新着DM {n}件" if n > 1 else "💬 新着DM")
#                 body = (f"{peers} より" if peers else "新しいDMが届きました")
#             casper_push.push_to_uid(uid, {"title": title, "body": body,
#                                           "tag": "casper-dm", "url": "/", "sticky": True})
# ══════════════════════════════════════════════════════════════════
