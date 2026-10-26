import { seal, unseal } from "./crypto";
import { pool } from "./db";
import { mintKey } from "./lore";

export type LoreAccount = { login: string; installation_id: string };

export async function accountsFor(userId: string): Promise<LoreAccount[]> {
  const { rows } = await pool.query<LoreAccount>(
    `select a.login, a.installation_id from web_user_accounts u
       join web_lore_accounts a using (login) where u.user_id = $1 order by a.login`,
    [userId],
  );
  return rows;
}

/** The join is the authorization check: a user only gets keys for accounts they linked. */
export async function keyFor(userId: string, login: string): Promise<string | null> {
  const { rows } = await pool.query<{ lore_key_enc: string }>(
    `select a.lore_key_enc from web_user_accounts u
       join web_lore_accounts a using (login) where u.user_id = $1 and a.login = $2`,
    [userId, login],
  );
  return rows[0] ? unseal(rows[0].lore_key_enc) : null;
}

/** Call only with an installation GitHub confirmed this user can reach. */
export async function link(userId: string, login: string, installationId: number): Promise<void> {
  const known = await pool.query("select 1 from web_lore_accounts where login = $1", [login]);
  if (known.rowCount) {
    // A reinstall gets a new installation id; the key and Canon stay.
    await pool.query("update web_lore_accounts set installation_id = $2 where login = $1", [login, installationId]);
  } else {
    await pool.query(
      `insert into web_lore_accounts (login, installation_id, lore_key_enc) values ($1, $2, $3)
       on conflict (login) do nothing`,
      [login, installationId, seal(await mintKey(login))],
    );
  }
  await pool.query(
    "insert into web_user_accounts (user_id, login) values ($1, $2) on conflict do nothing",
    [userId, login],
  );
}
