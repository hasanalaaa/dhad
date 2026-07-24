import assert from "node:assert/strict";
import test from "node:test";
import { GOLD_CAPABILITIES, assertCapabilityParity } from "./capabilities.js";

test("Gold capability contract covers every product surface", () => {
  assert.equal(assertCapabilityParity(GOLD_CAPABILITIES), true);
  assert.deepEqual(GOLD_CAPABILITIES.documents.formats, ["txt", "md", "docx", "pdf"]);
  assert.throws(() => assertCapabilityParity({ check: true }), /missing Gold capabilities/u);
});
