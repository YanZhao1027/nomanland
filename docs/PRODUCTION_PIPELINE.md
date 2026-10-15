# 《无人之地 / TERRA SINE HOMINIBUS》本地 Qwen-Image → H3 管线

这套文件把 64 镜头分成两个资产阶段：

1. **Qwen-Image 分镜静帧**：每镜多 seed 抽图；关键状态变化镜头额外生成尾帧。
2. **MiniMax H3 视频**：只消费人工挑中的 `approved/Sxx.png`（以及可选 `Sxx_end.png`），因此以后换 H3 workflow 时不需要重做分镜资产。

## 文件

- `terra_storyboard_qwen_batch.py`：主批处理器。
- `terra_storyboard_manifest.jsonl`：64 镜头结构化分镜数据。
- `terra_storyboard_prompts.jsonl`：已展开的 Qwen 正/负 prompt 和 H3 motion prompt，方便人工审阅。
- `qwen_nodes.example.json`：ComfyUI 节点映射示例。
- `run_terra_storyboards.bat/.sh`：默认一键跑全部静帧。
- `build_terra_h3_manifest.bat/.sh`：从 approved 目录导出 H3 队列。

## 0. Qwen 工作流准备

在你现有的 ComfyUI Qwen-Image workflow 中，保留你已经调好的模型、LoRA、sampler、steps、CFG 等。脚本只需要改：

- positive prompt
- negative prompt（如果工作流有）
- seed / noise_seed
- width / height
- SaveImage 的 filename_prefix

把 workflow 用 **API Format** 导出成：

`workflows/qwen_image_api.json`

不要用普通 UI workflow JSON；普通 JSON 有 `nodes` / `links` 数组，API JSON 是以节点 ID 为 key 的对象。

## 1. 自动识别节点

```bash
python terra_storyboard_qwen_batch.py inspect \
  --workflow workflows/qwen_image_api.json \
  --write-map qwen_nodes.json
```

打开 `qwen_nodes.json` 检查一次。复杂 workflow 如果有多个 Text Encode / latent size / sampler 节点，手动把 node id 改成你真正使用的那几个即可。

## 2. 先只跑 anchor shots

```bash
python terra_storyboard_qwen_batch.py generate \
  --workflow workflows/qwen_image_api.json \
  --node-map qwen_nodes.json \
  --manifest terra_storyboard_manifest.jsonl \
  --shots S01,S09,S31,S38,S59,S60,S62,S64 \
  --variants 4 \
  --include-endframes
```

建议先锁这几类资产：空城市、数据中心、具身机器人设计、机器人第一次进城、拟态地球、外部实验室、人类恢复、结尾办公室。

## 3. 全量跑图

```bash
python terra_storyboard_qwen_batch.py generate \
  --workflow workflows/qwen_image_api.json \
  --node-map qwen_nodes.json \
  --manifest terra_storyboard_manifest.jsonl \
  --variants 4 \
  --include-endframes \
  --resume
```

默认：

- Qwen 源图：`1664x928`。
- 自动中心裁切/缩放出 H3 帧：`1344x576`，精确 21:9。
- 源图：`generated_storyboards_qwen/S01/S01_v01.png`。
- H3 帧：`generated_storyboards_h3_frames/S01/S01_v01.png`。
- 生成日志：`generated_storyboards_qwen/_generation_state.jsonl`。

Prompt 明确要求把关键构图放在 21:9 中央安全区，因此从 16:9 裁成 21:9 时尽量不切掉叙事主体。

## 4. Prompt 风格

不是只写一个工作室/作品名，而是拆成更稳定的视觉属性：

- 当代高规格日本影视动画；
- 半写实、成熟人体比例；
- 精确手绘线条；
- 克制 2–3 阶赛璐璐阴影；
- 写实建筑、机械与工业尺度；
- 3D 辅助透视，但最终画面明确保持 2D 手绘合成；
- 冷灰 / 青色主色，少量钠灯暖色；
- 写实镜头与景深，不做华丽 cyberpunk UI；
- 禁止萌系、Q 版、塑料 3D、浮夸机甲、发光机器人眼睛。

机器人还有统一 design bible：**无脸、灰白陶瓷/金属外壳、石墨关节、一条窄黑色传感器条、无眼无嘴、工具型比例、无装甲装饰**。

## 5. 查看全部展开 Prompt

脚本已经生成 `terra_storyboard_prompts.jsonl`。重新导出可以用：

```bash
python terra_storyboard_qwen_batch.py prompts \
  --manifest terra_storyboard_manifest.jsonl \
  --output terra_storyboard_prompts.jsonl \
  --include-endframes
```

一共 64 个 key frame + 9 个关键尾帧 = 73 个 prompt 条目。

## 6. 人工挑图 → approved

挑完以后只需要把最终版本复制/重命名为：

```text
approved/
  S01.png
  S02.png
  ...
  S64.png
```

关键 FLF 镜头可以再放：

```text
approved/S32_end.png
approved/S36_end.png
approved/S55_end.png
approved/S58_end.png
approved/S59_end.png
approved/S60_end.png
approved/S61_end.png
approved/S62_end.png
approved/S63_end.png
```

不提供 `_end` 也没关系，H3 manifest 会自动退回 first-frame I2V。

## 7. 导出 H3 批量任务

```bash
python terra_storyboard_qwen_batch.py h3-manifest \
  --manifest terra_storyboard_manifest.jsonl \
  --approved-dir approved \
  --output terra_h3_from_approved.jsonl
```

每条 H3 job 已包含：

- shot id / 时间码 / beats
- first frame
- optional last frame
- H3 source duration
- 1344×576 / 24 fps
- deterministic seed
- 独立 motion prompt
- camera movement
- 原中文镜头描述

这就是后续“一键 H3”的接口层。

## 8. 下一步接 H3 ComfyUI

等你把**你本机正在使用的 H3 ComfyUI workflow 也导出 API JSON**，只需要再做一份 H3 node map：

- video prompt 节点
- seed
- first-frame LoadImage
- optional last-frame LoadImage
- frame count / duration
- width / height
- SaveVideo filename prefix

然后直接让 runner 逐行消费 `terra_h3_from_approved.jsonl` 即可；分镜、prompt、时长、首尾帧命名已经不需要再改。

## 9. 你原来的 Excel 脚本

原来的 `embed_storyboards_to_excel_all_sheets(1).py` 很适合保留为**第三阶段预览/归档**：Qwen 生成完成后，再用它把选中的 PNG/JPEG 嵌回制作表。现在不再让它负责生成逻辑，避免“生成、筛选、Excel 展示”绑死在一起。