import assert from "node:assert/strict";
import { test } from "node:test";
import { seal, unseal } from "./crypto.ts";

test("seal round-trips and never returns the plaintext", () => {
  const sealed = seal("lk_secret", "s1");
  assert.notEqual(sealed, seal("lk_secret", "s1"), "fresh IV per call");
  assert.ok(!Buffer.from(sealed, "base64").toString().includes("lk_secret"));
  assert.equal(unseal(sealed, "s1"), "lk_secret");
});

test("unseal rejects a wrong secret or tampered ciphertext", () => {
  const sealed = seal("lk_secret", "s1");
  assert.throws(() => unseal(sealed, "s2"));
  const buf = Buffer.from(sealed, "base64");
  buf[buf.length - 1] ^= 1;
  assert.throws(() => unseal(buf.toString("base64"), "s1"));
});

test("an empty secret is refused rather than used", () => {
  assert.throws(() => seal("x", ""), /AUTH_SECRET/);
});
