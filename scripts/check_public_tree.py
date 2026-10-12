"""Conservative pre-release tracked-file and relative-document-link checks.
Never prints candidate secrets; not a complete security or license audit.
"""
import re
import subprocess
from pathlib import Path
from urllib.parse import unquote

root=Path(__file__).resolve().parents[1]
files=subprocess.check_output(['git','ls-files','-z'],cwd=root).decode().split('\0')
files=[f for f in files if f]
problems=[]
credentials=re.compile(r'(?:github_pat_[A-Za-z0-9_]{30,}|gh[pousr]_[A-Za-z0-9]{30,}|sk-(?:proj-)?[A-Za-z0-9_-]{24,}|AKIA[A-Z0-9]{16}|-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----)')
for name in files:
    path=root/name
    if path.is_symlink():problems.append((name,'symlink'))
    if any(part in {'.venv','node_modules','verification','runtime','__pycache__'} for part in path.relative_to(root).parts):
        problems.append((name,'runtime artifact'))
    if path.suffix in {'.db','.sqlite3','.zip','.log','.mp4','.wav','.m4a'} or path.name in {'.env','.vault-key'}:
        problems.append((name,'sensitive/runtime type'))
    if path.suffix in {'.png','.jpg','.jpeg'}:continue
    try:text=path.read_text()
    except UnicodeDecodeError:problems.append((name,'unexpected binary'));continue
    if credentials.search(text):problems.append((name,'possible credential'))
    if name != 'scripts/check_public_tree.py' and re.search(r'/Users/mac/|九阳|乡乡嘴',text,re.IGNORECASE):
        problems.append((name,'private path/client material'))
    if re.search(r'\b[A-Za-z0-9._%+-]+@(?:gmail|outlook|hotmail)\.com\b',text,re.IGNORECASE):
        problems.append((name,'personal email'))
    if path.suffix=='.md':
        for target in re.findall(r'\]\(([^)]+)\)',text):
            target=target.strip('<>').split('#',1)[0]
            if not target or '://' in target or target.startswith('mailto:'):continue
            if not (path.parent/unquote(target)).exists():problems.append((name,'missing link: '+target))
if problems:
    for name,kind in problems:print(name,kind)
    raise SystemExit(1)
print(f'Checked {len(files)} tracked files: no flagged credentials, runtime/client artifacts or missing relative links.')
