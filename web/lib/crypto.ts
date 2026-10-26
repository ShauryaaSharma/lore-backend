import { createCipheriv, createDecipheriv, createHash, randomBytes } from "node:crypto";

// shortcut: the key derives from AUTH_SECRET, so rotating it orphans stored Lore keys (users re-link); move to AWS KMS if rotation matters.
const keyFrom = (secret: string) => {
  if (!secret) throw new Error("AUTH_SECRET is not set");
  return createHash("sha256").update(secret).digest();
};

/** AES-256-GCM; output is base64(iv | tag | ciphertext). */
export function seal(plain: string, secret = process.env.AUTH_SECRET ?? ""): string {
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", keyFrom(secret), iv);
  const body = Buffer.concat([cipher.update(plain, "utf8"), cipher.final()]);
  return Buffer.concat([iv, cipher.getAuthTag(), body]).toString("base64");
}

export function unseal(sealed: string, secret = process.env.AUTH_SECRET ?? ""): string {
  const buf = Buffer.from(sealed, "base64");
  const decipher = createDecipheriv("aes-256-gcm", keyFrom(secret), buf.subarray(0, 12));
  decipher.setAuthTag(buf.subarray(12, 28));
  return Buffer.concat([decipher.update(buf.subarray(28)), decipher.final()]).toString("utf8");
}
