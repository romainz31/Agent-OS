"""Isolate V10 data even if an earlier version exported environment variables."""
import os
import runpy
from pathlib import Path
root=Path(__file__).resolve().parent
os.chdir(root)
os.environ['AGENTOS_DATA_DIR']=str(root/'data')
os.environ['AGENTOS_WORKSPACE_DIR']=str(root/'workspace')
os.environ.setdefault('AGENTOS_VISION_MODEL','qwen2.5vl:3b')
runpy.run_path(str(root/'api_server.py'),run_name='__main__')
