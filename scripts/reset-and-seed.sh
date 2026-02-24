#!/bin/bash

# ====================================================================
# Reset InfluxDB and re-seed all data
#
# This script:
# 1. Deletes all data from InfluxDB (keeps the bucket/org/token intact)
# 2. Re-feeds all mission data from CSV files
#
# Usage: bash scripts/reset-and-seed.sh <mission-name>
# Example: bash scripts/reset-and-seed.sh mission-001
# ====================================================================

MISSION=$1
TOKEN="XZvi_7cfAtdoSsmdG_-1enydzbGSlTYSqmEgB2XAuwxRqpzXbeP_ThABKMyLPfCmOr1rueEXQde_wthNJwz1tw=="
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

if [ -z "$MISSION" ]; then
  echo "Usage: bash scripts/reset-and-seed.sh <mission-name>"
  echo "Example: bash scripts/reset-and-seed.sh mission-001"
  exit 1
fi

echo "=== Step 1: Delete all data from InfluxDB ==="
curl -s -X POST "http://localhost:8086/api/v2/delete?org=Rekise%20Marine&bucket=vessel-data" \
  -H "Authorization: Token $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"start":"2020-01-01T00:00:00Z","stop":"2030-01-01T00:00:00Z"}'
echo ""
echo "Data deleted."

echo ""
echo "=== Step 2: Feed mission segments ==="
node "$SCRIPT_DIR/write.js" --mission "$MISSION" --type mission-segments \
  --csv "$SCRIPT_DIR/pm-data/mission_time_report.xlsx - Mode Segments.csv"

echo ""
echo "=== Step 3: Feed power consumption ==="
node "$SCRIPT_DIR/write.js" --mission "$MISSION" --type power-consumption \
  --csv "$SCRIPT_DIR/pm-data/mission_time_report.xlsx - Power Consumption.csv"

echo ""
echo "=== Done! ==="
echo "Open Grafana at http://localhost:3000"
echo "Select mission: $MISSION from the dropdown"
echo "Set time range to 'Last 7d' to see all data"
