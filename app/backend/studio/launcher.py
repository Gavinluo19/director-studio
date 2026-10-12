from __future__ import annotations

import argparse
import os
import signal
import socket
import webbrowser
import subprocess
import sys
import time
from pathlib import Path

from .api import default_root
from .database import Database
from .vault import Vault


def main():
    parser=argparse.ArgumentParser(description="启动片场后台与独立任务进程")
    parser.add_argument("--data-dir",type=Path,default=default_root())
    parser.add_argument("--port",type=int,default=8768)
    parser.add_argument("--open-browser", action="store_true")
    args=parser.parse_args()
    if not 1024 <= args.port <= 65535:parser.error('端口必须在 1024 到 65535 之间')
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(('127.0.0.1',args.port));probe.listen(1)
        except OSError:parser.exit(1, f'端口 {args.port} 已被占用。未启动额外任务进程。\n')
    args.data_dir.mkdir(parents=True,exist_ok=True)
    logs=args.data_dir/'logs'
    logs.mkdir(exist_ok=True,mode=0o700)
    # One supervisor per data directory. Job leases remain the second safeguard.
    lock=(args.data_dir/'studio.lock').open('a+')
    if os.name=='posix':
        import fcntl
        try:fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:parser.exit(1,'此数据目录已有片场主进程，请使用现有窗口。\n')
    # Initialize the encryption key before launching two processes.
    Vault(Database(args.data_dir))
    env=dict(os.environ,LANGSMITH_TRACING="false",LANGCHAIN_TRACING_V2="false")
    commands={"api":[sys.executable,"-m","studio.web","--data-dir",str(args.data_dir),"--port",str(args.port)],
              "worker":[sys.executable,"-m","studio.worker","--data-dir",str(args.data_dir)]}
    handles={k:(logs/(k+'.log')).open('a',encoding='utf-8') for k in commands}
    processes={k:subprocess.Popen(v,env=env,stdout=handles[k],stderr=subprocess.STDOUT) for k,v in commands.items()}
    stopping=False
    def stop(*_):
        nonlocal stopping
        stopping=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    restarts={k:0 for k in commands}
    print(f"片场后台：http://127.0.0.1:{args.port} · 数据目录：{args.data_dir}",flush=True)
    print(f"运行日志：{logs} · 保持此终端打开；Control+C 停止服务",flush=True)
    browser_opened = False
    try:
        while not stopping:
            if args.open_browser and not browser_opened:
                try:
                    from urllib.request import urlopen
                    with urlopen(f'http://127.0.0.1:{args.port}/api/health',timeout=.5) as response:
                        if response.status==200:
                            webbrowser.open(f'http://127.0.0.1:{args.port}/');browser_opened=True
                except (OSError,TimeoutError):pass
            for name,process in list(processes.items()):
                if process.poll() is not None:
                    if restarts[name]>=3:
                        print(f"{name} 连续启动失败，请检查本地日志和端口。",flush=True);stopping=True;break
                    restarts[name]+=1
                    processes[name]=subprocess.Popen(commands[name],env=env,stdout=handles[name],stderr=subprocess.STDOUT)
            time.sleep(1)
    finally:
        for process in processes.values():
            if process.poll() is None:process.terminate()
        for process in processes.values():
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill();process.wait()
        lock.close()
        for handle in handles.values():handle.close()


if __name__=="__main__":main()
