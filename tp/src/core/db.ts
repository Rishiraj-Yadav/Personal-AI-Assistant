import Database from "better-sqlite3";
import path from "path";
import process from "process";

const dbPath = path.resolve(process.cwd(), "data", "taskmaster.db");
const db = new Database(dbPath, { verbose: process.env.TP_VERBOSE ? console.log : undefined });

// Optimize for serverless environments to prevent "database is locked" write races
db.pragma("journal_mode = WAL");
db.pragma("synchronous = NORMAL");

// ─── Schema Setup ────────────────────────────────────────────────────────────

db.exec(`
  CREATE TABLE IF NOT EXISTS State (
    key TEXT PRIMARY KEY,
    value TEXT
  );

  CREATE TABLE IF NOT EXISTS Steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT,
    step_num INTEGER,
    description TEXT,
    status TEXT DEFAULT 'PENDING'
  );

  CREATE TABLE IF NOT EXISTS History (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp INTEGER,
    agent TEXT,
    action TEXT,
    details TEXT
  );
`);

// ─── Database Abstractions ───────────────────────────────────────────────────

export const DB = {
    setState(key: string, value: any) {
        const stmt = db.prepare(`
      INSERT INTO State (key, value) 
      VALUES (?, ?) 
      ON CONFLICT(key) DO UPDATE SET value = excluded.value
    `);
        stmt.run(key, JSON.stringify(value));
    },

    getState(key: string): any {
        const stmt = db.prepare("SELECT value FROM State WHERE key = ?");
        const row = stmt.get(key) as { value: string } | undefined;
        if (!row) return null;
        try {
            return JSON.parse(row.value);
        } catch {
            return null;
        }
    },

    logHistory(agent: string, action: string, details: any) {
        const stmt = db.prepare("INSERT INTO History (timestamp, agent, action, details) VALUES (?, ?, ?, ?)");
        stmt.run(Date.now(), agent, action, JSON.stringify(details));
    },

    recordSteps(taskId: string, steps: string[]) {
        const insert = db.prepare("INSERT INTO Steps (task_id, step_num, description) VALUES (?, ?, ?)");
        const clear = db.prepare("DELETE FROM Steps WHERE task_id = ?");

        // Use an atomic transaction
        const insertMany = db.transaction(() => {
            clear.run(taskId);
            steps.forEach((desc, idx) => insert.run(taskId, idx + 1, desc));
        });

        insertMany();
    },

    updateStepStatus(taskId: string, stepNum: number, status: 'PENDING' | 'SUCCESS' | 'FAILED') {
        const stmt = db.prepare("UPDATE Steps SET status = ? WHERE task_id = ? AND step_num = ?");
        stmt.run(status, taskId, stepNum);
    }
};
