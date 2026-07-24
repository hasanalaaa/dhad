import assert from "node:assert/strict";
import test from "node:test";
import { ThemeController, applyTheme, resolveTheme } from "./theme-controller.js";

function root() { return { dataset: {}, attributes: {}, style: { values: {}, setProperty(k,v){this.values[k]=v;} }, setAttribute(k,v){this.attributes[k]=v;} }; }

test("theme resolution supports system, light, dark and AAA contrast mode", () => {
  assert.equal(resolveTheme("system", true), "dark");
  assert.equal(resolveTheme("system", false), "light");
  const target = root();
  assert.equal(applyTheme(target, "contrast"), "contrast");
  assert.equal(target.dataset.theme, "contrast");
});

test("theme controller persists explicit preference", async () => {
  const writes = [];
  const controller = new ThemeController({ root: root(), matchMedia: () => ({ matches: false, addEventListener(){}, removeEventListener(){} }), storage: { async getSetting(){ return "dark"; }, setSetting(...args){ writes.push(args); } } });
  assert.equal(await controller.initialize(), "dark");
  controller.setPreference("light");
  assert.deepEqual(writes, [["theme", "light"]]);
});
