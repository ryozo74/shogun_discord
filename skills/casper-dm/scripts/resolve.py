#!/usr/bin/env python3
"""cmd_524 ①宛先解決 — roster単一ソースの完全一致照合(部分一致は使わぬ)。

★背景(gunshi戦略review・subtask_524_strategy1要旨): 既存の chat_server.py
_resolve_person(L5284) は部分一致ロジックで「<社員名>太郎」「<姓ローマ字>太郎」が
<社員uid>(<姓ローマ字>)へ誤解決する(実測確認済)。会話文脈では正しい挙動だが、DM送信
という不可逆行為の宛先決定には危険。chat_server.py 側は直さず(hot path・
同日デプロイの禁)、本skill側で厳密な照合を別途行う。

原則: 「迷えば送信側へ倒せ」の逆 — 不可逆な行為の宛先決定は「迷えば止まる」
へ倒す。_resolve_person は一切呼ばない。

roster_cache.json は {uid(str): name(str)} の単純dict。完全一致
(小文字化・前後空白除去)で name と照合し、三値(unique/ambiguous/none)を返す。

★★cmd_524差し戻し(D4)是正(subtask_524_impl3): 「綴りが一意」と「送ってよい
資格がある」は別の問い(gunshi自省: 解決がuniqueと言うても送ってよい相手とは
限らぬ)。roster_cache.json は uid→name の名前だけしか持たず、is_active/role
を持たない(chat_server.py:_roster_refresh L586 の実装欠落が根)。本ファイルの
scopeは変えず(chat_server.pyは一切改修しない・hot path)、本skill側で実ソース
(/users?limit=200・casper_tools経由)へ直接引き直し、資格三層(出所不在/
is_active/形)で絞ったqualified roster を別途持つ。
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROSTER_PATH = os.path.join(HERE, "..", "..", "..", "projects", "casper", "scripts", "roster_cache.json")
ROSTER_PATH = os.path.normpath(ROSTER_PATH)

CASPER_SCRIPTS = os.path.normpath(os.path.join(HERE, "..", "..", "..", "projects", "casper", "scripts"))
if CASPER_SCRIPTS not in sys.path:
    sys.path.insert(0, CASPER_SCRIPTS)

STALE_SECONDS = 3600 * 6   # roster_cache.json の鮮度閾値(6h)。★D4是正後は資格判定には使わぬ
                            # (資格層は常に実ソースを引く)。roster_cache.json自体の
                            # 再取得要否のみに残す位置付け(本skillは同ファイルを書き換えぬため
                            # 実質未使用だが、鮮度概念の記録として保持)。

# ★D4是正(subtask_524_impl5): _self_uids()のimport失敗を沈黙で握り潰さず、明示的に
# stderrへ記録してからfallbackへ落ちる(将軍所見1「沈黙で落ちる経路はいずれ嘘をつく」)。
def _self_uids():
    """★D4自己宛送信の禁: Casper自身のuid集合。chat_server.py の _SELF_UIDS(L5369)を
    「写すな共有せよ」の掟通り読取専用importで直接引く(chat_server.pyはimport時に
    サーバを起動しない・全起動処理は if __name__ == "__main__" 配下で確認済)。
    importが失敗した場合のみ既知値へfail-safe(値は chat_server.py と重複させぬのが
    本義だが、importできぬ環境でqualifyが機能停止するのを避けるための最終防波堤)。"""
    try:
        import chat_server
        uids = getattr(chat_server, "_SELF_UIDS", None)
        if uids:
            return {str(u) for u in uids}
    except Exception as e:
        print(f"[resolve._self_uids] chat_server._SELF_UIDS読取不可、fallback{{'101'}}を使用: "
              f"{type(e).__name__}: {e}", file=sys.stderr)
    return {"101"}  # fallback (chat_server.py _SELF_UIDS 読取不可時のみ使用)


def _load_roster(path=None):
    p = path or ROSTER_PATH
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _norm(s):
    return str(s).strip().lower()


def resolve(query, roster=None):
    """query(人名文字列) → dict{status, uid, name, candidates}。

    status:
      "unique"    — 完全一致(小文字化・前後空白除去)が唯一 → uid/name を返す
      "ambiguous" — 完全一致(正規化後)が name の重複により複数の uid にヒット
                    → candidates([{uid,name}, ...]) を返す・送らず停止
      "none"      — 完全一致が0件 → 送らず停止(部分一致へのフォールバックは行わぬ)
    """
    if roster is None:
        roster = _load_roster()
    q = _norm(query)
    hits = [{"uid": uid, "name": name} for uid, name in roster.items() if _norm(name) == q]
    if len(hits) == 1:
        return {"status": "unique", "uid": hits[0]["uid"], "name": hits[0]["name"], "candidates": hits}
    if len(hits) > 1:
        return {"status": "ambiguous", "uid": None, "name": None, "candidates": hits}
    return {"status": "none", "uid": None, "name": None, "candidates": []}


# ------------------------------------------------------------------
# D4是正: 資格三層(出所不在/is_active/形) + roster鮮度三値 + 自己宛送信の禁
# ------------------------------------------------------------------

def _fetch_live_users():
    """実ソース(/users?limit=200・casper_tools経由)を直接照会する。
    戻り値: {uid(str): {"username":..., "is_active":..., "name":...}} または例外送出。
    ★儀式: chat_server.py の _roster_refresh と同じエンドポイントを叩くが、
    ここでは is_active/username を保存する(_roster_refreshが捨てている属性)。"""
    import casper_tools
    d = casper_tools._get("/users?limit=200")
    items = d.get("items") or (d if isinstance(d, list) else [])
    out = {}
    for u in items:
        uid = u.get("id")
        if uid is None:
            continue
        out[str(uid)] = {
            "username": u.get("username") or u.get("name") or "",
            "is_active": bool(u.get("is_active", True)),
            "name": u.get("name") or u.get("full_name") or u.get("username") or str(uid),
        }
    return out


def get_roster_freshness(cache_path=None, now=None, live_fetch=None):
    """roster_cache.json の鮮度(fresh|stale)を記録用に判定しつつ、★D4是正
    (subtask_524_impl5): freshnessに関わらず常に実ソースへ引き直す。

    ★是正前の欠陥(将軍再検品・gunshi裏取り): fresh時は実ソースを引かず「形」層
    のみで判定していた——cacheが新しいほど検査が弱いという逆転構造。
    retired_user(uid50)・kato(uid54、いずれも出所不在)がfresh時にqualified=True
    で通っていた(将軍実測・gunshi追加発見)。

    是正後: fresh/staleはmtime記録(監査用の付帯情報)に留め、資格判定の分岐には
    使わない。実ソース照会が失敗した場合のみ unknown(答えられぬと名乗り停止)。

    戻り値: {"state": "fresh"|"stale"|"unknown", "live_users": dict|None,
             "mtime": float|None, "age_sec": float|None, "error": str|None}
    """
    p = cache_path or ROSTER_PATH
    now = time.time() if now is None else now
    fetch = live_fetch or _fetch_live_users
    try:
        mtime = os.path.getmtime(p)
        age = now - mtime
        state_label = "fresh" if age <= STALE_SECONDS else "stale"
    except OSError as e:
        mtime, age, state_label = None, None, "stale"
        print(f"[resolve.get_roster_freshness] roster_cache.json mtime読取不可"
              f"(記録用途のみ・資格判定には影響せぬ): {type(e).__name__}: {e}", file=sys.stderr)

    # ★資格層は常に実ソースを引く(fresh/staleで分岐しない)。
    try:
        live = fetch()
        if not live:
            raise ValueError("実ソースが空を返した")
        return {"state": state_label, "live_users": live, "mtime": mtime, "age_sec": age, "error": None}
    except Exception as e:
        return {"state": "unknown", "live_users": None, "mtime": mtime, "age_sec": age,
                "error": f"実ソース引き直し失敗: {type(e).__name__}: {e}"}


def _looks_service_like(username):
    """形の層: サービス/システム的な名前パターンを除外する。
    ★人が接頭辞を列挙するな(病五の入口)。「日本語を含むか」は入れない(過剰阻止=
    <社員名>等の実employeeを誤って弾く原因になる——これらの username
    フィールド自体はASCIIローマ字[<roster username 例: ASCIIローマ字>]であり、日本語が現れるのは
    表示名[full_name/name]側でしかない)。
    見るのは username フィールドの「形」のみ:
      - "@" を含む(メールアドレス形のサービスアカウント)
      - username 自体がASCIIでない(ログインハンドルとして体を成さぬ・
        実データではuid48「アプリ管理用」がこれに該当し、real employeeの
        username[<roster username 例: ASCIIローマ字>]はASCIIゆえ誤爆しない)
    """
    u = username or ""
    if "@" in u:
        return True
    if not u.isascii():
        return True
    return False


def qualified_resolve(query, actor_id=None, cache_path=None, live_fetch=None):
    """resolve() の結果に、D4是正の資格三層+自己宛送信の禁を重ねる。

    戻り値: dict{
      resolution: resolve()の三値dict,
      freshness: get_roster_freshness()の結果,
      qualified: True|False|None(freshness=unknownでresolution=uniqueの場合はNoneで停止),
      disqualify_reason: str|None,  # "absent_from_source"|"inactive"|"service_form"|"self_uid"
    }
    ★resolution.status != "unique" の場合はqualify判定自体を行わず、その場で停止する
    (①宛先解決の三値をこの層が上書きしない)。
    """
    resolution = resolve(query)
    if resolution["status"] != "unique":
        return {"resolution": resolution, "freshness": None, "qualified": False,
                "disqualify_reason": None}

    uid = resolution["uid"]

    # 自己宛送信の禁(actor_id一致 or Casper自身のuid) — 資格層の外で別建てに断つ(gunshi裁定)。
    self_uids = _self_uids()
    if actor_id is not None and str(actor_id) == str(uid):
        return {"resolution": resolution, "freshness": None, "qualified": False,
                "disqualify_reason": "self_send_actor_match"}
    if str(uid) in self_uids:
        return {"resolution": resolution, "freshness": None, "qualified": False,
                "disqualify_reason": "self_uid_casper"}

    # ★D4是正(subtask_524_impl5): freshnessに関わらず常に実ソースを引く
    # (fresh時だけ形の層に頼る旧分岐を廃止 — 「状態も全数通せ」gunshi自省)。
    fresh = get_roster_freshness(cache_path=cache_path, live_fetch=live_fetch)
    if fresh["state"] == "unknown":
        # 実ソース照会が失敗した場合のみ答えられぬと名乗り停止する(案C補完適用)。
        return {"resolution": resolution, "freshness": fresh, "qualified": None,
                "disqualify_reason": "roster_freshness_unknown"}

    # 実ソース(live_users)が手に入っている → 三層すべて適用可能。
    live = fresh["live_users"]
    rec = live.get(str(uid))
    if rec is None:
        return {"resolution": resolution, "freshness": fresh, "qualified": False,
                "disqualify_reason": "absent_from_source"}
    if not rec.get("is_active", True):
        return {"resolution": resolution, "freshness": fresh, "qualified": False,
                "disqualify_reason": "inactive"}
    if _looks_service_like(rec.get("username", "")):
        return {"resolution": resolution, "freshness": fresh, "qualified": False,
                "disqualify_reason": "service_form"}
    return {"resolution": resolution, "freshness": fresh, "qualified": True,
            "disqualify_reason": None}


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("usage: resolve.py <query>")
        raise SystemExit(1)
    print(json.dumps(resolve(sys.argv[1]), ensure_ascii=False, indent=2))
