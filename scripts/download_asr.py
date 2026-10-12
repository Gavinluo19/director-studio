"""Explicitly download only the optional local ASR model; never upload media."""
import argparse
from pathlib import Path

parser = argparse.ArgumentParser(description="Prepare optional local Whisper weights")
parser.add_argument('--yes', action='store_true', help='Confirm the model download')
args = parser.parse_args()
if not args.yes:
    parser.exit(2, '下载会使用网络和磁盘；确认后加 --yes。先查看模型许可证。\n')
from huggingface_hub import snapshot_download

cache = Path.home() / '.cache/huggingface/hub'
path = snapshot_download('mlx-community/whisper-large-v3-turbo', cache_dir=str(cache),
                         allow_patterns=['*.json', '*.safetensors', '*.md'])
print('本地权重已准备 / Model cached:', path)
print('刷新工作台“能力与方法”。没有上传任何视频或音频。')
