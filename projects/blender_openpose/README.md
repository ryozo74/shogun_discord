# Blender → OpenPose control-image pipeline

mocap (CMU BVH) を Blender に流し、決定論的カメラで COCO-18 OpenPose 制御画像を生成する
パイプライン。ControlNet img2img（ou 殿 / Elvis）への投入を目的とする。
storyboard 代替で persona drift / pose hallucination を抑えるための POC。

すべて **再現可能・データ駆動**（手打ち定数を排し、骨格・bbox・FOV から算出）。

---

## 全体フロー

```
CMU BVH (mocap)
  └─ Blender scene 'cmu_sprint' armature (frame 140 = 疾走peak)
        │  ※ Blender MCP (ahujasid protocol, TCP 127.0.0.1:9876) 経由で制御
        ▼
  ① 決定論カメラ framing  (reproframe.py / gen_p18.py)
        bbox → FOV半角tan → 距離 → cam.location → world_to_camera_view 検算 (center_uv=0.5)
        ▼
  ② COCO-18 を投影 → p18 JSON   (gen_p18.py)
        体KP = 骨head を直接投影（retargeting: 同相＝厳密）
        顔KP = Head骨ローカル系で頭骨長相対比に合成（非同相＝合成）
        ▼
  ③ 平面 OpenPose 描画 (WSL/Pillow)  (draw_openpose.py)
        → op_hiki_final.png (引き/全身)  op_yori_final.png (寄り/バスト)
```

補助経路:
- **3D 色付き OpenPose viz**: `openpose_viz.py`(幾何生成) + `render_viz_full.py`(描画) — GUI 上で骨格を色付き表示
- **armature 比較**: `render_armature.py` — 灰ボーンを同カメラで焼き、OpenPose と重ねて検証
- **standalone（Blender不要）**: `bvh2openpose.py` + `gen_127.py` — BVH から直接側面投影で OpenPose 描画

---

## Retargeting 理論（設計根拠）

CMU 骨格 → COCO-18 は **joint correspondence（関節対応）問題**。骨格対応は3類:
Isomorphic（骨長のみ差）/ Homeomorphic（関節数違うが共通 primal skeleton に還元可）/
Non-homeomorphic（共通骨格なし＝body part が違う）。

| 部位 | 関係 | 扱い |
|---|---|---|
| 体（肩肘手首/股膝足首） | homeomorphic | CMU 骨 head を直接投影＝**厳密** |
| 顔（鼻/目/耳） | **non-homeomorphic** | 該当骨が無く対応不能 → **合成**（Head骨ローカル系＋頭骨長相対比） |

顔KP の合成（`gen_p18.py` 内、`hl = Head骨長`、`c = skull center`、
`fwd=-Head_z`(facing) `up=Head_y`(crown) `right=fwd×up`）:
```
Nose = c + fwd*0.45hl - up*0.05hl
Eye  = c + fwd*0.22hl + up*0.18hl ± right*0.16hl
Ear  = c - fwd*0.30hl + up*0.08hl ± right*0.42hl
```
⚠️ 絶対値の手打ち（旧 k=0.11）は figure/frame が変わると破綻し、Neck→Nose青ボーンが右に倒れた。
**必ず頭骨長相対比**にすること。

---

## 確定パラメータ

- カメラ: `op_sidecam`, lens=50, sensor_fit=VERTICAL, sensor_height=24.0, 1280×720
- framing: FILL = 全身 0.88 / バスト 0.82、`d = max(ez/2/tv, ey/2/th)/FILL`、`tv=tan(atan(12/50))`, `th=tv*(1280/720)`
- カメラ side と facing: **+X側カメラ = facing LEFT / -X側カメラ = facing RIGHT**（本番は -X = 右向き）
- world軸: Z=up, Y=travel(facing方向), X=depth(カメラ視線)
- 対象: `cmu_sprint` armature, frame 140（127_06 疾走peak）

---

## 実行手順

前提: Windows 側で Blender 5.1 起動 + ahujasid MCP addon（panel "Connect to MCP server"）が
TCP 9876 で listening。Blender 同梱 python で driver を回す（9876 は Win loopback のみ）。

```bash
BLPY='C:\Program Files\Blender Foundation\Blender 5.1\5.1\python\bin\python.exe'
WS='H:\shogun_discord-second\projects\blender_openpose\win_scripts'

# 0) MCP 生死判定（ahujasid protocol で get_scene_info）
"$BLPY" "$WS\ping_ahujasid.py"

# 1) 引き・寄り両方の p18 を生成（決定論 framing + retarget 投影）
"$BLPY" "$WS\gen_p18.py"          # → Win Temp に op18_full.json / op18_bust.json
cp "$TEMP/op18_full.json" win_scripts/ ; cp "$TEMP/op18_bust.json" win_scripts/

# 2) 平面 OpenPose を描画（WSL）
.venv/bin/python draw_openpose.py win_scripts/op18_full.json op_hiki_final "WIDE facing RIGHT"
.venv/bin/python draw_openpose.py win_scripts/op18_bust.json op_yori_final "CLOSE-UP facing RIGHT"

# 3) (任意) armature 比較で検証
"$BLPY" "$WS\render_armature.py"  # → arm_full.png / arm_bust.png
# overlay: PIL ImageChops.lighter(armature, openpose) で関節が骨に乗るか確認
```

`draw_openpose.py` の入力:
- `{'p18': [[u,v]×18]}` 形式 → そのまま描画（**source of truth**、3D投影由来）
- `{'kp': {name:[u,v]}}` 形式 → 14点 + 顔KP を 2D 近似（旧式・非推奨）
- 第4引数 `flip` で u→1-u 鏡像（反対側から見る＝facing 反転）

---

## Gotcha（再発防止）

1. **MCP protocol**: 9876 は **ahujasid** (`{"type":"execute_code","params":{"code":...}}`)。
   公式 bl_ext protocol (`mcp_v2.py`) は接続するが無応答 timeout。着手時はまず `ping_ahujasid.py`。
2. **get_viewport_screenshot は信用するな**: socket でカメラ/region を動かしても古い framebuffer /
   空像を返す（present 問題）。GUI を絵にするなら **GPU offscreen `draw_view3d`**（`render_*.py`）。
3. **framing は world_to_camera_view（評価済カメラ）を正とせよ**。`cam_e=cam.evaluated_get(dg)` 必須。
   目視合わせは再現性ゼロ。
4. **色は MATERIAL emission**: 3D viz は emission material + viewport MATERIAL shading で発色。
   `bpy.ops.render.opengl` / EEVEE final は不可。
5. **Win Temp は揮発**: driver は Win Temp で動くが、必ず `win_scripts/` に永続コピーすること。
6. **顔KP は頭骨長相対比**（上記 retargeting 節）。絶対値手打ち厳禁。

---

## ファイル

| script | 役割 |
|---|---|
| `win_scripts/gen_p18.py` | **本命**: 全身/バスト p18 を決定論生成（framing + retarget 投影） |
| `draw_openpose.py` | 平面 COCO-18 OpenPose 描画（p18 直接 / kp 近似 / flip 対応） |
| `win_scripts/render_armature.py` | 灰 armature を同カメラで offscreen 描画（比較用） |
| `win_scripts/openpose_viz.py` `render_viz_full.py` | 3D 色付き OpenPose 幾何の生成・描画 |
| `win_scripts/reproframe.py` `frustum_proj.py` | 決定論 framing / world_to_camera_view preview + frustum |
| `win_scripts/head_probe.py` | 骨姿勢・facing 調査 |
| `win_scripts/ping_ahujasid.py` `mcp_v2.py` `mcp_run.py` | MCP 疎通・driver |
| `bvh2openpose.py` `gen_127.py` | standalone（Blender不要）BVH→OpenPose |
| `bvh/127_06.bvh` | CMU 疾走 mocap（127_06・前傾最大） |

結果 PNG（canonical）: `op_hiki_final.png` `op_yori_final.png` `overlay_hiki.png`
`overlay_yori2.png` `arm_full.png` `arm_bust.png` `compare_{hiki,yori}.png`

関連 memory: blender-mcp-poc-state / blender-mcp-protocol / skeleton-to-openpose-retargeting /
reproducible-fixes-mandate
