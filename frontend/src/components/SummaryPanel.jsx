export default function SummaryPanel({ summary, filename }) {
  return (
    <div className="bg-slate-800 rounded-2xl p-6 border border-slate-700">
      <div className="flex items-center gap-2 mb-4">
        <span className="text-2xl">📋</span>
        <h2 className="text-white font-semibold text-lg">Summary</h2>
      </div>
      <p className="text-slate-300 text-sm leading-relaxed">{summary}</p>
      <div className="mt-4 pt-4 border-t border-slate-700">
        <p className="text-slate-500 text-xs">📎 {filename}</p>
      </div>
    </div>
  );
}
