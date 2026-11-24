"use client";

import { cn } from "@/lib/utils";
import { useState } from "react";
import { Upload, Code, FileCode } from "lucide-react";

interface Props {
  onSubmit: (sourceCode: string, filename: string, language: string) => void;
  isLoading: boolean;
}

type InputMode = "snippet" | "file";

const LANGUAGE_OPTS = [
  { value: "python", label: "Python", ext: ".py" },
  { value: "javascript", label: "JavaScript", ext: ".js" },
  { value: "typescript", label: "TypeScript", ext: ".ts" },
];

const EXAMPLE_CODE = `import sqlite3

def get_user(user_id: str) -> dict:
    conn = sqlite3.connect("app.db")
    cursor = conn.cursor()
    # Vulnerable: direct string concatenation
    query = "SELECT * FROM users WHERE id = " + user_id
    cursor.execute(query)
    return cursor.fetchone()

SECRET_KEY = "my-hardcoded-secret-123"
`;

export function CodeUpload({ onSubmit, isLoading }: Props) {
  const [mode, setMode] = useState<InputMode>("snippet");
  const [code, setCode] = useState("");
  const [language, setLanguage] = useState("python");
  const [filename, setFilename] = useState("snippet.py");
  const [dragging, setDragging] = useState(false);

  const selectedLang = LANGUAGE_OPTS.find((l) => l.value === language);

  function handleLanguageChange(lang: string) {
    setLanguage(lang);
    const ext = LANGUAGE_OPTS.find((l) => l.value === lang)?.ext ?? ".py";
    setFilename((f) => f.replace(/\.[^.]+$/, ext));
  }

  function handleFileRead(file: File) {
    const lang =
      file.name.endsWith(".ts") || file.name.endsWith(".tsx")
        ? "typescript"
        : file.name.endsWith(".js") || file.name.endsWith(".jsx")
          ? "javascript"
          : "python";

    setLanguage(lang);
    setFilename(file.name);

    const reader = new FileReader();
    reader.onload = (e) => setCode(e.target?.result as string ?? "");
    reader.readAsText(file);
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) {
      setMode("snippet"); // show code after drop
      handleFileRead(file);
    }
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!code.trim()) return;
    onSubmit(code, filename, language);
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {/* Mode toggle */}
      <div className="flex gap-1 p-1 bg-surface-overlay rounded-lg w-fit">
        {(["snippet", "file"] as InputMode[]).map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => setMode(m)}
            className={cn(
              "px-3 py-1.5 rounded-md text-xs font-medium transition-all",
              mode === m
                ? "bg-brand text-white"
                : "text-gray-500 hover:text-gray-300",
            )}
          >
            {m === "snippet" ? (
              <span className="flex items-center gap-1.5"><Code className="w-3.5 h-3.5" />Snippet</span>
            ) : (
              <span className="flex items-center gap-1.5"><Upload className="w-3.5 h-3.5" />File</span>
            )}
          </button>
        ))}
      </div>

      {/* Language + filename row */}
      <div className="flex gap-3">
        <div className="flex-1">
          <label className="block text-xs text-gray-500 mb-1">Language</label>
          <select
            value={language}
            onChange={(e) => handleLanguageChange(e.target.value)}
            className="w-full bg-surface-raised border border-surface-border rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-brand"
          >
            {LANGUAGE_OPTS.map((l) => (
              <option key={l.value} value={l.value}>{l.label}</option>
            ))}
          </select>
        </div>
        <div className="flex-1">
          <label className="block text-xs text-gray-500 mb-1">Filename</label>
          <input
            type="text"
            value={filename}
            onChange={(e) => setFilename(e.target.value)}
            className="w-full bg-surface-raised border border-surface-border rounded-lg px-3 py-2 text-sm text-gray-200 font-mono focus:outline-none focus:border-brand"
          />
        </div>
      </div>

      {mode === "snippet" ? (
        <div className="space-y-2">
          <div className="flex justify-between items-center">
            <label className="text-xs text-gray-500">Source Code</label>
            <button
              type="button"
              onClick={() => setCode(EXAMPLE_CODE)}
              className="text-xs text-brand hover:text-brand-dim transition-colors"
            >
              Load example (SQL injection)
            </button>
          </div>
          <textarea
            value={code}
            onChange={(e) => setCode(e.target.value)}
            rows={14}
            placeholder="Paste your code here..."
            className="w-full bg-surface-raised border border-surface-border rounded-lg px-4 py-3 text-sm font-mono text-gray-200 focus:outline-none focus:border-brand resize-none placeholder:text-gray-700"
          />
        </div>
      ) : (
        <div
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={handleDrop}
          className={cn(
            "border-2 border-dashed rounded-xl p-10 text-center transition-colors cursor-pointer",
            dragging ? "border-brand bg-brand-glow" : "border-surface-border hover:border-gray-600",
          )}
          onClick={() => document.getElementById("file-input")?.click()}
        >
          <FileCode className="w-8 h-8 text-gray-600 mx-auto mb-3" />
          <p className="text-sm text-gray-400">Drop a file or click to browse</p>
          <p className="text-xs text-gray-600 mt-1">.py .js .ts .jsx .tsx</p>
          <input
            id="file-input"
            type="file"
            accept=".py,.js,.ts,.jsx,.tsx"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) {
                setMode("snippet");
                handleFileRead(file);
              }
            }}
          />
          {code && (
            <p className="mt-3 text-xs text-green-400">
              ✓ {filename} loaded ({code.split("\n").length} lines)
            </p>
          )}
        </div>
      )}

      <button
        type="submit"
        disabled={isLoading || !code.trim()}
        className={cn(
          "w-full py-3 rounded-xl text-sm font-semibold transition-all duration-200",
          isLoading || !code.trim()
            ? "bg-surface-border text-gray-600 cursor-not-allowed"
            : "bg-brand hover:bg-brand-dim text-white shadow-lg shadow-brand/20 hover:shadow-brand/30",
        )}
      >
        {isLoading ? (
          <span className="flex items-center justify-center gap-2">
            <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
            Auditing…
          </span>
        ) : (
          "Start Security Audit"
        )}
      </button>
    </form>
  );
}
