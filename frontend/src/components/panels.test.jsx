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
});

describe("FactsPanel", () => {
  it("lists a single genuine fact that contains the word quota", () => {
    const html = render(<FactsPanel facts={["The Q3 quota was 1.2M"]} />);
    expect(html).toContain("The Q3 quota was 1.2M");
    expect(html).not.toContain("Unavailable");
  });

  it("does not crash when facts is an object instead of an array", () => {
    // Previously: facts.map is not a function -> blank page.
    expect(() => render(<FactsPanel facts={{ a: "x" }} />)).not.toThrow();
    expect(render(<FactsPanel facts={{ a: "x" }} />)).toContain("No key facts");
  });

  it("does not crash on non-string items or undefined", () => {
    expect(() => render(<FactsPanel facts={[1, null, "ok"]} />)).not.toThrow();
    expect(() => render(<FactsPanel />)).not.toThrow();
  });

  it("shows the failure message when the backend flags it", () => {
    const html = render(<FactsPanel facts={["Key facts unavailable — Gemini quota limit reached."]} failed />);
    expect(html).toContain("Key facts unavailable");
  });
});

describe("ErrorBoundary", () => {
  it("switches to the fallback state when a child throws", () => {
    expect(ErrorBoundary.getDerivedStateFromError(new Error("boom"))).toEqual({ failed: true });
  });
  it("renders children normally when nothing failed", () => {
    expect(render(<ErrorBoundary><p>fine</p></ErrorBoundary>)).toContain("fine");
  });
});
