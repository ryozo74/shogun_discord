#!/usr/bin/env bash
# tests/test_discord_routing.sh
# discord_listener.sh parse_messages の宛先ルーティング ユニットテスト
# SKIP=FAIL: このファイルに SKIP は許容しない

set -euo pipefail
PASS=0; FAIL=0

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Load .env if present (optional; test defaults used if vars absent)
set -a
[ -f "$SCRIPT_DIR/.env" ] && source "$SCRIPT_DIR/.env"
set +a

LORD_ID="${DISCORD_USER_ID:-test_lord_id_00001}"
BOT_ID="${DISCORD_BOT_USER_ID:-test_bot_id_00002}"
ROLE_ID="${DISCORD_SHOGUN_ROLE_ID:-}"

# Extract parse_messages function from discord_listener.sh (no full-script source)
PARSE_FUNC=$(sed -n '/^parse_messages()/,/^}$/p' "$SCRIPT_DIR/scripts/discord_listener.sh")

# run_test: $1=name $2=fixture_json_array $3=expect(process|skip) $4=multi_mode(true|false)
run_test() {
    local name="$1" fixture="$2" expect="$3" multi="${4:-true}"
    local result
    result=$(
        LORD_ID="$LORD_ID" \
        DISCORD_BOT_USER_ID="$BOT_ID" \
        DISCORD_SHOGUN_ROLE_ID="$ROLE_ID" \
        DISCORD_MULTI_SHOGUN="$multi" \
        bash -c "$PARSE_FUNC; parse_messages \"\$1\"" -- "$fixture" 2>/dev/null
    )
    if [ "$expect" = "process" ]; then
        # 処理対象: JSON メッセージ行（{で始まる行）が1件以上
        if echo "$result" | grep -q "^{"; then
            echo "✅ PASS: $name"
            PASS=$((PASS + 1))
        else
            echo "❌ FAIL: $name (expected process, got: [$result])"
            FAIL=$((FAIL + 1))
        fi
    else
        # skip 対象: JSON メッセージ行がゼロ件（SKIP: 行 or 空）
        if ! echo "$result" | grep -q "^{"; then
            echo "✅ PASS: $name"
            PASS=$((PASS + 1))
        else
            echo "❌ FAIL: $name (expected skip, got: [$result])"
            FAIL=$((FAIL + 1))
        fi
    fi
}

# run_reply_test: $1=name $2=fixture $3=expect_substr ('' = assert NO reply_to)
run_reply_test() {
    local name="$1" fixture="$2" want="$3" result
    result=$(
        LORD_ID="$LORD_ID" \
        DISCORD_BOT_USER_ID="$BOT_ID" \
        DISCORD_SHOGUN_ROLE_ID="$ROLE_ID" \
        DISCORD_MULTI_SHOGUN="true" \
        bash -c "$PARSE_FUNC; parse_messages \"\$1\"" -- "$fixture" 2>/dev/null
    )
    if [ -z "$want" ]; then
        if echo "$result" | grep -q "^{" && ! echo "$result" | grep -q '"reply_to"'; then
            echo "✅ PASS: $name"; PASS=$((PASS + 1))
        else
            echo "❌ FAIL: $name (expected no reply_to, got: [$result])"; FAIL=$((FAIL + 1))
        fi
    else
        if echo "$result" | grep -q '"reply_to"' && echo "$result" | grep -qF "$want"; then
            echo "✅ PASS: $name"; PASS=$((PASS + 1))
        else
            echo "❌ FAIL: $name (expected reply_to containing [$want], got: [$result])"; FAIL=$((FAIL + 1))
        fi
    fi
}

# ─── フィクスチャ定義（Discord API 実形式: JSON 配列）──────────────────────

# フィクスチャはシェル変数展開で構築（python3 への環境渡し不要）
mk_fixture() {
    python3 - "$@" <<'PY'
import sys, json
# args: id author_id mention_everyone mentions_bot_id(or '') stranger(bool)
args = sys.argv[1:]
msg_id, author_id, mention_everyone, mentions_bot_id = args[0], args[1], args[2]=='true', args[3]
mentions = [{'id': mentions_bot_id}] if mentions_bot_id else []
print(json.dumps([{
    'id': msg_id, 'author': {'id': author_id}, 'content': 'test',
    'mention_everyone': mention_everyone,
    'mentions': mentions, 'mention_roles': []
}]))
PY
}

# 自分宛てメンション（mentions に bot_id 含む）
FIXTURE_SELF=$(mk_fixture "111" "$LORD_ID" "false" "$BOT_ID")

# 他将軍のみ宛て（自分の bot_id は含まれない）
FIXTURE_OTHER=$(mk_fixture "222" "$LORD_ID" "false" "other_bot_id_99999")

# @everyone
FIXTURE_EVERYONE=$(mk_fixture "333" "$LORD_ID" "true" "")

# 無印（メンションなし）
FIXTURE_NOADR=$(mk_fixture "444" "$LORD_ID" "false" "")

# 殿以外の発言（author.id が lord_id と異なる）
FIXTURE_STRANGER=$(mk_fixture "555" "stranger_id_99998" "false" "$BOT_ID")

# クロス将軍参照: 殿が他将軍のコメントにリプライ＋自分宛メンション
FIXTURE_REPLY=$(python3 - "$LORD_ID" "$BOT_ID" <<'PY'
import sys, json
lord, bot = sys.argv[1], sys.argv[2]
print(json.dumps([{
    'id': '666', 'author': {'id': lord}, 'content': 'これどう思う？',
    'mention_everyone': False, 'mentions': [{'id': bot}], 'mention_roles': [],
    'referenced_message': {
        'author': {'username': 'shogun'},
        'content': 'REF-1ST-SHOGUN-OPINION'
    }
}]))
PY
)

# ─── テスト実行 ────────────────────────────────────────────────────────────

echo "=== テスト開始: DISCORD_MULTI_SHOGUN=true モード ==="

run_test "自分宛てメンション→処理"    "$FIXTURE_SELF"     "process" "true"
run_test "他将軍のみ宛て→skip"        "$FIXTURE_OTHER"    "skip"    "true"
run_test "@everyone→処理"             "$FIXTURE_EVERYONE" "process" "true"
run_test "無印(multi)→skip"           "$FIXTURE_NOADR"    "skip"    "true"
run_test "殿以外発言→skip"            "$FIXTURE_STRANGER" "skip"    "true"

echo ""
echo "=== テスト開始: DISCORD_MULTI_SHOGUN=false モード（後方互換）==="

run_test "無印(single)→処理"          "$FIXTURE_NOADR"    "process" "false"
run_test "殿以外発言(single)→skip"    "$FIXTURE_STRANGER" "skip"    "false"

echo ""
echo "=== テスト開始: クロス将軍参照 (referenced_message) ==="

run_reply_test "リプライ→reply_to に参照元author含む" "$FIXTURE_REPLY" "shogun"
run_reply_test "リプライ→reply_to に参照元content含む" "$FIXTURE_REPLY" "REF-1ST-SHOGUN-OPINION"
run_reply_test "非リプライ→reply_to を含まない(後方互換)" "$FIXTURE_SELF" ""

echo ""
echo "結果: PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ] && echo "✅ 全テスト PASS" || { echo "❌ FAIL あり (SKIP=FAIL)"; exit 1; }
