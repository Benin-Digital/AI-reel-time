# RH Sync Agent

This agent watches local CV/JOB folders on RH machines and uploads changed files to the VPS `/ingest` endpoint.

## Install

```bash
pip install -r agent/requirements.txt
```

## Run

```bash
python agent/sync_agent.py \
  --cv-dir "/path/to/cv" \
  --job-dir "/path/to/job" \
  --api-base "http://vps.example.com:8000" \
  --api-key "YOUR_KEY"
```

You can also set the API key via environment variable:

```bash
export AI_REALTIME_API_KEY="YOUR_KEY"
```

## Notes

- Supported file types: `.pdf`, `.docx`, `.txt`.
- Debounce and retry are enabled by default.
- Deletions are synced to the VPS (remote file removed).
- State is stored in `~/.ai-realtime-sync/state.json`.
