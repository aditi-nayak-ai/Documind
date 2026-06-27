import { useState, useRef } from "react";
import axios from "axios";

const BACKEND = import.meta.env.VITE_BACKEND_URL || "http://localhost:8000";

export default function UploadZone({ onUploadSuccess }) {
  const [dragging, setDragging] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const inputRef = useRef();

  const handleFile = async (file) => {
    if (!file || !file.name.endsWith(".pdf")) {
      setError("Only PDF files are accepted.");
      return;
    }
    setError("");
    setLoading(true);
    const formData = new FormData();
    formData.append("file", file);
    try {
      const res = await axios.post(`${BACKEND}/ingest`, formData);
      onUploadSuccess(res.data);
    } catch (e) {
      setError("Upload failed. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-col items-center justify-center min-h-screen px-4">
      <div className="mb-8 text-center">
        <h1 className="text-5xl font-bold text-white mb-3">
          Docu<span className="text-brand-500">Mind</span>
        </h1>
        <p className="text-slate-400 text-lg">
          Upload a PDF. Get instant summary, key facts, and chat with your document.
        </p>
      </div>

      <div
        className={`w-full max-w-xl border-2 border-dashed rounded-2xl p-12 text-center cursor-pointer transition-all duration-200 ${
          dragging
            ? "border-brand-500 bg-brand-500/10"
            : "border-slate-600 hover:border-brand-500 hover:bg-slate-800/50"
        }`}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); handleFile(e.dataTransfer.files[0]); }}
        onClick={() => inputRef.current.click()}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".pdf"
          className="hidden"
          onChange={(e) => handleFile(e.target.files[0])}
        />
        {loading ? (
          <div className="flex flex-col items-center gap-3">
            <div className="w-10 h-10 border-4 border-brand-500 border-t-transparent rounded-full animate-spin" />
            <p className="text-slate-400">Processing your document...</p>
          </div>
        ) : (
          <>
            <div className="text-5xl mb-4">📄</div>
            <p className="text-white font-medium text-lg">Drop your PDF here</p>
            <p className="text-slate-400 mt-2 text-sm">or click to browse</p>
          </>
        )}
      </div>

      {error && (
        <p className="mt-4 text-red-400 text-sm">{error}</p>
      )}
    </div>
  );
}
