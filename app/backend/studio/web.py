from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from .api import create_app, default_root


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--data-dir",type=Path,default=default_root())
    parser.add_argument("--port",type=int,default=8768)
    args=parser.parse_args()
    uvicorn.run(create_app(args.data_dir),host="127.0.0.1",port=args.port,log_level="warning")


if __name__=="__main__":main()
