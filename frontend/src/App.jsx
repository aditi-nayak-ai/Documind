import { useState } from "react";
import UploadZone from "./components/UploadZone";
import SummaryPanel from "./components/SummaryPanel";
import FactsPanel from "./components/FactsPanel";
import ChatWindow from "./components/ChatWindow";

export default function App() {
  const [docData, setDocData] = useState(null);

  if (!docData) {
    return <UploadZone onUploadSuccess={setDocData} />;
  }

  return (
    <div className="min-h-screen bg-slate-900 p-6">
      <div className="max-w-6xl mx-auto">
        <div className="flex items-center justify-between mb-8">
          <h1 className="text-2xl font-bold text-white">
            Docu<span className="text-brand-500">Mind</span>
          </h1>
          <button
            onClick={() => setDocData(null)}
            className="text-slate-400 hover:text-white text-sm border border-slate-600 hover:border-slate-400 px-4 py-2 rounded-lg transition-colors"
          >
            ↑ Upload New Document
          </button>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-1 space-y-6">
            <SummaryPanel summary={docData.summary} filename={docData.filename} />
            <FactsPanel facts={docData.facts} />
          </div>
          <div className="lg:col-span-2">
            <ChatWindow filename={docData.filename} />
          </div>
        </div>
      </div>
    </div>
  );
}
