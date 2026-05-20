#!/usr/bin/env python3
"""
ファミコン風 3陣稼働ボード生成器

各陣 (1st/2nd/3rd) の10エージェント稼働状況を、軍勢配置型のドット絵
アニメGIFに描画する。出力: /tmp/famicom_board_{1st,2nd,3rd}.gif

実行: /home/bokan/.venvs/famicom_board/bin/python3 scripts/famicom_board.py [--once]

殿GO待ち: Discord 投稿前の素子試作生成スクリプト。
"""
from __future__ import annotations
import os, sys, time, yaml, datetime, subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# ─── 陣 ─────────────────────────────────────────────────────────────────
FLEETS = {
    '1st': '/mnt/h/multi-agent-shogun-main',
    '2nd': '/mnt/h/shogun_discord-second',
    '3rd': '/mnt/h/multi-agent-shogun-third',
}
AGENTS = ['shogun', 'karo', 'gunshi'] + [f'ashigaru{i}' for i in range(1, 8)]

# 陣 → tmux socket dir (None=default)
FLEET_TMUX = {
    '1st': None,                       # 既定 socket /tmp/tmux-1000/default
    '2nd': '/tmp/tmux-shogun2',
    '3rd': '/tmp/tmux-shogun3',
}

# agent → pane (1st/2nd/3rd 同一構成)
AGENT_PANE = {
    'shogun':    'shogun:main.0',
    'karo':      'multiagent:agents.0',
    'gunshi':    'multiagent:agents.8',
    **{f'ashigaru{i}': f'multiagent:agents.{i}' for i in range(1, 8)},
}

# CPU 累計時間の前回値(キャッシュ・renderプロセス生存中のみ)
_CPU_PREV: dict = {}  # key=(fleet, agent) → (epoch, cputime_sec)


def _tmux_env(fleet_name: str) -> dict:
    env = os.environ.copy()
    tmpdir = FLEET_TMUX.get(fleet_name)
    if tmpdir:
        env['TMUX_TMPDIR'] = tmpdir
    else:
        env.pop('TMUX_TMPDIR', None)
    return env


def _get_pane_pid(fleet_name: str, pane: str) -> int | None:
    try:
        r = subprocess.run(
            ['tmux', 'display-message', '-p', '-t', pane, '#{pane_pid}'],
            capture_output=True, text=True, env=_tmux_env(fleet_name), timeout=3,
        )
        if r.returncode != 0: return None
        v = r.stdout.strip()
        return int(v) if v.isdigit() else None
    except Exception:
        return None


def _find_claude_pid(parent_pid: int) -> int | None:
    """bash pane の子から comm=claude のpidを取る"""
    try:
        r = subprocess.run(['pgrep', '-P', str(parent_pid)],
                            capture_output=True, text=True, timeout=2)
        for cpid in r.stdout.split():
            r2 = subprocess.run(['ps', '-p', cpid, '-o', 'comm='],
                                capture_output=True, text=True, timeout=2)
            if r2.stdout.strip() == 'claude':
                return int(cpid)
    except Exception:
        pass
    return None


def _get_cpu_time_sec(pid: int) -> float | None:
    """プロセス累計CPU時間(秒)を /proc/<pid>/stat から取得"""
    try:
        with open(f'/proc/{pid}/stat') as f:
            parts = f.read().split()
        # フィールド14=utime, 15=stime (jiffies)
        # comm に空白が含まる可能性→ 後ろから index
        # stat format: pid (comm) state ppid ... → comm)以降を取る
        # 簡略: 末尾の安定フィールドを使う代わり後ろから:
        # 14=utime, 15=stime
        utime = int(parts[13])
        stime = int(parts[14])
        # SC_CLK_TCK 通常 100
        clk_tck = os.sysconf('SC_CLK_TCK')
        return (utime + stime) / clk_tck
    except Exception:
        return None


def get_agent_activity(fleet_name: str, agent: str, interval_hint: int = 30) -> dict:
    """tmux pane → claude pid → CPU増分 から活動度を推定。
    return: dict(active=bool, delta_cpu=float|None, claude_pid=int|None)
    """
    pane = AGENT_PANE.get(agent)
    if not pane:
        return dict(active=False, delta_cpu=None, claude_pid=None)
    pane_pid = _get_pane_pid(fleet_name, pane)
    if not pane_pid:
        return dict(active=False, delta_cpu=None, claude_pid=None)
    claude_pid = _find_claude_pid(pane_pid)
    if not claude_pid:
        return dict(active=False, delta_cpu=None, claude_pid=None)
    cur_cpu = _get_cpu_time_sec(claude_pid)
    if cur_cpu is None:
        return dict(active=False, delta_cpu=None, claude_pid=claude_pid)
    now = time.time()
    key = (fleet_name, agent)
    prev = _CPU_PREV.get(key)
    delta = None
    active = False
    if prev:
        prev_t, prev_cpu = prev
        elapsed = now - prev_t
        if elapsed > 0 and cur_cpu >= prev_cpu:
            delta = cur_cpu - prev_cpu
            # interval scaling: 3% CPU 平均 (or 最低 0.2秒) を active 閾値
            # 30秒間隔なら ~0.9秒以上の CPU 使用 (= 会話中 LLM inference 1回分以上)
            threshold = max(0.2, elapsed * 0.03)
            active = delta >= threshold
    _CPU_PREV[key] = (now, cur_cpu)
    return dict(active=active, delta_cpu=delta, claude_pid=claude_pid)

# ─── ファミコン風パレット ─────────────────────────────────────────────────
# NES風の限定パレット
PAL = {
    'sky_top': (32, 56, 168),       # 紺空
    'sky_bot': (84, 124, 252),      # 明るい青
    'ground': (84, 60, 32),         # 茶色 地面
    'ground_lo': (120, 88, 48),
    'castle_stone': (188, 184, 152),# 灰白 城壁
    'castle_dark': (104, 100, 84),
    'castle_roof': (180, 60, 36),   # 朱屋根
    'roof_dark': (124, 36, 12),
    'flag_red': (228, 56, 36),
    'flag_pole': (200, 200, 200),
    # 役職カラー (アーマー/法衣)
    'shogun_armor': (216, 40, 40),  # 朱
    'shogun_armor_dark': (140, 24, 24),
    'shogun_helm': (252, 224, 64),  # 金兜
    'karo_robe': (60, 100, 200),    # 青
    'karo_robe_dark': (28, 64, 140),
    'gunshi_robe': (152, 60, 184),  # 紫
    'gunshi_robe_dark': (100, 28, 124),
    'ashi_armor': (124, 88, 48),    # 茶
    'ashi_armor_dark': (80, 56, 24),
    # 共通
    'skin': (252, 188, 152),
    'skin_dark': (200, 124, 88),
    'eye': (28, 28, 28),
    'outline': (16, 16, 16),
    'white': (252, 252, 252),
    # ステータス枠 (sprite裏に敷くハロー)
    'st_work': (96, 224, 96),       # 緑 = 作業中
    'st_idle': (180, 180, 180),     # 灰 = 待機
    'st_freeze': (252, 60, 60),     # 赤 = 凍結
    'st_offline': (40, 40, 40),     # 黒 = 未起動
    'st_wake': (252, 196, 36),      # 黄 = 検品待ち/思案
    # UI
    'panel_bg': (16, 24, 56),
    'panel_border': (252, 252, 252),
    'bar_fill': (96, 224, 96),
    'bar_empty': (60, 60, 60),
    'text_white': (252, 252, 252),
    'text_gray': (180, 180, 180),
}

# キャンバス
W, H = 480, 360
SCALE = 1  # 2x scaling can be applied at save time if needed

# ─── スプライト定義 (16x16, ASCII map → ピクセル) ─────────────────────────
# 文字キー → (color_a, color_b, color_c) で役職カラーを差し替え可能化
# o=outline, .=transparent, a=primary armor, b=secondary armor (dark),
# s=skin, e=eye, h=highlight, c=accent (helm/sash), w=white

SPRITE_SHOGUN_FRAME1 = [
    "................",
    "......cccc......",  # 兜上部
    ".....cccccc.....",
    ".....cwwccc.....",
    "....oossssoo....",  # 顔
    "....osseesoo....",  # 目
    "....os....so....",  # 顎
    "....ooooooo.....",
    "...oaaaaaa o....",  # 鎧上
    "...oababba o....",
    "...oaaaaaa o....",  # 鎧下
    "...obbbbbb o....",
    "...oaaooaao.....",  # 腰下
    "...oaa..aao.....",
    "....o....o......",  # 足
    "................",
]
SPRITE_SHOGUN_FRAME2 = [  # 振り向く動作
    "................",
    ".......cccc.....",
    "......cccccc....",
    "......cwwccc....",
    ".....oossssoo...",
    ".....osseesoo...",
    ".....os....so...",
    ".....ooooooo....",
    "....oaaaaaaao...",
    "....obababbao...",
    "....oaaaaaaao...",
    "....obbbbbbbo...",
    "....oaaooaao....",
    "....oaa..aao....",
    "....oo...oo.....",
    "................",
]

SPRITE_KARO_FRAME1 = [
    "................",
    "......oooo......",  # 烏帽子(細い帽子)
    ".....oo  oo.....",
    ".....o....o.....",
    "....oossssoo....",
    "....osseesoo....",
    "....os....so....",
    "....ooooooo.....",
    "...oaaaaaaao....",
    "...obabbabao....",
    "...oaaaaaaao....",
    "...oaaaaaaao....",
    "...oaaooaaao....",
    "...oaa..aaao....",
    "....o....o......",
    "................",
]
SPRITE_KARO_FRAME2 = [
    "................",
    "......oooo......",
    ".....oo  oo.....",
    ".....o....o.....",
    "....oossssoo....",
    "....oss..soo....",  # 目を閉じる
    "....os....so....",
    "....ooooooo.....",
    "....oaaaaaao....",
    "....obabbabo....",
    "....oaaaaaao....",
    "....oaaaaaao....",
    "...oaaooaaao....",
    "...oaa..aaao....",
    "....o....o......",
    "................",
]

SPRITE_GUNSHI_FRAME1 = [
    "................",
    ".....cccccc.....",  # 烏帽子＋飾り
    "....c......c....",
    "....c.cwwc.c....",
    "....oossssoo....",
    "....osseesoo....",
    "....os....so....",
    "....ooooooo.....",
    "...oaaaaaaao....",  # 法衣
    "...obabbabao....",
    "...oaaaaaaao....",
    "...oababbabo....",
    "...oaaaaaaao....",
    "...oaa..aaao....",
    "....o....o......",
    "................",
]
SPRITE_GUNSHI_FRAME2 = [  # 扇を仰ぐ
    "................",
    ".....cccccc.....",
    "....c......c....",
    "....c.cwwc.c....",
    "....oossssoo....",
    "....osseesoo....",
    "....os....so....",
    "....ooooooo.....",
    "...oaaaaaaao....",
    "..woababbabow...",  # 扇 (左右に)
    "...oaaaaaaao....",
    "...oababbabo....",
    "...oaaaaaaao....",
    "...oaa..aaao....",
    "....o....o......",
    "................",
]

SPRITE_ASHI_FRAME1 = [
    "................",
    "....ooooooooo...",  # 笠
    "...occccccccco..",
    "....ooooooooo...",
    "....oossssoo....",
    "....osseesoo....",
    "....os....so....",
    "....ooooooo.....",
    "....oaaaaao.....",  # 鎧
    "....obabbao.....",
    "....oaaaaao.....",
    "....oaaaaao.....",
    "...oaaooaao.....",
    "...oaa..aao.....",
    "....o....o......",
    "................",
]
SPRITE_ASHI_FRAME2 = [
    "................",
    "....ooooooooo...",
    "...occccccccco..",
    "....ooooooooo...",
    "....oossssoo....",
    "....oss..soo....",  # 目閉じ
    "....os....so....",
    "....ooooooo.....",
    "....oaaaaao.....",
    "....obabbao.....",
    "....oaaaaao.....",
    "....oaaaaao.....",
    "....oaaooaao....",  # 足変位 (歩行)
    "....oaa..aao....",
    "....oo...oo.....",
    "................",
]

ROLE_SPRITES = {
    'shogun': (SPRITE_SHOGUN_FRAME1, SPRITE_SHOGUN_FRAME2),
    'karo':   (SPRITE_KARO_FRAME1, SPRITE_KARO_FRAME2),
    'gunshi': (SPRITE_GUNSHI_FRAME1, SPRITE_GUNSHI_FRAME2),
    'ashigaru': (SPRITE_ASHI_FRAME1, SPRITE_ASHI_FRAME2),
}

ROLE_PALETTE = {
    'shogun': dict(o=PAL['outline'], s=PAL['skin'], e=PAL['eye'],
                   a=PAL['shogun_armor'], b=PAL['shogun_armor_dark'],
                   c=PAL['shogun_helm'], w=PAL['white']),
    'karo':   dict(o=PAL['outline'], s=PAL['skin'], e=PAL['eye'],
                   a=PAL['karo_robe'], b=PAL['karo_robe_dark'],
                   c=PAL['outline'], w=PAL['white']),
    'gunshi': dict(o=PAL['outline'], s=PAL['skin'], e=PAL['eye'],
                   a=PAL['gunshi_robe'], b=PAL['gunshi_robe_dark'],
                   c=PAL['outline'], w=PAL['white']),
    'ashigaru': dict(o=PAL['outline'], s=PAL['skin'], e=PAL['eye'],
                     a=PAL['ashi_armor'], b=PAL['ashi_armor_dark'],
                     c=PAL['outline'], w=PAL['white']),
}

# ─── ステータス集約 ─────────────────────────────────────────────────────

def detect_agent_state(fleet_root: str, agent: str, fleet_name: str = '') -> dict:
    """agent の現在状況を判定。
    return: dict(state, task_id, mtime_age_sec, progress)
      state: 'work' | 'idle' | 'freeze' | 'offline' | 'wake'

    判定方針(Phase 1+tmux):
      最優先: tmux pane の claude プロセス CPU 使用 (interval内増分 >= 0.3秒) = 'work'
      補助: mtime <5min: 'work' (filesystem 活動)
            mtime 5-30min: status が work/in_progress なら work、それ以外は idle
            mtime >30min: idle
            mtime >2h かつ status: work宣言 = freeze 疑い
      task / inbox file 共に不在 = 'offline'
    """
    task_file = Path(fleet_root) / 'queue' / 'tasks' / f'{agent}.yaml'
    inbox_file = Path(fleet_root) / 'queue' / 'inbox' / f'{agent}.yaml'

    if not task_file.exists() and not inbox_file.exists():
        return dict(state='offline', task_id='-', mtime_age_sec=None, progress=0)

    # task と inbox の より新しい方を直近活動として採用
    mtimes = []
    for p in (task_file, inbox_file):
        if p.exists():
            mtimes.append(p.stat().st_mtime)
    mtime_age = int(time.time() - max(mtimes)) if mtimes else None
    task_id = '-'
    status_raw = ''

    if task_file.exists():
        try:
            d = yaml.safe_load(task_file.read_text(errors='ignore')) or {}
            task = d.get('task', d) if isinstance(d, dict) else {}
            task_id = task.get('task_id') or d.get('task_id') or '-'
            status_raw = (task.get('status') or d.get('status') or '').lower()
        except Exception:
            pass

    # state 推論
    work_status = status_raw in ('work', 'in_progress', 'assigned', 'working', 'running')
    done_status = status_raw in ('done', 'completed', 'finished')

    if mtime_age < 300:
        state = 'work'
        progress = 80
    elif mtime_age < 1800:
        if work_status:
            state = 'work'; progress = 50
        else:
            state = 'idle'; progress = 100 if done_status else 0
    else:
        state = 'idle'; progress = 100 if done_status else 0

    # freeze: status=work 宣言で mtime > 2h
    if work_status and mtime_age > 7200:
        state = 'freeze'

    # tmux 由来の CPU 活動が最優先(filesystem が古くても会話/応答中なら work)
    if fleet_name:
        act = get_agent_activity(fleet_name, agent)
        if act['active']:
            state = 'work'
            progress = max(progress, 70)
        elif act['claude_pid'] is None and state != 'offline':
            # tmux 取得不可 → fleet 未起動の可能性
            # ただし mtime ある場合は idle扱いとする
            pass

    return dict(state=state, task_id=str(task_id)[:20],
                mtime_age_sec=mtime_age, progress=progress)


def collect_fleet_status(name: str, root: str) -> dict:
    """陣の全エージェント状態を収集"""
    out = {}
    if not Path(root).is_dir():
        # 陣が存在しない (新設前等)
        for ag in AGENTS:
            out[ag] = dict(state='offline', task_id='-', mtime_age_sec=None, progress=0)
        return out
    for ag in AGENTS:
        out[ag] = detect_agent_state(root, ag, fleet_name=name)
    return out


# ─── スプライト描画 ───────────────────────────────────────────────────────

def draw_sprite(img: Image.Image, sprite_lines: list, palette: dict,
                x: int, y: int, scale: int = 2):
    """16x16 ASCII map のスプライトを (x,y) に描画 (scale倍)"""
    px = img.load()
    for sy, row in enumerate(sprite_lines):
        for sx, ch in enumerate(row):
            if ch in ('.', ' '):
                continue
            color = palette.get(ch, PAL['outline'])
            # scale倍
            for dy in range(scale):
                for dx in range(scale):
                    tx, ty = x + sx*scale + dx, y + sy*scale + dy
                    if 0 <= tx < img.width and 0 <= ty < img.height:
                        px[tx, ty] = color


def draw_status_halo(img: Image.Image, x: int, y: int, w: int, h: int,
                     color: tuple, dim: bool = False):
    """sprite の周りに status を示す光輪/枠を描画"""
    d = ImageDraw.Draw(img)
    if dim:
        c = tuple(int(v*0.5) for v in color)
    else:
        c = color
    # 矩形枠 (2px)
    d.rectangle([x-2, y-2, x+w+1, y+h+1], outline=c, width=2)


_FONT_CACHE = {}

def _load_jp_font(size: int):
    """日本語フォントをサイズ別にキャッシュ取得。Windowsの MSGothic 等を利用。"""
    if size in _FONT_CACHE:
        return _FONT_CACHE[size]
    candidates = [
        '/mnt/c/Windows/Fonts/msgothic.ttc',
        '/mnt/c/Windows/Fonts/BIZ-UDGothicB.ttc',
        '/mnt/c/Windows/Fonts/YuGothM.ttc',
        '/mnt/c/Windows/Fonts/meiryo.ttc',
    ]
    for fp in candidates:
        if Path(fp).exists():
            try:
                f = ImageFont.truetype(fp, size)
                _FONT_CACHE[size] = f
                return f
            except Exception:
                continue
    f = ImageFont.load_default()
    _FONT_CACHE[size] = f
    return f


def draw_pixel_text(img: Image.Image, text: str, x: int, y: int,
                    color: tuple = (252,252,252), size: int = 10):
    """日本語対応・指定サイズ"""
    d = ImageDraw.Draw(img)
    font = _load_jp_font(size)
    d.text((x, y), text, fill=color, font=font)


def draw_castle_backdrop(img: Image.Image):
    """日本の天守閣風ドット絵背景 — 反り屋根・破風・鯱・石垣の勾配"""
    d = ImageDraw.Draw(img)
    GROUND_Y = 200
    # 空グラデーション
    for y in range(24, GROUND_Y):
        t = (y - 24) / (GROUND_Y - 24)
        r = int(PAL['sky_top'][0] * (1-t) + PAL['sky_bot'][0] * t)
        g = int(PAL['sky_top'][1] * (1-t) + PAL['sky_bot'][1] * t)
        b = int(PAL['sky_top'][2] * (1-t) + PAL['sky_bot'][2] * t)
        d.line([(0,y),(W,y)], fill=(r,g,b))
    # 雲
    d.ellipse([55, 48, 130, 72], fill=PAL['white'])
    d.ellipse([100, 56, 165, 78], fill=PAL['white'])
    d.ellipse([340, 60, 410, 82], fill=PAL['white'])
    d.ellipse([380, 50, 445, 75], fill=PAL['white'])
    # 地面 (200-H-30) — 石畳パターン
    for y in range(GROUND_Y, H-30):
        c = PAL['ground'] if ((y - GROUND_Y) // 4) % 2 == 0 else PAL['ground_lo']
        d.line([(0,y),(W,y)], fill=c)

    cx = W // 2
    # ── 武者返し風 石垣ベース (台形・上が狭く下が広い) ──
    # 石垣の頂点と底辺・勾配 (cmd_447 大坂城の如く)
    base_top_y = 158
    base_bot_y = GROUND_Y
    base_top_w = 80   # 上辺幅
    base_bot_w = 120  # 下辺幅
    pts = [(cx-base_top_w//2, base_top_y),
           (cx+base_top_w//2, base_top_y),
           (cx+base_bot_w//2, base_bot_y),
           (cx-base_bot_w//2, base_bot_y)]
    d.polygon(pts, fill=PAL['castle_stone'], outline=PAL['castle_dark'])
    # 石垣の石ブロック模様 (千鳥配置・縦縞)
    for layer in range(0, 5):
        ly = base_top_y + layer * ((base_bot_y-base_top_y) // 5)
        ly2 = base_top_y + (layer+1) * ((base_bot_y-base_top_y) // 5)
        # この層の幅
        lw_top = base_top_w + (base_bot_w-base_top_w) * layer // 5
        lw_bot = base_top_w + (base_bot_w-base_top_w) * (layer+1) // 5
        # 横線
        d.line([(cx-lw_top//2, ly), (cx+lw_top//2, ly)], fill=PAL['castle_dark'])
        # 縦線(千鳥)
        offset = 8 if layer % 2 == 0 else 0
        for bx in range(-lw_top//2 + offset, lw_top//2, 16):
            d.line([(cx+bx, ly), (cx+bx, ly2)], fill=PAL['castle_dark'])

    # ── 天守3層 (下層→中層→上層) 各層で反り屋根 ──
    # ─ 最下層: 大屋根 + 漆喰壁 ─
    # 漆喰壁(白)
    w1_y1, w1_y2, w1_hw = 122, 158, 48
    d.rectangle([cx-w1_hw, w1_y1, cx+w1_hw, w1_y2], fill=(252, 248, 232), outline=PAL['castle_dark'])
    # 連子窓 (黒い窓格子)
    for wx in range(cx-w1_hw+10, cx+w1_hw-9, 14):
        d.rectangle([wx, w1_y1+8, wx+6, w1_y2-8], fill=PAL['outline'])
        d.line([(wx+3, w1_y1+8), (wx+3, w1_y2-8)], fill=(232, 232, 200), width=1)
    # 大屋根 (反り曲線)
    _japanese_roof(d, cx, w1_y1, half_w=58, height=14, eave=8)

    # ─ 中層 ─
    w2_y1, w2_y2, w2_hw = 92, 122, 34
    d.rectangle([cx-w2_hw, w2_y1, cx+w2_hw, w2_y2], fill=(252, 248, 232), outline=PAL['castle_dark'])
    # 窓
    for wx in range(cx-w2_hw+6, cx+w2_hw-5, 12):
        d.rectangle([wx, w2_y1+6, wx+5, w2_y2-6], fill=PAL['outline'])
    # 破風 (中央の三角装飾) — 切妻破風
    d.polygon([(cx-12, w2_y1+5), (cx+12, w2_y1+5), (cx, w2_y1-4)],
              fill=PAL['castle_roof'], outline=PAL['roof_dark'])
    d.line([(cx, w2_y1-4), (cx, w2_y1+5)], fill=PAL['roof_dark'])
    # 中屋根
    _japanese_roof(d, cx, w2_y1, half_w=42, height=10, eave=6)

    # ─ 上層 (天守最上階) ─
    w3_y1, w3_y2, w3_hw = 66, 92, 22
    d.rectangle([cx-w3_hw, w3_y1, cx+w3_hw, w3_y2], fill=(252, 248, 232), outline=PAL['castle_dark'])
    # 上層 高欄(廻縁)
    d.rectangle([cx-w3_hw-3, w3_y2-3, cx+w3_hw+3, w3_y2+1], fill=PAL['castle_dark'])
    # 上層窓 (中央に華頭窓)
    d.rectangle([cx-6, w3_y1+6, cx+6, w3_y2-6], fill=PAL['outline'])
    d.arc([cx-6, w3_y1+3, cx+6, w3_y1+13], 180, 0, fill=PAL['outline'])
    # 上層屋根 (反り強め)
    _japanese_roof(d, cx, w3_y1, half_w=28, height=9, eave=5)

    # ── 鯱(しゃちほこ) ──
    shachi_y = w3_y1 - 8  # 屋根の上
    # 左右に対の鯱
    for sx in [-22, 22]:
        d.polygon([(cx+sx-2, shachi_y),
                   (cx+sx+2, shachi_y),
                   (cx+sx+3, shachi_y-6),
                   (cx+sx, shachi_y-9),
                   (cx+sx-3, shachi_y-6)],
                  fill=PAL['shogun_helm'], outline=PAL['outline'])
        # 尾びれ
        d.line([(cx+sx-3, shachi_y), (cx+sx-5, shachi_y+2)], fill=PAL['outline'])
        d.line([(cx+sx+3, shachi_y), (cx+sx+5, shachi_y+2)], fill=PAL['outline'])

    # ── 旗 (城の天頂) ──
    d.line([(cx, shachi_y-9), (cx, 40)], fill=PAL['flag_pole'], width=2)
    # 旗本体 (はためき・frame依存はしないので静的)
    d.polygon([(cx, 44), (cx+14, 48), (cx+12, 54), (cx, 56)],
              fill=PAL['flag_red'], outline=PAL['outline'])
    # 旗の家紋風マーク
    d.ellipse([cx+4, 49, cx+10, 53], fill=PAL['shogun_helm'])


def _japanese_roof(d: ImageDraw.ImageDraw, cx: int, top_y: int,
                   half_w: int, height: int, eave: int):
    """反り屋根 — 端が跳ね上がる日本建築特有のカーブ
    cx: 中央x / top_y: 屋根の下端y(壁の上端) / half_w: 半幅 / height: 屋根高 / eave: 端の跳ね上げ
    """
    # 主屋根の点列(左→上→右) — 端を eave 分跳ね上げ・中央は height 高い
    # 簡略: 5点 polygon で曲線風を近似
    apex_y = top_y - height
    eave_y = top_y - eave  # 端の上向きカーブ
    pts = [
        (cx - half_w, top_y + 2),     # 左端 軒先(やや下)
        (cx - half_w + 3, eave_y),    # 跳ね上がり
        (cx - half_w//2, apex_y + 2), # 中間左
        (cx, apex_y),                  # 頂点
        (cx + half_w//2, apex_y + 2), # 中間右
        (cx + half_w - 3, eave_y),    # 跳ね上がり
        (cx + half_w, top_y + 2),     # 右端 軒先
    ]
    d.polygon(pts, fill=PAL['castle_roof'], outline=PAL['roof_dark'])
    # 棟瓦 (頂点の横線)
    d.line([(cx-half_w+3, eave_y+2), (cx+half_w-3, eave_y+2)], fill=PAL['roof_dark'], width=1)
    # 軒先の暗色強調
    d.line([(cx-half_w, top_y+2), (cx+half_w, top_y+2)], fill=PAL['roof_dark'], width=1)


def state_color(state: str) -> tuple:
    return dict(work=PAL['st_work'], idle=PAL['st_idle'],
                freeze=PAL['st_freeze'], offline=PAL['st_offline'],
                wake=PAL['st_wake']).get(state, PAL['st_idle'])


def state_icon(state: str, frame_idx: int) -> str:
    """状態別アイコン (frame連動アニメ)
    idle: Z → ZZ → ZZZ
    work: ⚒ → ⚔ → ⚒ (槌振り上げ・下げ)
    freeze: ! → ‼ → !
    offline: - → -- → ---
    wake: ? → ?? → ???
    """
    cycles = {
        'idle':    ['Z', 'ZZ', 'ZZZ'],
        'work':    ['⚒', '⚔', '⚒'],
        'freeze':  ['!', '!!', '!!!'],
        'offline': ['', '', ''],
        'wake':    ['?', '??', '???'],
    }
    arr = cycles.get(state, ['Z','ZZ','ZZZ'])
    return arr[frame_idx % len(arr)]


def draw_thought_balloon(d: ImageDraw.ImageDraw, x: int, y: int,
                          width: int, height: int, color: tuple,
                          outline: tuple = (16,16,16)):
    """考え/眠り用のフキダシ枠 (楕円+小さい点)"""
    d.ellipse([x, y, x+width, y+height], fill=color, outline=outline)
    # 小さい泡 (balloon下に2つ)
    d.ellipse([x+2, y+height-1, x+6, y+height+3], fill=color, outline=outline)
    d.ellipse([x, y+height+3, x+3, y+height+6], fill=color, outline=outline)


# ─── 配置 ─────────────────────────────────────────────────────────────────

# 軍勢配置: 城の前に布陣 / 上段=指揮官3名 / 下段=足軽7名
# 各 sprite scale=2 → 32x32 表示

SPRITE_PIXEL = 32  # 16*2

POSITIONS = {
    # 指揮官 (城前・地面より少し奥) — 軍勢配置で城を背景に展開
    'shogun': (W//2 - 16, 200),                # 中央 (将軍は最前で指揮)
    'karo':   (W//2 - 80, 205),                # 左
    'gunshi': (W//2 + 48, 205),                # 右
    # 足軽 (最前列・横並び)
    'ashigaru1': (40, 268),
    'ashigaru2': (95, 268),
    'ashigaru3': (150, 268),
    'ashigaru4': (205, 268),
    'ashigaru5': (260, 268),
    'ashigaru6': (315, 268),
    'ashigaru7': (370, 268),
}

LABEL_BELOW = {
    'shogun': '将軍', 'karo': '家老', 'gunshi': '軍師',
    **{f'ashigaru{i}': f'足{i}' for i in range(1, 8)},
}

STATE_LABEL_JP = {
    'work': '作業中', 'idle': '待機', 'freeze': '凍結',
    'offline': '未起動', 'wake': '思案中',
}


# ─── 描画 ─────────────────────────────────────────────────────────────────

def role_of(agent: str) -> str:
    if agent in ('shogun', 'karo', 'gunshi'):
        return agent
    return 'ashigaru'


def render_frame(fleet_name: str, status: dict, frame_idx: int) -> Image.Image:
    img = Image.new('RGB', (W, H), PAL['sky_top'])
    draw_castle_backdrop(img)
    d = ImageDraw.Draw(img)

    # ヘッダー(陣名・時刻)
    d.rectangle([0, 0, W, 24], fill=PAL['panel_bg'])
    d.rectangle([0, 22, W, 24], fill=PAL['flag_red'])
    fleet_label = {'1st': '第1陣 SCORE', '2nd': '第2陣 DISCORD', '3rd': '第3陣 COMFY'}[fleet_name]
    draw_pixel_text(img, fleet_label, 8, 5, PAL['text_white'], size=14)
    draw_pixel_text(img, datetime.datetime.now().strftime('%H:%M:%S'), W-72, 6, PAL['st_wake'], size=13)

    # 各エージェント
    for agent, pos in POSITIONS.items():
        x, y = pos
        st = status[agent]
        role = role_of(agent)
        sprite = ROLE_SPRITES[role][frame_idx % 2]
        palette = ROLE_PALETTE[role]
        # ハロー (状態色枠)
        draw_status_halo(img, x, y, SPRITE_PIXEL, SPRITE_PIXEL,
                         state_color(st['state']),
                         dim=(st['state'] == 'offline'))
        # sprite描画
        if st['state'] != 'offline':
            draw_sprite(img, sprite, palette, x, y, scale=2)
        else:
            # offline: グレーアウト sprite
            gray_pal = dict(palette)
            for k in gray_pal:
                v = gray_pal[k]
                avg = sum(v)//3
                gray_pal[k] = (avg, avg, avg)
            draw_sprite(img, sprite, gray_pal, x, y, scale=2)
        # 役名ラベル(下・日本語)
        label = LABEL_BELOW[agent]
        draw_pixel_text(img, label, x + 2, y + SPRITE_PIXEL + 1, PAL['text_white'], size=11)
        # 状態テキスト(さらに下・色付き)
        st_text = STATE_LABEL_JP.get(st['state'], '?')
        draw_pixel_text(img, st_text, x, y + SPRITE_PIXEL + 14, state_color(st['state']), size=9)
        # 進捗バー
        if st['state'] == 'work':
            bx, by, bw, bh = x, y + SPRITE_PIXEL + 26, SPRITE_PIXEL, 3
            d.rectangle([bx, by, bx+bw, by+bh], fill=PAL['bar_empty'])
            d.rectangle([bx, by, bx + bw*st['progress']//100, by+bh], fill=PAL['bar_fill'])
        # 状態アイコン(頭上・フキダシ付き・frame連動アニメ)
        ico = state_icon(st['state'], frame_idx)
        if st['state'] in ('idle', 'wake'):
            # 眠/思案: フキダシ + 大きめZZZ・高コントラスト
            bal_w = 28
            bal_h = 16
            bal_x = x + SPRITE_PIXEL // 2 - bal_w // 2 + 6   # 頭の右上方向
            bal_y = y - bal_h - 4 + (frame_idx % 2) * 2     # 上下ふんわり揺れ
            # 黒バブル＋黄色ZZZ で高視認(ファミコン的ハイコントラスト)
            bal_color = PAL['outline']  # 黒
            text_color = (252, 224, 64)  # 鮮明な黄
            draw_thought_balloon(d, bal_x, bal_y, bal_w, bal_h, bal_color, outline=text_color)
            # ZZZ センター寄せ
            # 文字幅は frame_idx で変わる (Z=1字, ZZ=2字, ZZZ=3字)
            char_w_est = 6 * len(ico)
            tx = bal_x + (bal_w - char_w_est) // 2
            ty = bal_y + 1
            draw_pixel_text(img, ico, tx, ty, text_color, size=13)
        elif st['state'] == 'work':
            # 作業中: 大きいハンマー
            draw_pixel_text(img, ico, x + SPRITE_PIXEL - 4, y - 16 + (frame_idx % 2)*2,
                            PAL['st_work'], size=14)
        elif st['state'] == 'freeze':
            # 凍結: 赤い"!"が震える
            shake = 2 if frame_idx % 2 == 0 else -2
            draw_pixel_text(img, ico, x + SPRITE_PIXEL - 6 + shake, y - 14,
                            PAL['st_freeze'], size=14)
        else:
            # offline: 何も表示せず
            pass

    # フッター: 集計
    d.rectangle([0, H-30, W, H], fill=PAL['panel_bg'])
    d.rectangle([0, H-30, W, H-28], fill=PAL['flag_red'])
    cnt = {'work': 0, 'idle': 0, 'freeze': 0, 'offline': 0, 'wake': 0}
    for ag, st in status.items():
        cnt[st['state']] = cnt.get(st['state'], 0) + 1
    summary = f"作業:{cnt['work']:2d}  待機:{cnt['idle']:2d}  凍結:{cnt['freeze']:2d}  未起動:{cnt['offline']:2d}  /10"
    draw_pixel_text(img, summary, 8, H - 22, PAL['text_white'], size=12)
    # 凡例 (右側)
    legend_y = H - 22
    legend_x = 250
    items = [('作業', PAL['st_work']), ('待機', PAL['st_idle']),
             ('凍結', PAL['st_freeze']), ('未起動', PAL['st_offline'])]
    for i, (txt, col) in enumerate(items):
        d.rectangle([legend_x + i*55, legend_y, legend_x + i*55 + 8, legend_y + 8], fill=col, outline=PAL['outline'])
        draw_pixel_text(img, txt, legend_x + i*55 + 11, legend_y - 1, PAL['text_white'], size=9)

    return img


def render_gif(fleet_name: str, root: str, out_path: str):
    status = collect_fleet_status(fleet_name, root)
    # 3フレーム loop (Z→ZZ→ZZZ アニメ)
    frames = [render_frame(fleet_name, status, i) for i in range(3)]
    frames[0].save(out_path, save_all=True, append_images=frames[1:],
                   duration=420, loop=0, optimize=True)
    return status


# ─── main ─────────────────────────────────────────────────────────────────
def main():
    out_dir = Path('/tmp')
    print(f'famicom_board generator @ {datetime.datetime.now()}')
    for name, root in FLEETS.items():
        out = out_dir / f'famicom_board_{name}.gif'
        try:
            st = render_gif(name, root, str(out))
            print(f'  {name}: -> {out}')
            print(f'    {sum(1 for s in st.values() if s["state"]=="work"):d} work, '
                  f'{sum(1 for s in st.values() if s["state"]=="idle"):d} idle, '
                  f'{sum(1 for s in st.values() if s["state"]=="freeze"):d} freeze, '
                  f'{sum(1 for s in st.values() if s["state"]=="offline"):d} offline')
        except Exception as e:
            print(f'  {name}: ERROR {e}')
            import traceback; traceback.print_exc()
    print('done.')


if __name__ == '__main__':
    main()
