// Small pure helpers so the panels can never crash on an unexpected API
// shape. The backend already guarantees `facts` is a list of strings; this
// is the second line of defence, and it is trivial to unit test.
 
export function toFactList(facts) {
  if (!Array.isArray(facts)) return [];
  return facts
    .filter((fact) => typeof fact === "string" && fact.trim() !== "")
    .map((fact) => fact.trim());
}
 
// What the "Indexed ..." line under the file name should say. `partial`
// means only part of the document was embedded, so chat answers can miss
// content -- the user must be told, not shown a green "success".
export function indexStatus({ partial = false, reused = false } = {}) {
  if (partial) return { tone: "warn", label: "Partially indexed" };
  if (reused) return { tone: "ok", label: "Already indexed — reused" };
  return { tone: "ok", label: "Indexed successfully" };
}
 
