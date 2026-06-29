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
    <div className="min-h-screen bg-surface-900 p-6">
      {/* Ambient background glow */}
      <div className="fixed inset-0 pointer-events-none overflow-hidden">
        <div className="absolute top-[-10%] left-1/2 -translate-x-1/2 w-[800px] h-[400px] rounded-full bg-brand-500/8 blur-[100px]" />
      </div>

      <div className="relative z-10 max-w-6xl mx-auto">
        {/* Topbar */}
        <div className="flex items-center justify-between mb-8">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-xl bg-brand-500 flex items-center justify-center shadow-lg shadow-brand-500/30">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                <polyline points="14 2 14 8 20 8"/>
                <line x1="16" y1="13" x2="8" y2="13"/>
                <line x1="16" y1="17" x2="8" y2="17"/>
              </svg>
            </div>
            <h1 className="text-xl font-bold tracking-tight text-white">
              Docu<span className="text-brand-400">Mind</span>
            </h1>
          </div>

          <button
            onClick={() => setDocData(null)}
            className="flex items-center gap-2 text-slate-400 hover:text-white text-sm border border-white/8 hover:border-white/20 bg-white/3 hover:bg-white/6 px-4 py-2 rounded-xl transition-all duration-200"
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
              <polyline points="17 8 12 3 7 8"/>
              <line x1="12" y1="3" x2="12" y2="15"/>
            </svg>
            New document
          </button>
        </div>

        {/* Main layout */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
          <div className="lg:col-span-1 space-y-5">
            <SummaryPanel summary={docData.summary} filename={docData.filename} />
            <FactsPanel facts={docData.facts} />
          </div>
          <div className="lg:col-span-2">
            <ChatWindow docId={docData.doc_id} />
          </div>
        </div>
      </div>
    </div>
  );
}
