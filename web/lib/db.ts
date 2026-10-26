import { Pool } from "pg";

// Reuse one pool across dev hot reloads, which would otherwise leak connections.
const g = globalThis as { lorePool?: Pool };
export const pool = (g.lorePool ??= new Pool({ connectionString: process.env.DATABASE_URL, max: 5 }));
