"""Smoke-test: verify all endpoints are POST and return 200."""
from fastapi.testclient import TestClient
from app import app

c = TestClient(app)

tests = [
    ("POST", "/crops", {}),
    ("POST", "/weather/france", {}),
    ("POST", "/predict/yield", {}),
    ("POST", "/predict/price", {}),
    ("POST", "/prices/history", {}),
    ("POST", "/yield/history", {}),
    ("POST", "/ndvi/stats", {}),
    ("POST", "/analysis/crop-ndvi", {}),
    ("POST", "/agent/yield-analysis", {}),
    ("POST", "/agent/market-overview", {}),
    ("POST", "/agent/market-signals", {}),
    ("POST", "/agent/system-prompt", {}),
    ("POST", "/market/weekly-chart", {}),
]

ok = 0
for method, path, body in tests:
    r = c.post(path, json=body)
    status = "OK" if r.status_code == 200 else f"FAIL({r.status_code})"
    print(f"  {status}  POST {path}")
    if r.status_code == 200:
        ok += 1

# Verify GET on a former-GET endpoint returns 405
r405 = c.get("/crops")
print(f"\n  GET /crops -> {r405.status_code} (expect 405)")

print(f"\n{ok}/{len(tests)} passed")
