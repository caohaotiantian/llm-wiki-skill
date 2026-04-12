#!/usr/bin/env node
/**
 * PGlite sidecar HTTP server for llm-wiki.
 *
 * Provides a lightweight Postgres-compatible database via PGlite,
 * exposed over a simple JSON-RPC HTTP interface.
 *
 * Usage:
 *   node server.js --data-dir ./data --port 5488
 */

import { createServer } from "node:http";
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";
import { PGlite } from "@electric-sql/pglite";
import { vector } from "@electric-sql/pglite/vector";

const __dirname = dirname(fileURLToPath(import.meta.url));

const { values: args } = parseArgs({
  options: {
    "data-dir": { type: "string", default: join(__dirname, "data") },
    port: { type: "string", default: "5488" },
  },
});

const dataDir = args["data-dir"];
const port = parseInt(args.port, 10);

console.error(`[pglite-sidecar] Starting with data-dir=${dataDir} port=${port}`);

// Note: pg_trgm is not available in PGlite — fuzzy title matching is disabled
const db = new PGlite(dataDir, {
  extensions: { vector },
});

// Initialize schema on first run
async function initSchema() {
  const schemaPath = join(__dirname, "..", "schema.sql");
  try {
    const schema = readFileSync(schemaPath, "utf-8");
    await db.exec(schema);
    console.error("[pglite-sidecar] Schema initialized successfully");
  } catch (err) {
    if (err.code === "ENOENT") {
      console.error(`[pglite-sidecar] Warning: schema.sql not found at ${schemaPath}`);
    } else {
      console.error(`[pglite-sidecar] Schema init error: ${err.message}`);
    }
  }
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on("data", (chunk) => chunks.push(chunk));
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf-8")));
    req.on("error", reject);
  });
}

async function handleRpc(body) {
  const { method, params = {} } = JSON.parse(body);
  const { sql, args: sqlArgs } = params;

  switch (method) {
    case "ping":
      return { ok: true };

    case "query": {
      if (!sql) throw new Error("Missing 'sql' in params");
      const result = await db.query(sql, sqlArgs || []);
      return { rows: result.rows };
    }

    case "execute": {
      if (!sql) throw new Error("Missing 'sql' in params");
      // PGlite's exec() doesn't support parameterized queries — use query()
      const result = await db.query(sql, sqlArgs || []);
      const affected = result.affectedRows ?? result.rows?.length ?? 0;
      return { affected };
    }

    default:
      throw new Error(`Unknown method: ${method}`);
  }
}

const server = createServer(async (req, res) => {
  // CORS headers for local development
  res.setHeader("Content-Type", "application/json");

  if (req.method !== "POST" || req.url !== "/rpc") {
    res.writeHead(404);
    res.end(JSON.stringify({ error: "Not found. Use POST /rpc" }));
    return;
  }

  try {
    const body = await readBody(req);
    const result = await handleRpc(body);
    res.writeHead(200);
    res.end(JSON.stringify(result));
  } catch (err) {
    console.error(`[pglite-sidecar] RPC error: ${err.message}`);
    res.writeHead(400);
    res.end(JSON.stringify({ error: err.message }));
  }
});

// Graceful shutdown
function shutdown(signal) {
  console.error(`[pglite-sidecar] Received ${signal}, shutting down...`);
  server.close(() => {
    db.close().then(() => {
      console.error("[pglite-sidecar] Closed cleanly");
      process.exit(0);
    });
  });
  // Force exit after 5s
  setTimeout(() => process.exit(1), 5000);
}

process.on("SIGTERM", () => shutdown("SIGTERM"));
process.on("SIGINT", () => shutdown("SIGINT"));

// Start
await initSchema();
server.listen(port, () => {
  console.error(`[pglite-sidecar] Listening on http://localhost:${port}`);
});
