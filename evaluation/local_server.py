"""Launch the acceptance host with an existing local gateway environment."""
import argparse
import os
from pathlib import Path

from dotenv import load_dotenv
import uvicorn

parser = argparse.ArgumentParser()
parser.add_argument('workspace')
parser.add_argument('--gateway-env', type=Path)
args = parser.parse_args()
if args.gateway_env:
    load_dotenv(args.gateway_env, override=True)
os.environ['MYTHFALL_EVALUATION_WORKSPACE'] = args.workspace
os.environ['REALM_ENGINE_SESSION_UUID'] = '8ddbb387-851d-44dc-acd1-9285b8c846d5'
uvicorn.run('evaluation.server:app', host='127.0.0.1', port=8831)
