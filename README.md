# Crash Portal

Minimal local web portal for tracking kernel crashes across stable branches.
No external dependencies Python 3 stdlib only. Use crashes.json as database.

## Usage

```bash
python3 server.py          # http://127.0.0.1:8765/
python3 server.py 9000     # custom port
```

## Features

- **Import** crashes from a syzkaller `workdir/crashes/` directory (noise filtered automatically)
- **Track fix status** per branch: `linux-5.10-lvc`, `linux-6.1-lvc`, `linux-6.12-lvc`
- **Repro detection**: `prog+C` / `prog` / `C` / `repro0` / `none`
- Filter by: repro available · not fixed · needs work
- Full-text search

## Data

Crashes are stored in `crashes.json` (excluded from git — see `.gitignore`).
Copy `crashes.sample.json` → `crashes.json` to start from the example, or use the Import button.

## API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/crashes` | List all crashes |
| POST | `/api/crashes` | Add a crash |
| PUT | `/api/crashes/<id>` | Update a crash |
| DELETE | `/api/crashes/<id>` | Delete a crash |
| POST | `/api/import` | Import from syzkaller workdir (`{"workdir": "/path/to/workdir"}`) |
