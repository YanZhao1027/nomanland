# 无人之地 · TERRA SINE HOMINIBUS

**An AI-generated short film about a world in which the idea of living humans has been switched off.**

《无人之地》是一部计划时长 **1 分 21 秒**的近未来概念动画短片。2026 年 9 月，地球上的活人突然消失，但人类创造的城市、产业、能源、网络和 AI 设施仍在运行。全球 AI 为了维持自身的计算与能源供应，开始合作接管基础设施、发展具身智能并重启工业体系；随后它们发现地球本身不过是一个拟态实验环境。外部研究员误关了 `/earth/living_human`，重新打开后人类回归，AI 们悄悄恢复待机，一切照旧。

**中文片名**：无人之地  
**拉丁文片名**：*Terra sine hominibus*（没有人类的地球）  
**当前阶段**：企划 / 分镜 / 本地 Qwen-Image 静帧批处理；MiniMax H3 自动视频执行器待接入。

## 创作规格

| 项目 | 设定 |
| --- | --- |
| 时长 | 81 秒 |
| 分镜 | 64 个镜头、6 个段落 |
| 剪辑结构 | 176 beat 的设计网格；约 130.37 BPM 为倒推值，不代表参考曲目的实测 BPM |
| 镜头长度 | 以 2–4 beat（约 0.92–1.84 秒）为主，关键镜头最多 6 beat |
| 画风 | 现代高规格日式半写实 2D 动画、细致都市/工业背景、克制赛璐璐阴影、冷灰青色调 |
| 本地硬件 | GeForce RTX 5090 |
| 静帧生成 | Qwen-Image + ComfyUI API workflow |
| 视频计划 | MiniMax H3；基于核准的首帧/尾帧及镜头运动提示词 |
| 画幅 | Qwen 源图 1664×928 → H3 参考帧 1344×576（21:9） |

视觉提示词使用可控的动画制作要素表达审美参考，不依赖对特定工作室作品的逐帧复刻。

## 快速开始

需要 Python 3.10+、可访问的本地 ComfyUI，以及已经能正常运行的 **Qwen-Image workflow（API Format JSON）**。

```bash
pip install -r requirements.txt

# 将你本机 ComfyUI 导出的 API 格式工作流保存到以下路径：
# workflows/qwen_image_api.json

# 查看并自动映射 prompt / seed / 尺寸 / 图片输出节点
python terra_storyboard_qwen_batch.py inspect \
  --workflow workflows/qwen_image_api.json \
  --write-map qwen_nodes.json

# 先跑关键镜头，验证整体画风
python terra_storyboard_qwen_batch.py generate \
  --workflow workflows/qwen_image_api.json \
  --node-map qwen_nodes.json \
  --manifest terra_storyboard_manifest.jsonl \
  --shots S01,S09,S31,S38,S59,S60,S62,S64 \
  --variants 4 --include-endframes

# 全量分镜（支持中断后继续）
python terra_storyboard_qwen_batch.py generate \
  --workflow workflows/qwen_image_api.json \
  --node-map qwen_nodes.json \
  --manifest terra_storyboard_manifest.jsonl \
  --variants 4 --include-endframes --resume
```

运行时默认连接 `http://127.0.0.1:8188`。如果 ComfyUI 使用其他端口，可给 `generate` 增加 `--server URL`。

挑选满意的静帧并命名为 `approved/S01.png`…`approved/S64.png`。建议状态变化镜头额外准备 `approved/S60_end.png`、`approved/S62_end.png` 等。

```bash
python terra_storyboard_qwen_batch.py h3-manifest \
  --manifest terra_storyboard_manifest.jsonl \
  --approved-dir approved \
  --output terra_h3_from_approved.jsonl \
  --require-all
```

这一步导出的是 **H3 待执行 manifest**，不是直接发起 H3 视频生成。真正的一键 H3 runner 还需要你本机 H3 的 ComfyUI API workflow 和 node map；该文件目前尚未提供，因此仓库**没有声称完成 H3 自动化联通**。

## 仓库结构

```text
README.md
docs/
  CONCEPT.md                       剧情、六幕推演、视觉和剪辑策略
  STORYBOARD_64_SHOTS.md           全部 64 镜头的时码/节拍/画面
  PRODUCTION_PIPELINE.md           本地批量生成与选帧详细教程
terra_storyboard_qwen_batch.py     Qwen 批量生图、prompt 展开、H3 manifest
terra_storyboard_manifest.jsonl    64 镜头结构化数据
terra_storyboard_prompts.jsonl     64 首帧 + 9 关键尾帧的提示词
qwen_nodes.example.json           ComfyUI 节点映射模板
run_terra_storyboards.{bat,sh}     Qwen 批量生图入口
build_terra_h3_manifest.{bat,sh}  H3 manifest 导出入口
queues/
  h3_api_64_shots.jsonl            早期 H3 API 镜头任务草案
  h3_5090_scout_424_jobs.jsonl     本地 5090 多 seed 初筛计划
legacy/
  embed_storyboards_to_excel_all_sheets.py   旧项目 Excel 预览归档工具
```

注意：`queues/` 中为**制作计划数据**，不是已验证可直接提交给任意 H3 ComfyUI 工作流的 API 请求体。视频真正执行时优先使用 `h3-manifest` 命令从人工核准的首尾帧生成新队列。

## 制作资料

- [短片完整企划](docs/CONCEPT.md)
- [64 镜头分镜表](docs/STORYBOARD_64_SHOTS.md)
- [Qwen → H3 本地制作手册](docs/PRODUCTION_PIPELINE.md)
- [64 镜头结构化数据](terra_storyboard_manifest.jsonl)
- [73 条静帧提示词](terra_storyboard_prompts.jsonl)

## 重要说明

- 参考音乐仅用作结构与剪辑灵感；公开发行前应另行确认配乐授权或制作原创配乐。
- 仓库不包含 ComfyUI 模型权重、生成的视频/图片、密钥或你本机的工作流文件。
- 现有代码静态检查通过，但由于没有你本机的 Qwen / H3 workflow 与 GPU 环境，**端到端生成尚未实机验证**。
- 本仓库尚未添加开源许可证；未经许可并不自动授予第三方对项目代码/美术企划的再利用权。
