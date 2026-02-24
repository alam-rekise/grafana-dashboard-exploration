const { InfluxDB, Point } = require("@influxdata/influxdb-client");
const fs = require("fs");
const path = require("path");

// ====================================================================
// Load data type definitions
// ====================================================================
const dataTypesPath = path.join(__dirname, "data-types.json");
const dataTypes = JSON.parse(fs.readFileSync(dataTypesPath, "utf-8"));
const availableTypes = Object.keys(dataTypes);

// ====================================================================
// Parse CLI arguments: --mission <name> --type <type> --csv <path>
// ====================================================================
const args = process.argv.slice(2);
const missionIdx = args.indexOf("--mission");
const typeIdx = args.indexOf("--type");
const csvIdx = args.indexOf("--csv");

if (missionIdx === -1 || !args[missionIdx + 1] || typeIdx === -1 || !args[typeIdx + 1]) {
  console.error("Usage: node write.js --mission <mission-name> --type <data-type> [--csv <path>]");
  console.error("");
  console.error("Available data types:", availableTypes.join(", "));
  console.error("");
  console.error("Examples:");
  console.error("  node write.js --mission mission-001 --type mission-segments");
  console.error("  node write.js --mission mission-001 --type navigation --csv /path/to/nav.csv");
  process.exit(1);
}

const missionName = args[missionIdx + 1];
const typeName = args[typeIdx + 1];
const csvPath = csvIdx !== -1 && args[csvIdx + 1] ? args[csvIdx + 1] : null;

// ====================================================================
// Validate data type
// ====================================================================
const typeConfig = dataTypes[typeName];
if (!typeConfig) {
  console.error(`Unknown data type: "${typeName}"`);
  console.error("Available types:", availableTypes.join(", "));
  process.exit(1);
}

if (!csvPath) {
  console.error("Please provide a CSV file path with --csv <path>");
  console.error(`Example: node write.js --mission ${missionName} --type ${typeName} --csv /path/to/data.csv`);
  process.exit(1);
}

console.log("Mission:", missionName);
console.log("Type:", typeName);
console.log("Measurement:", typeConfig.measurement);
console.log("CSV:", csvPath);

// ====================================================================
// InfluxDB connection
// ====================================================================
const token =
  "XZvi_7cfAtdoSsmdG_-1enydzbGSlTYSqmEgB2XAuwxRqpzXbeP_ThABKMyLPfCmOr1rueEXQde_wthNJwz1tw==";
const org = "Rekise Marine";
const bucket = "vessel-data";

const client = new InfluxDB({ url: "http://localhost:8086", token });
const writeApi = client.getWriteApi(org, bucket, "ms");

writeApi.useDefaultTags({ vessel: "AUV_01" });

// ====================================================================
// STEP 1: Read the CSV file
// ====================================================================
const rawData = fs.readFileSync(csvPath, "utf-8");
console.log("\n=== STEP 1: Read file ===");
console.log("File length:", rawData.length, "characters");

// ====================================================================
// STEP 2: Split into rows and parse header
// ====================================================================
const rows = rawData.split("\n");
const header = rows[0].split(",").map((col) => col.trim());

console.log("\n=== STEP 2: Parse header ===");
console.log("Columns found:", header);

// Build column name → index map
const colIndex = {};
header.forEach((name, idx) => {
  colIndex[name] = idx;
});

// Validate timestamp column (null means use current time for summary data)
const timestampCol = typeConfig.timestamp_column;
const useCurrentTime = timestampCol === null;

if (!useCurrentTime && colIndex[timestampCol] === undefined) {
  console.error(`Timestamp column "${timestampCol}" not found in CSV header.`);
  console.error("Available columns:", header.join(", "));
  process.exit(1);
}

if (useCurrentTime) {
  console.log("Timestamp: using current time (summary data, no timestamp column)");
}

for (const [fieldName, fieldDef] of Object.entries(typeConfig.fields)) {
  if (colIndex[fieldDef.column] === undefined) {
    console.error(`Field column "${fieldDef.column}" (for field "${fieldName}") not found in CSV header.`);
    console.error("Available columns:", header.join(", "));
    process.exit(1);
  }
}

for (const [tagName, tagColumn] of Object.entries(typeConfig.tags)) {
  if (colIndex[tagColumn] === undefined) {
    console.error(`Tag column "${tagColumn}" (for tag "${tagName}") not found in CSV header.`);
    console.error("Available columns:", header.join(", "));
    process.exit(1);
  }
}

// ====================================================================
// STEP 3: Parse each row and create InfluxDB points
// ====================================================================
console.log("\n=== STEP 3: Parse rows ===");

const points = [];

for (let i = 1; i < rows.length; i++) {
  const row = rows[i].trim();
  if (!row) continue;

  const columns = row.split(",");

  // Get timestamp
  let timestampMs;
  let timestampStr;

  if (useCurrentTime) {
    timestampMs = Date.now();
    timestampStr = "(current time)";
  } else {
    timestampStr = columns[colIndex[timestampCol]];
    timestampMs = new Date(timestampStr).getTime();

    if (isNaN(timestampMs)) {
      if (i <= 3) console.log(`  Skipping row ${i}: invalid timestamp "${timestampStr}"`);
      continue;
    }
  }

  // Create point with measurement name from config
  const point = new Point(typeConfig.measurement)
    .tag("mission", missionName)
    .timestamp(timestampMs);

  // Add configured tags
  for (const [tagName, tagColumn] of Object.entries(typeConfig.tags)) {
    const value = columns[colIndex[tagColumn]];
    if (value) point.tag(tagName, value.trim());
  }

  // Add configured fields with correct types
  for (const [fieldName, fieldDef] of Object.entries(typeConfig.fields)) {
    const rawValue = columns[colIndex[fieldDef.column]];

    if (fieldDef.type === "int") {
      const parsed = parseInt(rawValue);
      if (!isNaN(parsed)) point.intField(fieldName, parsed);
    } else if (fieldDef.type === "float") {
      const parsed = parseFloat(rawValue);
      if (!isNaN(parsed)) point.floatField(fieldName, parsed);
    } else {
      // string field
      if (rawValue) point.stringField(fieldName, rawValue.trim());
    }
  }

  points.push(point);

  // Log first 3 rows
  if (i <= 3) {
    console.log(`\nRow ${i}:`);
    console.log("  Timestamp:", timestampStr, "→", timestampMs, "ms");
    for (const [tagName, tagColumn] of Object.entries(typeConfig.tags)) {
      console.log(`  Tag "${tagName}":`, columns[colIndex[tagColumn]]);
    }
    for (const [fieldName, fieldDef] of Object.entries(typeConfig.fields)) {
      console.log(`  Field "${fieldName}" (${fieldDef.type}):`, columns[colIndex[fieldDef.column]]);
    }
  }
}

console.log("\n=== Total points created:", points.length, "===");

// ====================================================================
// STEP 4: Write all points to InfluxDB
// ====================================================================
console.log("\n=== STEP 4: Writing to InfluxDB ===");
writeApi.writePoints(points);

writeApi
  .close()
  .then(() => {
    console.log("All", points.length, "points written successfully!");
  })
  .catch((e) => {
    console.error("Write failed:", e);
  });
