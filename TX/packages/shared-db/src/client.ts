import pg from "pg";

const { Pool } = pg;

let pool: pg.Pool | null = null;

/** Single shared pool for the process. Connection string from DATABASE_URL (see .env.example). */
export function getPool(): pg.Pool {
  if (!pool) {
    const connectionString = process.env.DATABASE_URL;
    if (!connectionString) {
      throw new Error("DATABASE_URL is not set — copy .env.example to .env and fill it in");
    }
    pool = new Pool({ connectionString });
  }
  return pool;
}

export async function query<T extends pg.QueryResultRow = pg.QueryResultRow>(
  text: string,
  params?: unknown[],
): Promise<pg.QueryResult<T>> {
  return getPool().query<T>(text, params);
}

export async function closePool(): Promise<void> {
  if (pool) {
    await pool.end();
    pool = null;
  }
}
