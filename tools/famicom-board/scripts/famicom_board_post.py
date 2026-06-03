#!/usr/bin/env python3
"""
ファミコン風 3陣稼働ボード Discord投稿ループ

- 各 fleet の GIF を生成 (famicom_board.py 経由)
- Discord channel に投稿 / edit-in-place 更新
- メッセージID永続化 (/mnt/h/shogun_discord-second/var/famicom_board_state.yaml)

使い方:
  # 設定: channel_map.yaml に殿が channel ID を記入後、起動
  /home/bokan/.venvs/famicom_board/bin/python3 scripts/famicom_board_post.py [--interval 30] [--once]

設定ファイル(channel_map.yaml 例):
  1st: '1234567890123456789'  # 第1陣 channel ID
  2nd: '2345678901234567890'  # 第2陣 channel ID
  3rd: '3456789012345678901'  # 第3陣 channel ID
"""
from __future__ import annotations
import os, sys, time, json, yaml, datetime, argparse
from pathlib import Path
import requests

# famicom_board からインポート
sys.path.insert(0, str(Path(__file__).parent))
import famicom_board as fb

ROOT = Path(__file__).parent.parent  # /mnt/h/shogun_discord-second (default)
# 注: --config/--env/--state/--log で override 可能 (Phase 2 分散型・他陣 daemon 用)
CHANNEL_MAP_PATH = ROOT / 'config' / 'famicom_board_channels.yaml'
STATE_PATH = ROOT / 'var' / 'famicom_board_state.yaml'
ENV_PATH = ROOT / '.env'
LOG_PATH = ROOT / 'logs' / 'famicom_board.log'

# Phase 2 分散型対応: --config/--env/--state flag で path override 可能化
# 1st-fleet 用例:
#   --config /mnt/h/multi-agent-shogun-main/config/famicom_board_channels.yaml
#   --env /mnt/h/multi-agent-shogun-main/.env
#   --state /mnt/h/multi-agent-shogun-main/var/famicom_board_state.yaml
#   --fleet 1st


def log(msg: str):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    try:
        with LOG_PATH.open('a') as f:
            f.write(line + '\n')
    except Exception:
        pass


def load_env() -> dict:
    env = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, _, v = line.partition('=')
            env[k.strip()] = v.strip()
    return env


def load_channel_map() -> dict:
    if not CHANNEL_MAP_PATH.exists():
        log(f"channel_map 未設定: {CHANNEL_MAP_PATH}")
        return {}
    d = yaml.safe_load(CHANNEL_MAP_PATH.read_text()) or {}
    return d


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {}
    return yaml.safe_load(STATE_PATH.read_text()) or {}


def save_state(state: dict):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(yaml.safe_dump(state, allow_unicode=True))


def post_message(token: str, channel_id: str, gif_path: str,
                 content: str) -> str:
    """Discord に画像付きメッセージを新規投稿。message_id を返す"""
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    headers = {
        "Authorization": f"Bot {token}",
        "User-Agent": "FleetBoard (https://github.com/local, 1.0)",
    }
    with open(gif_path, 'rb') as fbin:
        files = {"files[0]": (Path(gif_path).name, fbin, "image/gif")}
        data = {"payload_json": json.dumps({"content": content})}
        r = requests.post(url, headers=headers, data=data, files=files, timeout=30)
    r.raise_for_status()
    return r.json()["id"]


def edit_message(token: str, channel_id: str, message_id: str,
                 gif_path: str, content: str) -> bool:
    """既存メッセージの content と添付GIFを更新。"""
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages/{message_id}"
    headers = {
        "Authorization": f"Bot {token}",
        "User-Agent": "FleetBoard (https://github.com/local, 1.0)",
    }
    payload = {
        "content": content,
        "attachments": [],  # 既存添付を消し新しいのと置き換え
    }
    with open(gif_path, 'rb') as fbin:
        files = {"files[0]": (Path(gif_path).name, fbin, "image/gif")}
        data = {"payload_json": json.dumps(payload)}
        r = requests.patch(url, headers=headers, data=data, files=files, timeout=30)
    if r.status_code in (404, 403):
        # message不在もしくは権限なし → 再投稿要
        log(f"  edit失敗 status={r.status_code}: {r.text[:200]}")
        return False
    r.raise_for_status()
    return True


def post_or_edit(token: str, channel_id: str, gif_path: str,
                 content: str, state: dict, key: str) -> str:
    """state[key] にmessage_id があれば edit、無ければ新規投稿。"""
    msg_id = state.get(key)
    if msg_id:
        ok = edit_message(token, channel_id, msg_id, gif_path, content)
        if ok:
            return msg_id
        log(f"  {key}: edit不可ゆえ新規投稿")
    # 新規投稿
    new_id = post_message(token, channel_id, gif_path, content)
    log(f"  {key}: 新規投稿 msg_id={new_id}")
    return new_id


def render_and_post(token: str, channels: dict, state: dict,
                     fleet_filter: str = 'all'):
    for name, root in fb.FLEETS.items():
        if fleet_filter != 'all' and name != fleet_filter:
            continue
        try:
            gif_path = f"/tmp/famicom_board_{name}.gif"
            status = fb.render_gif(name, root, gif_path)
            # 集計サマリー content
            cnt = {'work':0,'idle':0,'freeze':0,'offline':0,'wake':0}
            for s in status.values(): cnt[s['state']] = cnt.get(s['state'],0)+1
            ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            label = {'1st':'第1陣 (Score専任)','2nd':'第2陣 (Discord窓口)','3rd':'第3陣 (ComfyUI音源)'}[name]
            content = (f"**{label}** ステータス @ {ts}\n"
                       f"作業 {cnt['work']} / 待機 {cnt['idle']} / 凍結 {cnt['freeze']} / 未起動 {cnt['offline']}")
            ch = channels.get(name)
            if not ch:
                log(f"  {name}: channel未設定 (channel_map.yaml に {name} の channel_id 追記要)")
                continue
            key = f"{name}_msg_id"
            new_id = post_or_edit(token, str(ch), gif_path, content, state, key)
            state[key] = new_id
            save_state(state)
        except Exception as e:
            log(f"  {name}: ERROR {e}")
            import traceback; traceback.print_exc()


def ensure_channel_map_template():
    """初回起動時に channel_map.yaml テンプレを作成"""
    if not CHANNEL_MAP_PATH.exists():
        CHANNEL_MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
        CHANNEL_MAP_PATH.write_text(
            "# 殿が3 Discord channel 作成後、ここに channel ID を記入\n"
            "# Discord 開発者モード ON → channel 右クリック → IDをコピー\n"
            "1st: ''  # 第1陣 channel ID\n"
            "2nd: ''  # 第2陣 channel ID\n"
            "3rd: ''  # 第3陣 channel ID\n"
        )
        log(f"channel_map template作成: {CHANNEL_MAP_PATH}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--interval', type=int, default=30, help='更新間隔(秒)')
    ap.add_argument('--once', action='store_true', help='一回だけ実行して終了')
    ap.add_argument('--dry-run', action='store_true', help='GIF生成のみ・Discord投稿せず')
    ap.add_argument('--fleet', choices=['all','1st','2nd','3rd'], default='all',
                    help='対象陣を限定 (Phase2 分散型移行を見越して)')
    ap.add_argument('--config', default=None, help='channel_map.yaml path override')
    ap.add_argument('--env', default=None, help='.env path override')
    ap.add_argument('--state', default=None, help='state.yaml path override')
    ap.add_argument('--log', default=None, help='log file path override')
    args = ap.parse_args()

    # Path override (Phase 2 分散型・1st-fleet daemon等で同コード再利用)
    global CHANNEL_MAP_PATH, ENV_PATH, STATE_PATH, LOG_PATH
    if args.config: CHANNEL_MAP_PATH = Path(args.config)
    if args.env:    ENV_PATH = Path(args.env)
    if args.state:  STATE_PATH = Path(args.state)
    if args.log:    LOG_PATH = Path(args.log)

    ensure_channel_map_template()
    env = load_env()
    token = env.get('DISCORD_BOT_TOKEN', '')
    if not token:
        log("ERROR: DISCORD_BOT_TOKEN 未設定 (/mnt/h/shogun_discord-second/.env)")
        sys.exit(1)
    if args.dry_run:
        log("dry-run mode (Discord 投稿せず)")
        for name, root in fb.FLEETS.items():
            gif_path = f"/tmp/famicom_board_{name}.gif"
            fb.render_gif(name, root, gif_path)
            log(f"  {name}: -> {gif_path}")
        return

    channels = load_channel_map()
    valid = {k: v for k, v in channels.items() if v}
    if not valid:
        log(f"⚠️ channel_map.yaml に channel ID 未記入: {CHANNEL_MAP_PATH}")
        log("殿が Discord channel 3つ作成 + shogun2 bot 権限付与 + channel ID 記入後に再起動下さい")
        sys.exit(2)

    state = load_state()
    log(f"famicom board post-loop 起動 interval={args.interval}s fleet={args.fleet} channels={list(valid.keys())}")
    while True:
        render_and_post(token, valid, state, fleet_filter=args.fleet)
        if args.once:
            break
        time.sleep(args.interval)


if __name__ == '__main__':
    main()
