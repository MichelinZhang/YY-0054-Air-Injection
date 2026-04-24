# Air Column Assistant Backend

FastAPI backend for Hikvision MV camera preview, calibration, semi-automatic measurement, and result saving.

## Run

```powershell
uv sync
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Tests

```powershell
uv run pytest -q
```

