import { describe, expect, it } from "vitest";
import { indexStatus, toFactList } from "./docStatus";
 
describe("toFactList", () => {
  it("keeps clean strings and trims them", () => {
    expect(toFactList([" a ", "b"])).toEqual(["a", "b"]);
  });
  it("returns an empty list for anything that is not an array", () => {
    for (const bad of [null, undefined, {}, { a: "x" }, "text", 42]) {
      expect(toFactList(bad)).toEqual([]);
    }
  });
  it("drops blanks and non-strings instead of crashing", () => {
    expect(toFactList(["ok", "", "  ", 3, null, { x: 1 }])).toEqual(["ok"]);
  });
});
 
describe("indexStatus", () => {
  it("warns when only part of the document was indexed", () => {
    expect(indexStatus({ partial: true })).toEqual({ tone: "warn", label: "Partially indexed" });
  });
  it("says reused for a repeat upload", () => {
    expect(indexStatus({ reused: true }).label).toBe("Already indexed — reused");
  });
  it("defaults to success", () => {
    expect(indexStatus().label).toBe("Indexed successfully");
  });
  it("partial wins over reused", () => {
    expect(indexStatus({ partial: true, reused: true }).tone).toBe("warn");
  });
});
