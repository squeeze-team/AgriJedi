"""Quick test for /agent/crop-report endpoint."""
import requests, sys

BASE = "http://localhost:8000"
ok = 0
fail = 0

# Test all 3 crops + aliases
for crop, expected in [
    ("wheat", "wheat"), ("corn", "corn"), ("grape", "grape"),
    ("maize", "corn"), ("blé", "wheat"), ("vin", "grape"),
]:
    r = requests.post(f"{BASE}/agent/crop-report", json={"crop": crop})
    if r.status_code == 200:
        d = r.json()
        assert d["crop"] == expected, f"Expected {expected}, got {d['crop']}"
        assert len(d["report"]) > 1000, f"Report too short: {len(d['report'])}"
        print(f"  ✅ crop={crop!r:10s} → {expected}, {len(d['report']):,} chars")
        ok += 1
    else:
        print(f"  ❌ crop={crop!r:10s} → HTTP {r.status_code}")
        fail += 1

# Test error case
r = requests.post(f"{BASE}/agent/crop-report", json={"crop": "banana"})
if r.status_code == 400:
    print(f"  ✅ crop='banana' → 400 (expected)")
    ok += 1
else:
    print(f"  ❌ crop='banana' → HTTP {r.status_code} (expected 400)")
    fail += 1

print(f"\n{'='*40}")
print(f"Results: {ok} passed, {fail} failed")
sys.exit(0 if fail == 0 else 1)
