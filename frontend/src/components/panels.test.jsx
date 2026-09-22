import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import ErrorBoundary from "./ErrorBoundary";
import FactsPanel from "./FactsPanel";
import SummaryPanel from "./SummaryPanel";
 
const render = (element) => renderToStaticMarkup(element);
 
describe("SummaryPanel", () => {
  it("shows a genuine summary that merely mentions the word quota", () => {
    // The old code hid this behind a fake "Gemini quota reached" banner.
    const html = render(
      <SummaryPanel summary="The report reviews sales quota attainment in four regions." filename="q3.pdf" />
    );
    expect(html).toContain("sales quota attainment");
    expect(html).toContain("Summary");
    expect(html).not.toContain("chat is ready");
  });
 
  it("shows the server's own message when generation failed", () => {
    const html = render(
      <SummaryPanel
        summary="Summary unavailable — Gemini's servers are temporarily overloaded. Please try again shortly."
        filename="a.pdf"
        summaryFailed
      />
    );
    expect(html).toContain("temporarily overloaded"); // accurate cause, not a hard-coded "quota" claim
    expect(html).toContain("chat is ready");
  });
 
  it("tells the user when a document is only partially indexed", () => {
    const html = render(
      <SummaryPanel summary="Document partially indexed (20/64 chunks)." filename="a.pdf" partial />
    );
    expect(html).toContain("Partially indexed");
    expect(html).not.toContain("Indexed successfully");
    expect(html).toContain("Upload the same file again");
  });
 
  it("labels a reused upload", () => {
    expect(render(<SummaryPanel summary="s" filename="a.pdf" reused />)).toContain("Already indexed");
  });
 
  it("does not throw when summary is missing", () => {
    expect(() => render(<SummaryPanel filename="a.pdf" />)).not.toThrow();
  });
