export default function FactsPanel({ facts }) {
  return (
    <div className="bg-slate-800 rounded-2xl p-6 border border-slate-700">
      <div className="flex items-center gap-2 mb-4">
        <span className="text-2xl">🔍</span>
        <h2 className="text-white font-semibold text-lg">Key Facts</h2>
      </div>
      <ul className="space-y-2">
        {facts.map((fact, i) => (
          <li key={i} className="flex items-start gap-2">
            <span className="text-brand-500 mt-1 text-xs">▸</span>
            <span className="text-slate-300 text-sm leading-relaxed">{fact}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
