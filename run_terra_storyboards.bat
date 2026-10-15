@echo off
python terra_storyboard_qwen_batch.py generate ^
  --workflow workflows\qwen_image_api.json ^
  --node-map qwen_nodes.json ^
  --manifest terra_storyboard_manifest.jsonl ^
  --variants 4 ^
  --include-endframes ^
  --resume
pause