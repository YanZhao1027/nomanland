@echo off
python terra_storyboard_qwen_batch.py h3-manifest ^
  --manifest terra_storyboard_manifest.jsonl ^
  --approved-dir approved ^
  --output terra_h3_from_approved.jsonl
pause