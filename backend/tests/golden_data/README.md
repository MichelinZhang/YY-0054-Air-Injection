# Golden Test Data

Place real camera images (`.png` / `.jpg`) in this directory for regression testing.

Each image should have a corresponding `.json` sidecar with expected measurement results:

```
sample_001.png
sample_001.json   ← expected output
```

## JSON sidecar format

```json
{
  "top_point": {"x": 320, "y": 100},
  "bottom_point": {"x": 320, "y": 400},
  "expected_tick_delta": 6.0,
  "expected_pixel_delta": 300.0,
  "tolerance_tick": 1.0,
  "tolerance_pixel": 20.0,
  "min_confidence": 0.3,
  "roi": {"x": 200, "y": 50, "width": 240, "height": 500},
  "description": "Standard 6-tick air column at normal lighting"
}
```
