#!/usr/bin/env bash
# Casper auto-reload supervisor (殿御下命 2026-06-24「再起動しなくてもいい状態」)。
# ① 死活監視: 管理下の chat_server が落ちたら自動再起動。
# ② 自動リロード: chat_server.py の変更を検知したら自動で再起動(手動 pkill 不要)。
# ③ メンション番犬の死活も見る。
# ④ 【cmd_509第1便】前世代引き継ぎ: 起動時、自陣の前世代(孤児chat_server)が
#    ポートを握っていれば人手kill無しに引き継ぐ(casper_handoff.py・五点検証+TOCTOU対策)。
# 管理対象は本スクリプトが起動した子プロセスのみ(自分の子を扱う・他は触らぬ)。
# ★D006厳守: pkill/killall(名前照合)は永久禁止。casper_handoff.pyがverified pidに
#   SIGTERMのみを送る。SIGKILLへ自動昇格しない(退かねば報せて待つ)。
# 【cmd_509第2便・軍師QC条件1】環境変数で上書き可能に(既定値=現行値・後方互換)。
# ★軍師のROOTハードコード見落としで本番chat_serverを誤停止させた事故の再発防止
# (2026-08-18)。隔離試験は必ず CASPER_ROOT を本番と異なるパスへ指定して行うこと。
# 【cmd_518手当2b 改修④-1・Fable第二診地雷1】exec失敗時にbashが即死せぬよう先頭で設定。
# これがなければ check_self_generation_and_exec 内の `exec ... || { ...; }` の `||` は
# 効かず、exec失敗(バイナリ破損・権限剥奪等)でsupervisorプロセスそのものが消える。
shopt -s execfail

ROOT="${CASPER_ROOT:-/mnt/h/multi-agent-shogun-main}"
SCR="$ROOT/projects/casper/scripts"
# 【改修④-7・地雷7】cwdはexecを跨いで保存されるが、failover_probe_and_decideが
# cd "$SCR" したまま戻らぬため、周回によりexec時点のcwdが不定になる。起動時に固定する。
cd "$ROOT"
WATCH="$SCR/chat_server.py"   # 変更検知の代表(ログ表示用)
LOG="$ROOT/queue/casper_supervisor.log"
PIDFILE="$ROOT/queue/casper_chat_server.pid"
HANDOFF="$ROOT/scripts/casper_handoff.py"
FAILOVER="$SCR/casper_failover.py"    # 【cmd_509第2便】自動退避+breaker唯一台帳化
log(){ echo "[$(date '+%F %T')] $1" >> "$LOG"; }

# 【AC12/AC-G10】起動時に自分(このsupervisorが起動するchat_server.py)のsha256をログへ刻む。
# ★世代の判定を起動時刻やmtimeで代理しない(将軍が2026-08-17に誤った戒め)。一次証拠として残す。
log_sha256(){
  local sum
  sum="$(sha256sum "$SCR/chat_server.py" 2>/dev/null | awk '{print $1}')"
  log "起動時sha256(chat_server.py)=$sum"
}

# 【cmd_518手当3・AC-G10】supervisor自身も検知対象に含める(reloaderをreloadする者が
# 存在しないため、supervisor自身がずれても誰も気づかない構造への対策)。
# generation_drift_check.py --declare へ相乗りし、依存解決(案A/B/C)を二重実装しない
# (鉄則8箇条=件数と一覧は同一機構)。台帳(queue/generation_ledger.json)へ自分のsha256を
# 名乗るのみ・監査(sha比較)自体はsupervisorの外(cron側alert_dispatch.py)で行う。
declare_generation_sha(){
  python3 "$ROOT/scripts/generation_drift_check.py" --declare "$0" --pid "$$" >> "$LOG.generation_declare" 2>&1
}

# 【cmd_518手当2 項目B】supervisor自身の自己世代交代(self-exec)機構。
# ★配置の掟(絶対厳守): 本ファイル(casper_supervisor.sh)を決してin-place編集しない
#   運用とする(新ファイルを書いてmv/renameで置く)。bashは走行中の台本を遅延読みして
#   おり、in-place編集は旧世代の挙動を壊す。この掟はデプロイ手順側の規律であり、
#   本スクリプトはそれを前提に「置き換えられたこと」をshaで検知するだけの役割を持つ。
SELF_SCRIPT="$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null || echo "$ROOT/scripts/casper_supervisor.sh")"
GENERATION_FILE="$ROOT/queue/casper_supervisor.generation"
SUPERVISOR_STATE_FILE="$ROOT/queue/casper_supervisor.state"

self_sha(){ sha256sum "$SELF_SCRIPT" 2>/dev/null | awk '{print $1}'; }

# 【AC4】起動時にSELF_SHAを記録し、queue/casper_supervisor.generationへ自分を名乗る。
# ★原子書込(tmp→mv)で中断時の破損を避ける。
declare_self_generation(){
  local tmp
  tmp="$(mktemp "$ROOT/queue/.casper_supervisor.generation.XXXXXX")"
  python3 -c "
import json,sys
sha, ts, pid = sys.argv[1], sys.argv[2], sys.argv[3]
json.dump({'sha': sha, 'ts': int(ts), 'pid': int(pid)}, open(sys.argv[4], 'w'))
" "$SELF_SHA" "$(date +%s)" "$$" "$tmp" 2>>"$LOG.generation_declare"
  mv -f "$tmp" "$GENERATION_FILE"
  log "[self-exec] 世代を名乗った sha=${SELF_SHA:0:12}... pid=$$"
}

# 【AC5】静かな交代は禁物——log+inbox+Discordの三点で必ず誰かに伝わる形にする。
notify_self_exec(){
  local detail="$1"
  bash "$ROOT/scripts/inbox_write.sh" karo "casper_supervisor[自己世代交代]: ${detail}" escalation casper_supervisor 2>/dev/null || true
  bash "$ROOT/scripts/discord.sh" "🔄 Casper supervisor 自己世代交代: ${detail}" 2>/dev/null || true
}

# 【AC-B3・状態の引き継ぎ】exec直前にSRV_PID/WD_PID/SRV_SIG/fast_death_streakを書く。
save_handoff_state(){
  local tmp
  tmp="$(mktemp "$ROOT/queue/.casper_supervisor.state.XXXXXX")"
  python3 -c "
import json,sys
srv_pid, wd_pid, srv_sig, streak, ppid, ts = sys.argv[1:7]
json.dump({
    'srv_pid': int(srv_pid) if srv_pid else None,
    'wd_pid': int(wd_pid) if wd_pid else None,
    'srv_sig': srv_sig,
    'fast_death_streak': int(streak),
    'parent_pid': int(ppid),
    'ts': int(ts),
}, open(sys.argv[7], 'w'))
" "${SRV_PID:-}" "${WD_PID:-}" "${SRV_SIG:-}" "${fast_death_streak:-0}" "$$" "$(date +%s)" "$tmp" 2>>"$LOG.generation_declare"
  mv -f "$tmp" "$SUPERVISOR_STATE_FILE"
}

# 【項目B-3・養子縁組ロジック】起動側で呼ぶ。stateファイルがあり、記載pidが生きており
# 親(ppid)が自分自身なら、新規launchせずSRV_PID/WD_PIDを引き継ぐ。
# 戻り値: 0=引き継いだ(launch_server/launch_watchdogを呼んではならない)
#         1=引き継ぎ対象なし(通常通りlaunchせよ)
# ★★項目B追加要件(将軍発見の危険への対処・孤児番犬の畳み順序):
#   旧supervisorが自己execで消える際、旧番犬(WD_PID)は「supervisorの子」のまま新
#   supervisor(execなのでpidは変わらない)に引き継がれる——exec は pid を保存するため
#   子は迷子にならず、そのまま新世代の子であり続ける(要件4)。ゆえ「孤児番犬」が
#   生まれるのは exec 経路そのものではなく、旧世代プロセスが完全に終了してから
#   新プロセスが別途起動される場合(fork起動の再起動系)に限られる。本関数は両ケースを
#   カバーするため、養子縁組時に「既存WD_PIDが自分の子でない(ppidが自分でない)」場合は
#   先にSIGTERMで畳んでから新番犬を起こす順序を保証する。
adopt_prior_generation(){
  [ -f "$SUPERVISOR_STATE_FILE" ] || return 1
  local srv_pid wd_pid srv_sig streak parent_pid
  srv_pid="$(python3 -c "import json; d=json.load(open('$SUPERVISOR_STATE_FILE')); print(d.get('srv_pid') or '')" 2>/dev/null)"
  wd_pid="$(python3 -c "import json; d=json.load(open('$SUPERVISOR_STATE_FILE')); print(d.get('wd_pid') or '')" 2>/dev/null)"
  srv_sig="$(python3 -c "import json; d=json.load(open('$SUPERVISOR_STATE_FILE')); print(d.get('srv_sig') or '')" 2>/dev/null)"
  streak="$(python3 -c "import json; d=json.load(open('$SUPERVISOR_STATE_FILE')); print(d.get('fast_death_streak') or 0)" 2>/dev/null)"
  parent_pid="$(python3 -c "import json; d=json.load(open('$SUPERVISOR_STATE_FILE')); print(d.get('parent_pid') or '')" 2>/dev/null)"

  if [ -z "$srv_pid" ] || ! kill -0 "$srv_pid" 2>/dev/null; then
    log "[self-exec] state有りだがsrv_pid($srv_pid)不在。養子縁組せず通常起動する。"
    rm -f "$SUPERVISOR_STATE_FILE"
    return 1
  fi
  local actual_ppid
  actual_ppid="$(awk '{print $4}' "/proc/$srv_pid/stat" 2>/dev/null)"
  # exec後もpidは変わらないため、srv_pidが自分自身と一致するケース(exec直後の
  # 自己再launch)が本来の主経路。ppid照合はfork起動(親が自分)経由の養子縁組も
  # 許容するための保険。
  if [ "$srv_pid" != "$$" ] && [ "$actual_ppid" != "$$" ]; then
    log "[self-exec] state有りだがsrv_pid=$srv_pid のppid($actual_ppid)が自分($$)と不一致。養子縁組せず通常起動する。"
    rm -f "$SUPERVISOR_STATE_FILE"
    return 1
  fi
  SRV_PID="$srv_pid"
  SRV_SIG="$srv_sig"
  fast_death_streak="${streak:-0}"
  log "[self-exec] 前世代からSRV_PID=$SRV_PID sig=$SRV_SIG streak=$fast_death_streak を養子縁組で引き継いだ(pidは無停止・要件4)。"

  # ★孤児番犬の畳み順序: 引き継いだWD_PIDが自分の子(ppid==$$)でなければ、
  #   それはfork起動系の再起動を跨いだ孤児の可能性がある。先に検証つきで畳んでから
  #   新番犬を起こす(将軍指摘の危険への対処・手当4実施順序にも反映すべき設計)。
  if [ -n "$wd_pid" ] && kill -0 "$wd_pid" 2>/dev/null; then
    local wd_actual_ppid
    wd_actual_ppid="$(awk '{print $4}' "/proc/$wd_pid/stat" 2>/dev/null)"
    if [ "$wd_actual_ppid" = "$$" ]; then
      WD_PID="$wd_pid"
      log "[self-exec] 前世代からWD_PID=$WD_PID を養子縁組で引き継いだ(自分の子と確認済)。"
    else
      log "[self-exec] WD_PID=$wd_pid は自分の子でない(ppid=$wd_actual_ppid)。孤児の疑いあり——単一機構で検証・畳む。"
      resolve_orphan_watchdog_unified
      WD_PID=""
    fi
  else
    WD_PID=""
  fi
  rm -f "$SUPERVISOR_STATE_FILE"
  return 0
}

# 【cmd_518手当2b 改修①・★単一機構の原則】孤児番犬の検証→畳み→(呼び出し元が)起こす、の
# 「検証→畳み」部分を一関数に一本化。起動時経路(adopt_prior_generation)とループ③経路
# (watchdog死亡検知後の再起動判断)の双方がこれだけを呼ぶ——鉄則「件数と一覧は同一関数」。
# 甲(系譜=SUPERVISOR_STATE_FILEのwd_pid)・乙(flock保持者=mention_watchdog.lock)・
# 丙(owner欄=mention_watchdog_state.json)を信頼順に試す(casper_handoff.py側で実装)。
# 戻り値: 0=verified個体を畳めた、またはそもそも候補が居なかった(absent)→新番犬を起こしてよい
#         1=unverified/foreign、または畳めなかった→WD_BLOCKEDで待て(新番犬を起こすな)
resolve_orphan_watchdog_unified(){
  python3 "$ROOT/scripts/casper_handoff.py" resolve-orphan-watchdog \
    --script-name discord_mention_watchdog.py --root "$ROOT" \
    --lock-path "$ROOT/queue/mention_watchdog.lock" \
    --state-file "$SUPERVISOR_STATE_FILE" \
    --owner-state-file "$ROOT/queue/mention_watchdog_state.json" \
    --expect-ppid "$$" --term-wait 5 --log "$LOG" \
    > "$ROOT/queue/.resolve_orphan_watchdog.last.json" 2>> "$LOG.generation_declare"
  local rc=$?
  cat "$ROOT/queue/.resolve_orphan_watchdog.last.json" >> "$LOG.generation_declare" 2>/dev/null
  return $rc
}

# 【項目B-2】主ループ毎周でNOW_SHAをSELF_SHAと比較し、違えば自己世代交代する。
# ①bash -nで構文検問(壊れた台本へのexecはsupervisor死=全機構死に直結するため、
#   赤なら交代せず家老へ報せる・AC5=反証照会)。
# ②状態を書く③log+inbox+Discordで一報④execで自身を着替える(絶対パス使用・要件)。
SELF_EXEC_NOTIFIED=0
check_self_generation_and_exec(){
  local now_sha
  now_sha="$(self_sha)"
  [ -n "$now_sha" ] || return 0
  [ "$now_sha" = "$SELF_SHA" ] && return 0

  log "[self-exec] 自己sha変化検知 旧=${SELF_SHA:0:12}... 新=${now_sha:0:12}..."

  # ①構文検問。壊れた台本へのexecはsupervisor自身の死=全機構死に直結するため、
  #   赤なら交代せず家老へ報せるのみに留める(AC5=最重要の反証照会)。
  if ! bash -n "$SELF_SCRIPT" 2>>"$LOG"; then
    log "[self-exec] ★構文エラー検知。交代せず現世代のまま継続する(AC5)。家老へ報せる。"
    if [ "$SELF_EXEC_NOTIFIED" -ne 1 ]; then
      notify_self_exec "新しいcasper_supervisor.shに構文エラーあり。交代を見送り現行世代のまま稼働継続中。要修正: ${SELF_SCRIPT}"
      SELF_EXEC_NOTIFIED=1
    fi
    return 0
  fi
  SELF_EXEC_NOTIFIED=0

  # ②状態の引き継ぎを書く(exec後の自分がここから読む)。
  save_handoff_state

  # ③一報(静かな交代は禁物)。
  log "[self-exec] 構文OK。世代交代を実施する(pid=$$は不変・chat_server/watchdogは無停止のまま)。"
  notify_self_exec "世代交代を実施(pid=$$は不変)。旧sha=${SELF_SHA:0:12}... 新sha=${now_sha:0:12}..."

  # ④execで自身を着替える。★絶対パスを使う(failover_probe_and_decideがcd "$SCR"した
  #   まま戻らぬため、相対$0では踏み抜く)。
  # 【改修④-4・地雷4】fdはexecを跨いで継承される。孤児fdがtmux paneを指したままだと
  #   pane破棄でSIGPIPEの芽になるため、exec行でLOG/標準入力を明示的に付け替える。
  # 【改修④-1・地雷1・AC-D5実測で発覚した設計不備の是正】execfailは「execve()した
  #   実行対象そのものが起動できない」場合のみ捕捉できる。`exec /usr/bin/env bash
  #   "$SELF_SCRIPT"` はenvを実行対象としており、envは常に存在・実行可能なため
  #   execve自体は成功してしまい、envの内側でbashやSELF_SCRIPTが見つからず失敗しても
  #   その時点で旧プロセスは既に消えておりexecfailは効かない(実測で判明・合成反証で確認)。
  #   ★SELF_SCRIPT自身をshebang経由で直接exec対象にすることで、execve()の成否そのものを
  #   execfailで捕捉できる形にする。SELF_SCRIPT配置時は実行権限(+x)を維持すること。
  exec "$SELF_SCRIPT" >>"$LOG" 2>&1 </dev/null || {
    log "[self-exec] ★exec失敗・現世代で続行(execfail捕捉)。SELF_SCRIPT=${SELF_SCRIPT}"
    notify_self_exec "exec失敗により世代交代を見送り、現行世代のまま稼働継続中。要調査: ${SELF_SCRIPT}"
    return 0
  }
}

# 【cmd_507第1便】holdout測定とauto-reloadの干渉を断つロック。
# reports/_holdout.lock の1行目=epoch秒(ts)。run_holdout.py が測定中に設置し、
# 正常終了/シグナル/TTL(20分)のいずれかで必ず解ける(三重防御・AC2)。
# ★中身のtsを見る(mtimeは触られうるため見ない)。
HOLDOUT_LOCK="$SCR/reports/_holdout.lock"
HOLDOUT_LOCK_TTL=1200   # 20分。実測最長628秒(10.5分)の約2倍の余裕(軍師設計)。
holdout_lock_active(){
  # 戻り値0=保留すべき(ロック有効)。戻り値1=reload許可(ロック無し or TTL超過)。
  [ -f "$HOLDOUT_LOCK" ] || return 1
  local ts now age
  ts="$(head -n1 "$HOLDOUT_LOCK" 2>/dev/null | tr -cd '0-9')"
  [ -n "$ts" ] || return 1
  now="$(date +%s)"
  age=$((now - ts))
  if [ "$age" -le "$HOLDOUT_LOCK_TTL" ]; then
    log "測定中につきreload保留(残り$((HOLDOUT_LOCK_TTL - age))秒)"
    return 0
  fi
  log "[reload] ロックがTTL(20分)を超過。無効と見なしreloadを実施(pid=$SRV_PID)"
  return 1
}
# 【chat_server.py だけでは足りぬ】casper_dropbox.py 等の兄弟モジュールは起動時に import され、
# それらを直しても chat_server.py が変わらねば再読込されず「直したのに効かぬ」状態が続く
# (実測2026-07-29: Dropboxのdl=1修正が反映されず、殿の環境で旧挙動のまま出ていた)。
# ゆえ scripts 直下の *.py 全ての mtime 合算を署名とする(サブディレクトリは対象外=索引等の巨大物を避ける)。
# 【cmd_520第1便】test_*.py / gate_*.py は本番実行時にimportされない(chat_server.pyの
# import文を機械確認済・grep -rn "^import |^from " で0件)ため対象から除外。編集のみで
# auto-reloadが誤発火する事故(cmd_510検品時に三便中三便で再発)を断つ。
sig(){ find "$SCR" -maxdepth 1 -name '*.py' ! -name 'test_*.py' ! -name 'gate_*.py' -print0 2>/dev/null | xargs -0 stat -c %Y 2>/dev/null | awk '{s+=$1} END{print s}'; }

# 【cmd_518手当2 項目B-6・病A-2の穴】WD_SIG: 番犬(discord_mention_watchdog.py)と
# casper_handoff.pyの署名(mtime)を、sig()(chat_server系)とは別に監視する。
# ★★手当1(state原子化・limit50・flock)完了後もデフォルト無効で提出する。
#   有効化のタイミングはkaroが判断する(WD_SIG_ENABLEDで切替・既定=0)。
WD_SIG_ENABLED="${CASPER_WD_SIG_ENABLED:-0}"
wd_sig(){ stat -c %Y "$WD_SCRIPT" "$HANDOFF" 2>/dev/null | awk '{s+=$1} END{print s}'; }

# 【改修④-6・地雷6】execで起こる新世代のbashは環境変数(export済)のみ引き継ぎ、
#   シェル変数は引き継がない。casper_endpoints.envは台本冒頭で毎回re-sourceされる
#   ため「幽霊値」の懸念はない——ただし当該envファイルから行を削除した場合、
#   OS環境にexport済の旧値は new process でも生き続けうる(: "${VAR:=default}"は
#   既存値を上書きせぬ)。運用上、envファイルの値変更で足り、削除運用はしないこと。
# 【改修④-5・地雷5】supervisor自身はflockを保持しない設計(番犬側のみflock)。
#   将来supervisor自身にflockを入れる場合はfd番号を固定(exec 9>lockfile)し、
#   新世代が同じfdを認識できる形にすること。★Python側(番犬)はopenがCLOEXEC既定で
#   execを跨がないため逆の性質——混同するな。
# 【外部依存先は一箇所から】z8a 移設に備え、宛先は casper_endpoints.env を正とする
# (殿御下命 2026-08-03)。ここに焼かず、env を書き換えるだけで移せるようにする。
# 未設定・ファイル欠落時は従来値へ退避(後方互換)。
if [ -f "$SCR/casper_endpoints.env" ]; then
  set -a; . "$SCR/casper_endpoints.env"; set +a
fi
: "${CASPER_OLLAMA:=http://192.168.44.119:11434}"
: "${CASPER_MODEL:=qwen3.6:27b}"
: "${CASPER_PORT:=8770}"
: "${CASPER_HOME_OLLAMA:=http://192.168.44.139:11434}"

# 【cmd_509第2便】起動時、breaker.json中の旧key("z8a")を検出したらログへ刻むのみ
# (新keyへは引き継がない・古い判定を新しい宛先へ持ち越さぬ)。
# ★台帳を読む口はcasper_breaker.pyただ一つ。shellからbreaker.jsonを直接パースしない。
log_legacy_breaker_keys(){
  local legacy
  legacy="$(cd "$SCR" && python3 -c "import casper_breaker as B; print(','.join(B.detect_legacy_keys()))" 2>/dev/null)"
  if [ -n "$legacy" ]; then
    log "[breaker] 旧key検出: ${legacy} (新keyへは引き継がない・新規にgreenから開始する)"
  fi
}

# 【cmd_509第2便】三層probeのうち定常/候補をsupervisorのループから駆動。
# ★supervisor自身は閾値を持たず、record()を流すだけ(判断はallow()/state())。
# ★HOME(CASPER_HOME_OLLAMA・固定台帳)とACTIVE(CASPER_OLLAMA・実効宛先)は別概念。
#   退避中もHOMEを常時probeし続けねば復旧を検知できない(sandbox実測で判明した初版の欠陥)。
FAILOVER_PROBE_TICK=0        # 8秒ループの何回に1回probeを打つかのカウンタ(32秒間隔=4ループに1回)
FAILOVER_PROBE_EVERY=4
HOME_HOSTPORT="${CASPER_HOME_OLLAMA#http://}"
HOME_HOSTPORT="${HOME_HOSTPORT#https://}"

# 【2026-08-24 新設】退避先候補(CASPER_ALT_OLLAMA・カンマ区切りの host:port)。
# ★ACTIVEとHOMEの二点しか知らぬ機構は、HOME自身が死ぬ時に袋小路へ入る
#   (2026-08-24 12:00 実害: HOME(.139)電源断・.119は健在なのに逃げ先が候補に無く退避できず)。
ALT_HOSTPORTS=()
if [ -n "${CASPER_ALT_OLLAMA:-}" ]; then
  IFS=',' read -r -a ALT_HOSTPORTS <<< "$CASPER_ALT_OLLAMA"
fi

# 【2026-08-24 新設】台帳(env)と【走行実体】の座席が食い違っていないかを毎周回照合する。
# ★env再読込だけでは足りぬ——supervisorが新しい座席を知っていても、既に走っている
#   chat_server は起動時の座席を握ったままである(実害: 2026-08-24 17:02、台帳はclaude_cliなのに
#   実体はollama/.119 のまま動き続け、殿が別作業へ回された z8a を使い続けた)。
# ★実体の座席は /proc/PID/environ を【直に読む】。起動時刻やログでの推定(代理証拠)はしない。
SEAT_FIX_TRIES=0
SEAT_FIX_MAX=3

srv_seat_now(){
  local pid="$1" e b o m
  if [ -z "$pid" ] || [ ! -r "/proc/$pid/environ" ]; then echo "||"; return; fi
  e="$(tr '\0' '\n' < "/proc/$pid/environ" 2>/dev/null)"
  b="$(printf '%s\n' "$e" | sed -n 's/^CASPER_BACKEND=//p' | head -1)"; b="${b:-ollama}"
  o="$(printf '%s\n' "$e" | sed -n 's/^CASPER_OLLAMA=//p' | head -1)"
  m="$(printf '%s\n' "$e" | sed -n 's/^CASPER_MODEL=//p' | head -1)"
  echo "${b}|${o}|${m}"
}

ensure_seat_matches_ledger(){
  kill -0 "$SRV_PID" 2>/dev/null || return 0
  local want have
  want="${CASPER_BACKEND:-ollama}|${CASPER_OLLAMA}|${CASPER_MODEL}"
  have="$(srv_seat_now "$SRV_PID")"
  if [ "$want" = "$have" ]; then SEAT_FIX_TRIES=0; return 0; fi
  if [ "$SEAT_FIX_TRIES" -ge "$SEAT_FIX_MAX" ]; then
    # ★no silent caps: 諦めた事実と回数を必ず名乗る(黙って食い違いを放置せぬ)。
    if [ "$SEAT_FIX_TRIES" -eq "$SEAT_FIX_MAX" ]; then
      log "[seat] ★${SEAT_FIX_MAX}回起こし直しても座席が台帳に一致せぬ。誤爆を避け以後は報せて待つ。実体[${have}] 台帳[${want}]"
      bash "$ROOT/scripts/inbox_write.sh" karo \
        "casper_supervisor[座席不一致]: chat_serverの座席が台帳と${SEAT_FIX_MAX}回一致せず。実体[${have}] 台帳[${want}]。人の目が要る。" \
        escalation casper_supervisor 2>/dev/null || true
      SEAT_FIX_TRIES=$((SEAT_FIX_TRIES + 1))
    fi
    return 0
  fi
  SEAT_FIX_TRIES=$((SEAT_FIX_TRIES + 1))
  log "[seat] 走行中chat_serverの座席が台帳と食い違う(${SEAT_FIX_TRIES}/${SEAT_FIX_MAX}): 実体[${have}] 台帳[${want}]。起こし直す。"
  kill "$SRV_PID" 2>/dev/null; sleep 2; launch_server
  handle_fast_death_and_relaunch
}

# 【2026-08-24 新設】casper_endpoints.env の変更に走行中も追随する。
# ★これが無かったために、env(台帳)を書き換えても走行中のsupervisorが起動時の写しを
#   握り続け、「書き換えたのに座席が変わらぬ」が繰り返された(2026-08-21の失敗と同型)。
#   台帳が正であるなら、機構は台帳を読み直し続けねばならぬ。
ENV_FILE_PATH="$SCR/casper_endpoints.env"
ENV_MTIME_SEEN="$(stat -c %Y "$ENV_FILE_PATH" 2>/dev/null || echo 0)"

resync_env_if_changed(){
  local m; m="$(stat -c %Y "$ENV_FILE_PATH" 2>/dev/null || echo 0)"
  [ "$m" = "$ENV_MTIME_SEEN" ] && return 0
  ENV_MTIME_SEEN="$m"
  local b_backend="${CASPER_BACKEND:-ollama}" b_ollama="$CASPER_OLLAMA" b_model="$CASPER_MODEL"
  set -a; . "$ENV_FILE_PATH"; set +a
  # 席表・禁足・雲の可否を読み直す(古い配列を握り続けぬ)
  HOME_HOSTPORT="${CASPER_HOME_OLLAMA#http://}"; HOME_HOSTPORT="${HOME_HOSTPORT#https://}"
  ALT_HOSTPORTS=()
  [ -n "${CASPER_ALT_OLLAMA:-}" ] && IFS=',' read -r -a ALT_HOSTPORTS <<< "$CASPER_ALT_OLLAMA"
  FORBIDDEN_SEATS=()
  [ -n "${CASPER_FORBIDDEN_SEATS:-}" ] && IFS=',' read -r -a FORBIDDEN_SEATS <<< "$CASPER_FORBIDDEN_SEATS"
  CLOUD_FALLBACK="${CASPER_CLOUD_FALLBACK:-1}"
  log "[env] casper_endpoints.env の変更を検知→再読込(backend=${CASPER_BACKEND:-ollama} 宛先=${CASPER_OLLAMA} 模型=${CASPER_MODEL} 禁足=${CASPER_FORBIDDEN_SEATS:-無})"
  if [ "${CASPER_BACKEND:-ollama}" != "$b_backend" ] || [ "$CASPER_OLLAMA" != "$b_ollama" ] \
     || [ "$CASPER_MODEL" != "$b_model" ]; then
    log "[env] 座席が変わった(旧: backend=${b_backend} 宛先=${b_ollama} 模型=${b_model})。chat_serverを起こし直す。"
    if kill -0 "$SRV_PID" 2>/dev/null; then
      kill "$SRV_PID" 2>/dev/null; sleep 2; launch_server
      handle_fast_death_and_relaunch
    fi
  fi
}

# 【殿御下命 2026-08-24】席の禁足リスト。ここに挙げた host:port へは【何があっても座らぬ】。
# ★z8a(.119)は別の作業へ回された。機構が勝手に戻れば殿の作業を圧迫する。
#   言葉の約束でなく機構で禁ずる(env が誤ってその宛先を指しても、席として選ばぬ)。
FORBIDDEN_SEATS=()
if [ -n "${CASPER_FORBIDDEN_SEATS:-}" ]; then
  IFS=',' read -r -a FORBIDDEN_SEATS <<< "$CASPER_FORBIDDEN_SEATS"
fi

seat_is_forbidden(){
  local seat="$1" f
  for f in "${FORBIDDEN_SEATS[@]}"; do
    f="$(echo "$f" | tr -d '[:space:]')"
    [ -n "$f" ] || continue
    [ "$seat" = "$f" ] && return 0
  done
  return 1
}

# 宛先1つのbreaker状態を返す。$1=host:port $2=gen|emb
endpoint_breaker_state(){
  local hp="$1" kind="$2"
  (cd "$SCR" && python3 -c "
import casper_breaker as B
h, p = '$hp'.split(':', 1)
print(B.state(B.gen_key(h, p) if '$kind' == 'gen' else B.emb_key(h, p)))
" 2>/dev/null)
}

# 【殿御裁可2026-08-24・甲】最下段の座席=雲(claude_cli/Sonnet)。
# GPUの席(現宛先/HOME/候補)が一つも緑でない時だけ座る。雲は救命艇であって住処ではない。
# ★雲に居る間、社の情報はAnthropicを経由する。出た内容は casper_cloud_ledger が
#   一件残らず帳簿(scripts/casper_cloud_ledger.jsonl)へ刻む(殿御下命: 頻度と内容を後で検分)。
# 0にすると降段しない(全滅時は答えられぬまま待つ)。
CLOUD_FALLBACK="${CASPER_CLOUD_FALLBACK:-1}"
CLOUD_RETURN_TICK=0
CLOUD_RETURN_EVERY=10          # 雲に居る間、この回数ごとにGPUの席の生成probeを試す(約5分毎)

# 座席の変更(ローカル推論⇄雲)。env書換→再読込→chat_server再起動→報せ。
do_backend_switch(){
  local to="$1" reason="$2"
  python3 "$FAILOVER" set-backend --to "$to" --reason "$reason" >> "$LOG.failover" 2>&1
  set -a; . "$SCR/casper_endpoints.env"; set +a
  log "[failover] 座席変更: backend=${to} — ${reason}"
  if kill -0 "$SRV_PID" 2>/dev/null; then
    log "[failover] 新しい座席を反映するためchat_server再起動 (停止 $SRV_PID)"
    kill "$SRV_PID" 2>/dev/null; sleep 2; launch_server
    handle_fast_death_and_relaunch
  fi
  ENV_MTIME_SEEN="$(stat -c %Y "$ENV_FILE_PATH" 2>/dev/null || echo 0)"   # 自らの書換で二重再起動せぬ
  if [ "$to" = "claude_cli" ]; then
    notify_failover_event "雲へ降段(最下段の座席)" "GPUの席が一つも緑でないため雲(claude_cli/Sonnet)へ自動降段した。★この間、社の情報はAnthropicを経由する。出た内容は全件記帳される(確認: cd projects/casper/scripts && python3 casper_cloud_ledger.py report)。★縮退: 道具(MCP)は雲では呼べず機構の先読み注入のみ／意味検索は埋込機が要るため字面検索へ落ちうる。理由: ${reason}"
  else
    notify_failover_event "雲から復席" "GPUの席が緑に戻ったゆえローカル推論へ復した。理由: ${reason}"
  fi
}

# 雲に居る間: GPUの席が緑に戻ったら復席する(雲へ座りっぱなしにせぬ)。
# ★生成probeは高価(冷間120秒待ち)ゆえ毎周回はせず CLOUD_RETURN_EVERY 回に一度。
cloud_return_check(){
  CLOUD_RETURN_TICK=$((CLOUD_RETURN_TICK + 1))
  [ $((CLOUD_RETURN_TICK % CLOUD_RETURN_EVERY)) -ne 0 ] && return 0
  local seat tried="" g e seen=""
  for seat in "$HOME_HOSTPORT" "${ALT_HOSTPORTS[@]}"; do
    seat="$(echo "$seat" | tr -d '[:space:]')"
    [ -n "$seat" ] || continue
    case " $seen " in *" $seat "*) continue ;; esac      # 重複(HOME==候補)は一度だけ
    seen="$seen $seat"
    if seat_is_forbidden "$seat"; then tried="${tried}${seat}=禁足席(殿御下命); "; continue; fi
    python3 "$FAILOVER" probe-generate --target "$seat" >> "$LOG.failover" 2>&1
    g="$(endpoint_breaker_state "$seat" gen)"
    e="$(endpoint_breaker_state "$seat" emb)"
    if [ "$g" = "green" ] && [ "$e" != "red" ]; then
      log "[failover] GPUの席(${seat})が緑に戻った。雲から復席する。"
      python3 "$FAILOVER" switch --to "$seat" --reason "return_from_cloud" >> "$LOG.failover" 2>&1
      do_backend_switch "ollama" "GPUの席(${seat})が緑に戻ったゆえ復席"
      return 0
    fi
    tried="${tried}${seat}=gen:${g}/emb:${e}; "
  done
  # ★no silent caps: 雲に座り続けている事実と、その理由を毎回名乗る(黙って雲に居着かぬ)。
  log "[failover] 雲に着座中。GPUの席は依然すべて赤(${tried:-候補なし})。復席せず継続。"
}

failover_probe_and_decide(){
  cd "$SCR"
  # 【雲に着座中】ollama宛先が赤なのは当然ゆえ decide は回さず、復席の見張りのみ行う。
  if [ "${CASPER_BACKEND:-ollama}" = "claude_cli" ]; then
    # ★2026-08-24 是正: 雲に居る間もHOMEへ /api/tags probe を【毎周回】打つ。
    #   これが無いと emb key を誰も叩かず、fails が積もったまま永久に赤で居座り、
    #   復席条件(gen緑 ∧ emb非赤)が原理的に満たせなくなる(実害: .139が復電しても
    #   機構が戻れず、emb:.139 が fails=63/oks=0 のまま固着した)。
    #   /api/tags は行列を通らぬゆえ安価。生成probe(高価)は cloud_return_check 側で間引く。
    python3 "$FAILOVER" probe-home >> "$LOG.failover" 2>&1
    cloud_return_check
    return 0
  fi
  # 定常probe(ACTIVEへ1トークン生成)+HOME probe(/api/tagsのみ・在庫照合・常時実施)
  python3 "$FAILOVER" probe-active >> "$LOG.failover" 2>&1
  python3 "$FAILOVER" probe-home >> "$LOG.failover" 2>&1

  local decision
  decision="$(python3 "$FAILOVER" decide 2>>"$LOG.failover")"
  echo "$decision" >> "$LOG.failover"

  local action
  action="$(echo "$decision" | python3 -c "import json,sys; print(json.load(sys.stdin).get('action',''))" 2>/dev/null)"

  case "$action" in
    evacuate_needed)
      # ★切替判断時のみ: HOMEへ生成probe(timeout120秒・冷間ロードを待つ)。
      #   HOMEも不通ならば「退避先が無い」ため現状維持のうえ報せる(AC4)。
      python3 "$FAILOVER" probe-generate --target "$HOME_HOSTPORT" >> "$LOG.failover" 2>&1
      local home_gen_state home_emb_state
      home_gen_state="$(cd "$SCR" && python3 -c "
import casper_breaker as B
print(B.state(B.gen_key(*'$HOME_HOSTPORT'.split(':',1))))
" 2>/dev/null)"
      home_emb_state="$(cd "$SCR" && python3 -c "
import casper_breaker as B
print(B.state(B.emb_key(*'$HOME_HOSTPORT'.split(':',1))))
" 2>/dev/null)"
      if [ "$HOME_HOSTPORT" != "${CASPER_OLLAMA#http://}" ] && ! seat_is_forbidden "$HOME_HOSTPORT" \
         && [ "$home_gen_state" = "green" ] && [ "$home_emb_state" != "red" ]; then
        do_failover_switch "$HOME_HOSTPORT" "evacuate" "現在の宛先(${CASPER_OLLAMA})不通(breaker red・連続失敗)"
      else
        # 【2026-08-24 新設】HOMEも駄目な時、候補(CASPER_ALT_OLLAMA)を上から試す。
        # ★ここが無かったために、HOMEが死んだ日に機構は「逃げ先が無い」と申したまま止まった。
        local active_hostport tried_report="" cand cand_gen cand_emb switched=0
        active_hostport="${CASPER_OLLAMA#http://}"
        active_hostport="${active_hostport#https://}"
        for cand in "${ALT_HOSTPORTS[@]}"; do
          cand="$(echo "$cand" | tr -d '[:space:]')"
          [ -n "$cand" ] || continue
          if [ "$cand" = "$active_hostport" ]; then tried_report="${tried_report}${cand}=現宛先ゆえ飛ばす; "; continue; fi
          if [ "$cand" = "$HOME_HOSTPORT" ]; then tried_report="${tried_report}${cand}=HOMEと同一(検査済); "; continue; fi
          if seat_is_forbidden "$cand"; then tried_report="${tried_report}${cand}=禁足席(殿御下命)ゆえ座らぬ; "; continue; fi
          log "[failover] 退避先候補を試す: ${cand}"
          python3 "$FAILOVER" probe-generate --target "$cand" >> "$LOG.failover" 2>&1
          cand_gen="$(endpoint_breaker_state "$cand" gen)"
          cand_emb="$(endpoint_breaker_state "$cand" emb)"
          if [ "$cand_gen" = "green" ] && [ "$cand_emb" != "red" ]; then
            do_failover_switch "$cand" "evacuate_alt" "現宛先(${CASPER_OLLAMA})もHOME(${CASPER_HOME_OLLAMA})も不通。候補${cand}が緑ゆえ退避する。"
            switched=1
            break
          fi
          tried_report="${tried_report}${cand}=gen:${cand_gen}/emb:${cand_emb}; "
        done
        if [ "$switched" -eq 0 ]; then
          # ★no silent caps: 何を試して何故駄目だったかを必ず並べる(黙って諦めぬ)。
          log "[failover] 現宛先(${CASPER_OLLAMA})・HOME(${CASPER_HOME_OLLAMA})・候補すべて不通/在庫欠如(home_gen=${home_gen_state} home_emb=${home_emb_state} / 候補: ${tried_report:-無し})。"
          # 【殿御裁可2026-08-24・甲】GPUの席が一つも無い=最下段の座席(雲)へ降段する。
          # ★ここへ来るのは物理GPUが全滅した時のみ。雲だけがLANのGPUに依存せぬ席である。
          if [ "$CLOUD_FALLBACK" = "1" ]; then
            do_backend_switch "claude_cli" "現宛先(${CASPER_OLLAMA})・HOME(${CASPER_HOME_OLLAMA})・候補すべて赤(${tried_report:-候補なし})"
          else
            notify_failover_event "退避見送り" "現在の宛先(${CASPER_OLLAMA})・HOME(${CASPER_HOME_OLLAMA})・退避先候補のいずれも使えぬ。雲への降段は CASPER_CLOUD_FALLBACK=0 ゆえ行わぬ。現状を保つ。試した候補: ${tried_report:-無し(CASPER_ALT_OLLAMA未設定)}"
          fi
        fi
      fi
      ;;
    return_home)
      do_failover_switch "$HOME_HOSTPORT" "return_home" "HOME(${CASPER_HOME_OLLAMA})復帰(三条件AND充足)"
      ;;
    cap_reached)
      log "[failover] 切替回数の毎時上限に到達。現状固定。"
      notify_failover_event "切替上限到達" "毎時1回の切替上限に達したため、現状(${CASPER_OLLAMA})を固定した。"
      ;;
    *) : ;;
  esac
}

# 実際の切替: env書換(casper_failover.py switch)→管理下chat_server再起動→報せ(inbox+Discord)。
do_failover_switch(){
  local target_hostport="$1" reason_tag="$2" reason_text="$3"
  local before="$CASPER_OLLAMA"
  local sw_out
  sw_out="$(python3 "$FAILOVER" switch --to "$target_hostport" --reason "$reason_tag" 2>>"$LOG.failover")"
  echo "$sw_out" >> "$LOG.failover"
  # envを再読込(次回launch_serverから新宛先を使う)
  set -a; . "$SCR/casper_endpoints.env"; set +a
  log "[failover] 切替実施: ${before} → http://${target_hostport} (${reason_tag}) — ${reason_text}"
  # 現在稼働中のchat_serverへ新宛先を反映させるため再起動させる(sig変更なしでも明示kill)。
  if kill -0 "$SRV_PID" 2>/dev/null; then
    log "[failover] 新宛先反映のためchat_server再起動 (停止 $SRV_PID)"
    kill "$SRV_PID" 2>/dev/null; sleep 2; launch_server
    handle_fast_death_and_relaunch
  fi
  ENV_MTIME_SEEN="$(stat -c %Y "$ENV_FILE_PATH" 2>/dev/null || echo 0)"   # 自らの書換で二重再起動せぬ
  notify_failover_event "宛先切替" "いつ: $(date '+%F %T') / どこから: ${before} / どこへ: http://${target_hostport} / なぜ: ${reason_text} / 現在の速度: $([ "$target_hostport" = "$HOME_HOSTPORT" ] && echo 'HOMEへ復帰済' || echo '退避先は本命より遅い場合あり(実測に基づき別途報告)')"
}

# 【AC5】報せは家老inbox + Discordの双方(切替時に「いつ・どこから・どこへ・なぜ・現在の速度」を含める)。
notify_failover_event(){
  local title="$1" detail="$2"
  bash "$ROOT/scripts/inbox_write.sh" karo "casper_supervisor[自動退避]: ${title}。${detail}" escalation casper_supervisor 2>/dev/null || true
  bash "$ROOT/scripts/discord.sh" "🔀 Casper自動退避: ${title}\n${detail}" 2>/dev/null || true
}

# 【cmd_509第1便】前世代の畳み口。戻り値:
#   0 = 先客なし、または引き継ぎ完了(launch可)
#   1 = 別プロセス/検証不一致/TOCTOU不一致 につき停止せず報せて待つ(launch不可)
#   2 = verified pidにSIGTERM送信も退かず(SIGKILLへ自動昇格しない・launch不可)
# ★③(TOCTOU再照合)と④(SIGTERM)の間に他処理を挟まぬ実装はcasper_handoff.py側で担保。
handoff_prior_generation(){
  python3 "$HANDOFF" verify-and-terminate --port "$CASPER_PORT" \
    --pidfile "$PIDFILE" --root "$ROOT" --script-name chat_server.py \
    --term-wait 10 --log "$LOG"
  return $?
}

HANDOFF_BLOCKED=0            # 1=前世代引き継ぎ不可で待機中(AC2/AC10)。SRV_PIDは未起動のまま。
HANDOFF_BLOCKED_NOTIFIED=0   # 二重報告防止(状態が変わらぬ限り一度だけ報せる)

# 【cmd_518手当2b 改修②不変条件・HANDOFF_BLOCKEDと同型】1=新番犬を起こさず待機中
# (★不変条件: 畳めぬなら起こすな。片肺は病、二匹は死)。
# WD_BLOCKED_REASON: "orphan"=旧個体をunverified/foreignで畳めなかった
#   (再検証すれば解ける可能性がある→resolve_orphan_watchdog_unifiedで定期再確認)
#   "config"=config_missingで respawn自体が無意味(オペレータが.env等を直すまで
#   再検証しても解けない→孤児検証を呼ばず、ただ待って報せるのみ)。
WD_BLOCKED=0
WD_BLOCKED_REASON=""
WD_BLOCKED_NOTIFIED=0
WD_BLOCKED_RETRY_SEC=30

# 【AC11】bind失敗の無限ループ是正。launch_server内の定着確認(下記)がFAST_DEATH_SEC以内の
# 即死を検知した場合、「bind失敗の疑いあり」とみなし指数backoff(8→16→32→64秒)を挟む。
# 試行上限到達でループを抜け、家老へ報せる(このループ自体は無限に高速回転しない)。
FAST_DEATH_SEC=3          # この秒数以内の死亡は「即死=bind失敗疑い」とみなす
BACKOFF_SEQUENCE=(8 16 32 64)
MAX_FAST_DEATH_STREAK=8   # 連続即死8回(backoffで最長でも数分以内)で見切り、報告して止める
fast_death_streak=0
SRV_FAST_DEATH=0

launch_server(){
  cd "$ROOT"
  handoff_prior_generation
  local hrc=$?
  if [ "$hrc" -ne 0 ]; then
    log "[handoff] 前世代の引き継ぎ不可(rc=$hrc)。停止せず報せて待つ(AC2/AC10)。launchを見送る。"
    HANDOFF_BLOCKED=1
    if [ "$HANDOFF_BLOCKED_NOTIFIED" -eq 0 ]; then
      bash "$ROOT/scripts/inbox_write.sh" karo \
        "casper_supervisor: 前世代引き継ぎ不可(rc=${hrc})でchat_server起動を見送り待機中。ポート${CASPER_PORT}を確認されたし。誤爆防止のため機構は停止せず待っている。ログ: ${LOG}" \
        escalation casper_supervisor 2>/dev/null || true
      HANDOFF_BLOCKED_NOTIFIED=1
    fi
    return 1
  fi
  HANDOFF_BLOCKED=0
  HANDOFF_BLOCKED_NOTIFIED=0
  CASPER_PIDFILE="$PIDFILE" nohup python3 "$SCR/chat_server.py" --endpoint "$CASPER_OLLAMA" \
    --model "$CASPER_MODEL" --port "$CASPER_PORT" > "$SCR/casper_server.log" 2>&1 &
  SRV_PID=$!; SRV_SIG="$(sig)"
  SRV_LAUNCH_TS=$(date +%s)
  log "server launch pid=$SRV_PID sig=$SRV_SIG"
  # 【AC11】即死(bind失敗等)を主ループの sleep 8 の周期に頼らず素早く検知するための
  # 短い定着確認。ここで死んでいれば FAST_DEATH_SEC 以内の即死として扱う
  # (主ループの kill -0 だけに頼ると、死亡が判明するのは常に次の sleep 8 後になり
  #  経過時間が実際の生存時間でなく「ポーリング周期」を測ってしまう欠陥がある)。
  sleep "$FAST_DEATH_SEC"
  if ! kill -0 "$SRV_PID" 2>/dev/null; then
    SRV_FAST_DEATH=1
  else
    SRV_FAST_DEATH=0
  fi
  return 0
}
WD_SCRIPT="$ROOT/scripts/discord_mention_watchdog.py"

# 【cmd_518手当2 AC-B7・将軍発見の危険への対処】launch_watchdogにも
# chat_serverと同型の即死対策(backoff)を実装する。
# ★★exit 0(flock取得失敗=先客あり=正常終了)と異常死を★別の出口として扱う——
# 世代交代直後、旧番犬が生きたまま新番犬が起きると新番犬はflockを取れずexit 0で
# 即座に死ぬ。これを「番犬が死に続けておる」と報告すると読む者が真因を誤る
# (cmd_512の門の五番目=その赤は読めるか、に相当)。
WD_FAST_DEATH_SEC=3
WD_BACKOFF_SEQUENCE=(8 16 32 64)
WD_MAX_FAST_DEATH_STREAK=8
wd_fast_death_streak=0
WD_FAST_DEATH=0
WD_LAST_EXIT_CODE=0

# 【cmd_518手当2b 改修③】死因台帳(queue/mention_watchdog_exit.json)を読む。
# ★pidがWD_PIDと一致しtsが直近のもののみ信用(古い記録に惑わされるな)。
# 足軽3号の実装(subtask_518_impl6)が完了するまでファイル不在の前提でも動く
# (ファイル無し=情報なし=fast-death扱いにフォールバック)。
EXIT_LEDGER="$ROOT/queue/mention_watchdog_exit.json"
WD_LAST_EXIT_REASON=""   # ""=情報なし(台帳なし/pid不一致/読取不能)。lock_held/config_missing/other

read_exit_ledger_for(){
  local target_pid="$1"
  [ -f "$EXIT_LEDGER" ] || { WD_LAST_EXIT_REASON=""; return 1; }
  local ledger_pid reason ts
  ledger_pid="$(python3 -c "
import json
try:
    d = json.load(open('$EXIT_LEDGER'))
    print(d.get('pid') or '')
except Exception:
    print('')
" 2>/dev/null)"
  if [ -z "$ledger_pid" ] || [ "$ledger_pid" != "$target_pid" ]; then
    WD_LAST_EXIT_REASON=""
    return 1
  fi
  reason="$(python3 -c "
import json
try:
    d = json.load(open('$EXIT_LEDGER'))
    print(d.get('reason') or '')
except Exception:
    print('')
" 2>/dev/null)"
  WD_LAST_EXIT_REASON="$reason"
  return 0
}

launch_watchdog(){
  cd "$ROOT"
  nohup python3 "$WD_SCRIPT" >> queue/mention_watchdog.log 2>&1 &
  WD_PID=$!; WD_SIG="$(wd_sig)"; log "mention_watchdog launch pid=$WD_PID"
  # ★launch_serverと同型の短い定着確認(次のsleep 8を待たず即死を検知)。
  sleep "$WD_FAST_DEATH_SEC"
  if ! kill -0 "$WD_PID" 2>/dev/null; then
    WD_FAST_DEATH=1
    # 【改修④-2・地雷2】execを跨いだ養子縁組のWD_PIDにはwaitできない(job table消失)が、
    #   ここは launch_watchdog 自身が fork した直後なので wait は有効(job tableに載っている)。
    #   ただしexit codeは構造的に副次経路(Fable第二診二)——台帳(exit ledger)を主経路とする。
    wait "$WD_PID" 2>/dev/null
    WD_LAST_EXIT_CODE=$?
    read_exit_ledger_for "$WD_PID"
  else
    WD_FAST_DEATH=0
    WD_LAST_EXIT_CODE=0
    WD_LAST_EXIT_REASON=""
  fi
}

report_watchdog_giveup(){
  # 【改修③】台帳の理由を主経路として優先(exit codeはexec越しで構造的に取り逃がしうる副次経路)。
  if [ "$WD_LAST_EXIT_REASON" = "lock_held" ] || [ "$WD_LAST_EXIT_CODE" -eq 11 ]; then
    log "[watchdog] 先客(既存の番犬プロセス)が居るためflockを取得できず起動を見合わせている(連続${WD_MAX_FAST_DEATH_STREAK}回・reason=lock_held)。異常ではない。"
    bash "$ROOT/scripts/inbox_write.sh" karo \
      "casper_supervisor: mention_watchdogは先客が居るため起動できずにいる(lock_held・異常死ではない)。二重起動防止のflockが働いている。ログ: ${LOG}" \
      escalation casper_supervisor 2>/dev/null || true
  elif [ "$WD_LAST_EXIT_REASON" = "config_missing" ] || [ "$WD_LAST_EXIT_CODE" -eq 12 ]; then
    log "[watchdog] 設定不足(TOKEN無し等)によりmention_watchdogが起動できずにいる(連続${WD_MAX_FAST_DEATH_STREAK}回・reason=config_missing)。再試行無意味。"
    bash "$ROOT/scripts/inbox_write.sh" karo \
      "casper_supervisor: mention_watchdogは設定不足(config_missing)で起動できずにいる。.env等を確認されたし。ログ: ${LOG}" \
      escalation casper_supervisor 2>/dev/null || true
  elif [ "$WD_LAST_EXIT_CODE" -eq 0 ]; then
    # ★★台帳が読めずexit codeのみ0(旧世代コード等で台帳未対応の場合のフォールバック)。
    log "[watchdog] 先客(既存の番犬プロセス)が居るためflockを取得できず起動を見合わせている(連続${WD_MAX_FAST_DEATH_STREAK}回・exit 0・台帳照合不能)。異常ではない可能性が高い。"
    bash "$ROOT/scripts/inbox_write.sh" karo \
      "casper_supervisor: mention_watchdogは先客が居るため起動できずにいる可能性が高い(exit 0・台帳照合不能)。二重起動防止のflockが働いている。ログ: ${LOG}" \
      escalation casper_supervisor 2>/dev/null || true
  else
    log "[watchdog] mention_watchdog.pyが起動直後に連続${WD_MAX_FAST_DEATH_STREAK}回異常死(exit=${WD_LAST_EXIT_CODE} reason=${WD_LAST_EXIT_REASON:-なし})。再起動ループを打ち切る。"
    bash "$ROOT/scripts/inbox_write.sh" karo \
      "casper_supervisor: mention_watchdog.pyが起動直後に連続${WD_MAX_FAST_DEATH_STREAK}回異常死(exit=${WD_LAST_EXIT_CODE} reason=${WD_LAST_EXIT_REASON:-なし})。再起動ループを打ち切った。ログ: ${LOG}" \
      escalation casper_supervisor 2>/dev/null || true
  fi
}

# 直前のlaunch_watchdogが即死(WD_FAST_DEATH=1)ならbackoffを挟んで再起動、
# 上限到達でループを抜ける(chat_server側のhandle_fast_death_and_relaunchと同型)。
handle_watchdog_fast_death(){
  if [ "$WD_FAST_DEATH" -ne 1 ]; then
    wd_fast_death_streak=0
    return 0
  fi
  wd_fast_death_streak=$((wd_fast_death_streak + 1))
  if [ "$wd_fast_death_streak" -ge "$WD_MAX_FAST_DEATH_STREAK" ]; then
    report_watchdog_giveup
    wd_fast_death_streak=0
    return 1
  fi
  local idx backoff
  idx=$(( wd_fast_death_streak - 1 ))
  [ "$idx" -ge "${#WD_BACKOFF_SEQUENCE[@]}" ] && idx=$(( ${#WD_BACKOFF_SEQUENCE[@]} - 1 ))
  backoff="${WD_BACKOFF_SEQUENCE[$idx]}"
  log "[watchdog] 即死(連続${wd_fast_death_streak}回目・exit=${WD_LAST_EXIT_CODE})→${backoff}秒待って再起動"
  sleep "$backoff"
  launch_watchdog
  handle_watchdog_fast_death
}

report_bind_failure_giveup(){
  log "[AC11] bind失敗の連続($MAX_FAST_DEATH_STREAK回)により再起動ループを打ち切る。家老へ報せる。"
  bash "$ROOT/scripts/inbox_write.sh" karo \
    "casper_supervisor: chat_server.pyが起動直後に連続${MAX_FAST_DEATH_STREAK}回死亡(bind失敗疑い)。再起動ループを打ち切った。ポート${CASPER_PORT}の状況を確認されたし。ログ: ${LOG}" \
    escalation casper_supervisor 2>/dev/null || true
}

HANDOFF_RETRY_SEC=30   # 引き継ぎ待機中の再確認間隔(誤爆防止優先ゆえ急がない)

# 直前の launch_server が即死(SRV_FAST_DEATH=1)なら backoff を挟んで再起動、
# 上限到達でループを抜ける。呼び出し元は launch_server 直後にこれを呼ぶ。
handle_fast_death_and_relaunch(){
  if [ "$SRV_FAST_DEATH" -ne 1 ]; then
    fast_death_streak=0
    return 0
  fi
  fast_death_streak=$((fast_death_streak + 1))
  if [ "$fast_death_streak" -ge "$MAX_FAST_DEATH_STREAK" ]; then
    report_bind_failure_giveup
    return 1
  fi
  idx=$(( fast_death_streak - 1 ))
  [ "$idx" -ge "${#BACKOFF_SEQUENCE[@]}" ] && idx=$(( ${#BACKOFF_SEQUENCE[@]} - 1 ))
  backoff="${BACKOFF_SEQUENCE[$idx]}"
  log "server即死(bind失敗疑い・連続${fast_death_streak}回目)→${backoff}秒待って再起動"
  sleep "$backoff"
  launch_server
  handle_fast_death_and_relaunch
}

log "supervisor 起動"
log_sha256
declare_generation_sha
log_legacy_breaker_keys

# 【cmd_518手当2 項目B-1】自己shaを記録して名乗る。
SELF_SHA="$(self_sha)"
declare_self_generation

# 【項目B-3】養子縁組: 前世代からの引き継ぎがあればlaunch_server/launch_watchdogを
# スキップしてSRV_PID/WD_PIDを引き継ぐ(要件4=pidは無停止のまま)。
if adopt_prior_generation; then
  [ -n "$WD_PID" ] || launch_watchdog
else
  launch_server
  handle_fast_death_and_relaunch || exit 0
  launch_watchdog
fi
WD_SIG="${WD_SIG:-$(wd_sig)}"

while true; do
  # 【AC2/AC10】前世代引き継ぎが不可で待機中は、通常の死活/backoffループへ入らず
  # 一定間隔で再確認するだけに留める(誤って別プロセスを畳む早まった動作をしない)。
  if [ "$HANDOFF_BLOCKED" -eq 1 ]; then
    sleep "$HANDOFF_RETRY_SEC"
    launch_server
    handle_fast_death_and_relaunch || break
    continue
  fi
  # 【改修②不変条件・改修③是正】WD_BLOCKED中はserver死活/reload等の通常ループを
  # 回しつつ、理由別に再確認する。
  # ★reason=orphan(unverified/foreignで畳めなかった)の時のみ孤児検証を再試行する。
  #   reason=config(config_missing)は孤児が存在しない(respawn自体が無意味な設定不備)ため
  #   孤児検証を呼ばない——呼ぶと「候補なし=absent」を誤って解除条件に読み違え、
  #   壊れた設定のまま新番犬を即respawnして即死ループへ逆戻りする事故になる
  #   (合成テストで実際に発生を確認・是正済)。configはオペレータの手当てを待つのみ。
  if [ "$WD_BLOCKED" -eq 1 ] && [ "$WD_BLOCKED_REASON" = "orphan" ]; then
    resolve_orphan_watchdog_unified
    wd_resolve_rc=$?
    if [ "$wd_resolve_rc" -eq 0 ]; then
      log "[watchdog] WD_BLOCKED解除(reason=orphan)。孤児検証が通ったため新番犬を起こす。"
      WD_BLOCKED=0
      WD_BLOCKED_REASON=""
      WD_BLOCKED_NOTIFIED=0
      launch_watchdog
      handle_watchdog_fast_death
      WD_SIG="$(wd_sig)"
    else
      sleep "$WD_BLOCKED_RETRY_SEC"
    fi
  elif [ "$WD_BLOCKED" -eq 1 ]; then
    # reason=config(またはその他): 孤児検証は呼ばず、ただ待つ。解除はオペレータ操作
    # (例: karo/家老が.envを直した後、supervisorを再起動するか、または将来的に
    # config再チェックのみ行う経路を足す)まで行わない——respawnしない、が正。
    sleep "$WD_BLOCKED_RETRY_SEC"
  fi
  sleep 8
  # ① server 死活
  if ! kill -0 "$SRV_PID" 2>/dev/null; then
    log "server死亡→再起動"
    launch_server
    handle_fast_death_and_relaunch || break
    continue
  fi
  fast_death_streak=0
  # ② コード変更→自動リロード(管理下の子PIDのみ停止して再launch)
  NOW="$(sig)"
  if [ -n "$NOW" ] && [ "$NOW" != "$SRV_SIG" ]; then
    if holdout_lock_active; then
      : # 測定中はreload保留(ログはholdout_lock_active内で出力済)。SRV_SIGは更新しない
        # (ロック解除後の次ループでも変更検知が継続し、TTL超過時に確実にreloadへ回る)。
    else
      log "scripts/*.py 変更検知→auto-reload (停止 $SRV_PID)"
      kill "$SRV_PID" 2>/dev/null; sleep 2; launch_server
      handle_fast_death_and_relaunch || break
    fi
  fi
  # ③ mention_watchdog 死活(AC-B7: 即死対策backoff付き / 改修③: 死因台帳連携)
  if [ "$WD_BLOCKED" -ne 1 ] && ! kill -0 "$WD_PID" 2>/dev/null; then
    log "watchdog死亡検知(pid=$WD_PID)"
    # 【改修④-2・地雷2】execを跨いだ養子縁組のWD_PIDはこのシェルのjob tableに無く、
    #   waitは失敗しうる(死活はkill -0で既に確認済・exit codeは死因台帳を主経路とする)。
    wait "$WD_PID" 2>/dev/null
    WD_LAST_EXIT_CODE=$?
    read_exit_ledger_for "$WD_PID"
    case "$WD_LAST_EXIT_REASON" in
      lock_held)
        log "[watchdog] 死因台帳=lock_held。respawnせず孤児handoff(単一機構)へ回す。"
        resolve_orphan_watchdog_unified
        if [ $? -eq 0 ]; then
          log "[watchdog] 孤児検証が通った。新番犬を起こす。"
          launch_watchdog
          handle_watchdog_fast_death
          WD_SIG="$(wd_sig)"
        else
          log "[watchdog] 孤児を畳めなかった(unverified/foreign)。WD_BLOCKEDで待つ(★不変条件: 畳めぬなら起こすな)。"
          WD_BLOCKED=1
          WD_BLOCKED_REASON="orphan"
          if [ "$WD_BLOCKED_NOTIFIED" -eq 0 ]; then
            bash "$ROOT/scripts/inbox_write.sh" karo \
              "casper_supervisor: mention_watchdog死亡(lock_held)後、旧個体を検証できず畳めなかった(unverified/foreign)。新番犬は起こさず待機中。二匹がstateを書き合う危険を避けるための不変条件。ログ: ${LOG}" \
              escalation casper_supervisor 2>/dev/null || true
            bash "$ROOT/scripts/discord.sh" "⚠️ Casper番犬: 旧個体を安全に畳めず新番犬起動を保留中(WD_BLOCKED)" 2>/dev/null || true
            WD_BLOCKED_NOTIFIED=1
          fi
        fi
        ;;
      config_missing)
        log "[watchdog] 死因台帳=config_missing。respawn無意味。WD_BLOCKEDで待ち報せる。"
        WD_BLOCKED=1
        WD_BLOCKED_REASON="config"
        if [ "$WD_BLOCKED_NOTIFIED" -eq 0 ]; then
          bash "$ROOT/scripts/inbox_write.sh" karo \
            "casper_supervisor: mention_watchdogが設定不足(config_missing)で死亡。.env等を確認するまでrespawnを保留する。ログ: ${LOG}" \
            escalation casper_supervisor 2>/dev/null || true
          WD_BLOCKED_NOTIFIED=1
        fi
        ;;
      *)
        # 台帳なし(本物の異常死)、またはtsが直近でない/pid不一致で台帳を信用できぬ場合。
        # ★現行のfast-death対策通り: streak++・backoff・8回で見切り。
        #   3秒以上生きた個体の死はstreak=0で即respawn(現行どおり・launch_watchdog内で判定)。
        log "[watchdog] 死因台帳なし/照合不能。fast-death対策(現行どおり)へフォールバック。"
        WD_FAST_DEATH=1
        handle_watchdog_fast_death
        WD_SIG="$(wd_sig)"
        ;;
    esac
  fi
  # ③b【項目B-6・WD_SIG・既定無効】番犬/handoffの署名変更を検知したら己の子WD_PIDを
  #   SIGTERMして生み直す(chat_server reloadと同型)。有効化はkaroが判断するまで無効。
  if [ "$WD_SIG_ENABLED" = "1" ]; then
    NOW_WD_SIG="$(wd_sig)"
    if [ -n "$NOW_WD_SIG" ] && [ "$NOW_WD_SIG" != "$WD_SIG" ]; then
      if holdout_lock_active; then
        :
      else
        log "[watchdog] WD_SIG変化検知→再生み直し(停止 $WD_PID)"
        kill "$WD_PID" 2>/dev/null; wait "$WD_PID" 2>/dev/null
        launch_watchdog
        handle_watchdog_fast_death
        WD_SIG="$(wd_sig)"
      fi
    fi
  fi
  # ④【cmd_509第2便】三層probeのうち定常/候補(32秒=4ループに1回)。
  # ★holdout測定中はauto-reloadと同様に保留する(cmd_507ロックの趣旨=本番実測との干渉を断つ)。
  FAILOVER_PROBE_TICK=$((FAILOVER_PROBE_TICK + 1))
  if [ "$FAILOVER_PROBE_TICK" -ge "$FAILOVER_PROBE_EVERY" ]; then
    FAILOVER_PROBE_TICK=0
    if holdout_lock_active; then
      : # 測定中はprobe/切替を保留(ログはholdout_lock_active内で出力済)
    else
      failover_probe_and_decide
    fi
  fi
  resync_env_if_changed        # 台帳(endpoints.env)の変更に走行中も追随する
  ensure_seat_matches_ledger   # 台帳と走行実体の座席が食い違えば起こし直す
  # 【cmd_518手当2 項目B-2】自己世代交代チェック(毎ループ末尾)。
  check_self_generation_and_exec
done
