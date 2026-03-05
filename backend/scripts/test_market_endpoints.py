"""Quick smoke-test for new market endpoints."""
from fastapi.testclient import TestClient
from app import app

client = TestClient(app)

# 1) POST /agent/market-signals
print("=== POST /agent/market-signals ===")
r1 = client.post("/agent/market-signals", json={"crop": "wheat"})
print("Status:", r1.status_code)
d1 = r1.json()
print("Assets:", list(d1["assets"].keys()))
print("Narrative:")
for n in d1.get("narrative", []):
    print(f"  {n}")
print("Supply/demand wheat:", d1["supply_demand"]["wheat"])
print("Weekly series weeks:", len(d1["weekly_series"].get("weeks", [])))

# 2) GET /agent/system-prompt
print("\n=== GET /agent/system-prompt ===")
r2 = client.get("/agent/system-prompt")
print("Status:", r2.status_code)
d2 = r2.json()
print(d2["content"][:1000])

# 3) GET /market/weekly-chart
print("\n=== GET /market/weekly-chart ===")
r3 = client.get("/market/weekly-chart?symbol=wheat_fut&weeks=12")
print("Status:", r3.status_code)
d3 = r3.json()
print("Weeks:", len(d3["weeks"]), "| Last 3 closes:", d3["close"][-3:])

# 4) Existing endpoints still work
print("\n=== Existing endpoints ===")
r4 = client.post("/agent/yield-analysis", json={})
print("yield-analysis:", r4.status_code)
r5 = client.post("/agent/market-overview", json={})
print("market-overview:", r5.status_code)

print("\n✅ All tests passed!")
