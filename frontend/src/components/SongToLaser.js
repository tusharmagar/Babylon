import React, { useState, useRef, useCallback } from "react";
import {
  Music, Download, Loader2, CheckCircle2, AlertCircle,
  Youtube, Waves, Brain, Film, FileOutput, Sparkles,
  Clock, Disc3, BarChart3, Palette, Type, Zap,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || "http://localhost:8001";
const API = `${BACKEND_URL}/api`;

const PIPELINE_STAGES = [
  { key: "extracting_audio", label: "Extracting Audio", icon: Youtube, doneKey: "extracting_audio_done" },
  { key: "fetching_lyrics", label: "Fetching Lyrics", icon: Type, doneKey: "fetching_lyrics_done" },
  { key: "analyzing_audio", label: "Analyzing Audio", icon: Waves, doneKey: "analyzing_audio_done" },
  { key: "designing_show", label: "Designing Show", icon: Brain, doneKey: "designing_show_done" },
  { key: "generating_frames", label: "Generating Frames", icon: Film, doneKey: "generating_frames_done" },
  { key: "writing_ilda", label: "Writing ILDA File", icon: FileOutput, doneKey: "writing_ilda_done" },
];

const StageIndicator = ({ stage, currentStage, completedStages, stageData }) => {
  const isActive = currentStage === stage.key;
  const isDone = completedStages.includes(stage.doneKey);
  const isPending = !isActive && !isDone;
  const Icon = stage.icon;
  const data = stageData[stage.doneKey];

  return (
    <div className={`flex items-start gap-3 p-3 rounded-lg transition-all duration-300 ${
      isActive ? "bg-green-500/10 border border-green-500/30" :
      isDone ? "bg-white/5 border border-white/10" :
      "bg-transparent border border-transparent opacity-40"
    }`}>
      <div className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 mt-0.5 ${
        isActive ? "bg-green-500/20 text-green-400" :
        isDone ? "bg-green-600/20 text-green-500" :
        "bg-white/5 text-zinc-600"
      }`}>
        {isActive ? (
          <Loader2 className="w-4 h-4 animate-spin" />
        ) : isDone ? (
          <CheckCircle2 className="w-4 h-4" />
        ) : (
          <Icon className="w-4 h-4" />
        )}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className={`text-sm font-medium ${
            isActive ? "text-green-400" : isDone ? "text-white" : "text-zinc-600"
          }`}>
            {stage.label}
          </span>
          {isActive && (
            <span className="text-xs text-green-500/60 animate-pulse">Processing...</span>
          )}
        </div>
        {isDone && data && (
          <div className="mt-1 text-xs text-zinc-500">
            {stage.key === "extracting_audio" && data.title && (
              <span>{data.title} — {data.artist} ({Math.round(data.duration)}s)</span>
            )}
            {stage.key === "fetching_lyrics" && (
              <span>{data.lyric_count} lines {data.has_synced ? "(synced)" : "(plain)"}</span>
            )}
            {stage.key === "analyzing_audio" && (
              <span>{data.bpm?.toFixed(0)} BPM · {data.beat_count} beats · {data.segments} segments</span>
            )}
            {stage.key === "designing_show" && (
              <span>{data.sections} sections · {data.text_style} style</span>
            )}
            {stage.key === "generating_frames" && (
              <span>{data.total_frames?.toLocaleString()} frames · {data.duration_s?.toFixed(1)}s</span>
            )}
            {stage.key === "writing_ilda" && (
              <span>{data.ilda_filename} ({data.file_size_kb} KB)</span>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

const ResultCard = ({ result }) => {
  const [downloading, setDownloading] = useState(false);
  const meta = result.metadata || {};
  const design = result.design || {};

  const handleDownload = async () => {
    setDownloading(true);
    try {
      const response = await fetch(`${API}/youtube/download/${result.job_id || result.status === 'complete' ? '' : ''}`.replace(/\/$/, ''));
      // Use the proper download URL
      const url = `${API}/youtube/download/${result.job_id}`;
      const a = document.createElement("a");
      a.href = url;
      a.download = result.ilda_filename || "show.ild";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      toast.success("Download started!");
    } catch (e) {
      toast.error("Download failed");
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div className="card-surface p-6 space-y-5">
      {/* Header with thumbnail */}
      <div className="flex items-start gap-4">
        {meta.thumbnail_url && (
          <img
            src={meta.thumbnail_url}
            alt={meta.title}
            className="w-24 h-24 rounded-lg object-cover border border-white/10 flex-shrink-0"
          />
        )}
        <div className="flex-1 min-w-0">
          <h3 className="text-lg font-bold text-white truncate">{meta.title || "Unknown"}</h3>
          <p className="text-sm text-zinc-400">{meta.artist || "Unknown"}</p>
          <div className="flex items-center gap-4 mt-2 text-xs text-zinc-500">
            <span className="flex items-center gap-1"><Clock className="w-3 h-3" /> {Math.round(meta.duration || 0)}s</span>
            <span className="flex items-center gap-1"><Disc3 className="w-3 h-3" /> {result.bpm?.toFixed(0)} BPM</span>
            <span className="flex items-center gap-1"><BarChart3 className="w-3 h-3" /> {result.total_frames?.toLocaleString()} frames</span>
            <span className="flex items-center gap-1"><Type className="w-3 h-3" /> {result.lyric_count} lines</span>
          </div>
        </div>
      </div>

      {/* Show design info */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="bg-white/5 rounded-lg p-3 border border-white/5">
          <div className="text-xs text-zinc-500 mb-1">Text Style</div>
          <div className="text-sm font-medium text-white capitalize">{design.text_style || "—"}</div>
        </div>
        <div className="bg-white/5 rounded-lg p-3 border border-white/5">
          <div className="text-xs text-zinc-500 mb-1">Intensity</div>
          <div className="text-sm font-medium text-white capitalize">{design.intensity_curve || "—"}</div>
        </div>
        <div className="bg-white/5 rounded-lg p-3 border border-white/5">
          <div className="text-xs text-zinc-500 mb-1">Sections</div>
          <div className="text-sm font-medium text-white">{result.sections?.length || 0}</div>
        </div>
        <div className="bg-white/5 rounded-lg p-3 border border-white/5">
          <div className="text-xs text-zinc-500 mb-1">File Size</div>
          <div className="text-sm font-medium text-white">{result.file_size_kb} KB</div>
        </div>
      </div>

      {/* Color palette */}
      {design.palette && design.palette.length > 0 && (
        <div className="flex items-center gap-2">
          <Palette className="w-4 h-4 text-zinc-500" />
          <span className="text-xs text-zinc-500">Palette:</span>
          <div className="flex gap-1.5">
            {design.palette.map((c, i) => (
              <div
                key={i}
                className="w-6 h-6 rounded-full border border-white/20"
                style={{ backgroundColor: `rgb(${c[0]},${c[1]},${c[2]})` }}
                title={`RGB(${c[0]}, ${c[1]}, ${c[2]})`}
              />
            ))}
          </div>
        </div>
      )}

      {/* Sections timeline */}
      {result.sections && result.sections.length > 0 && (
        <div>
          <div className="text-xs text-zinc-500 mb-2 flex items-center gap-1">
            <Sparkles className="w-3 h-3" /> Song Sections
          </div>
          <div className="flex gap-0.5 h-6 rounded-md overflow-hidden">
            {result.sections.map((s, i) => {
              const totalDuration = meta.duration * 1000;
              const width = totalDuration > 0 ? ((s.end_ms - s.start_ms) / totalDuration * 100) : (100 / result.sections.length);
              const palette = design.palette || [[0,255,100]];
              const color = palette[i % palette.length];
              return (
                <div
                  key={i}
                  className="relative group cursor-default"
                  style={{
                    width: `${Math.max(2, width)}%`,
                    backgroundColor: `rgba(${color[0]},${color[1]},${color[2]},0.3)`,
                    borderLeft: i > 0 ? "1px solid rgba(255,255,255,0.1)" : "none",
                  }}
                  title={`${s.label} (${(s.start_ms/1000).toFixed(1)}s - ${(s.end_ms/1000).toFixed(1)}s) energy: ${(s.energy*100).toFixed(0)}%`}
                >
                  <div className="absolute inset-0 flex items-center justify-center">
                    <span className="text-[9px] font-bold text-white/60 uppercase tracking-wider truncate px-1">
                      {s.label}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Download button */}
      <Button
        onClick={handleDownload}
        disabled={downloading}
        className="w-full bg-green-600 hover:bg-green-700 text-white font-semibold h-12 text-base"
      >
        {downloading ? (
          <Loader2 className="w-5 h-5 animate-spin mr-2" />
        ) : (
          <Download className="w-5 h-5 mr-2" />
        )}
        {downloading ? "Downloading..." : `Download ${result.ilda_filename || "show.ild"}`}
      </Button>
    </div>
  );
};

const SongToLaser = () => {
  const [url, setUrl] = useState("");
  const [processing, setProcessing] = useState(false);
  const [currentStage, setCurrentStage] = useState(null);
  const [completedStages, setCompletedStages] = useState([]);
  const [stageData, setStageData] = useState({});
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const eventSourceRef = useRef(null);

  const resetState = useCallback(() => {
    setCurrentStage(null);
    setCompletedStages([]);
    setStageData({});
    setResult(null);
    setError(null);
  }, []);

  const handleAnalyze = useCallback(async () => {
    if (!url.trim() || processing) return;

    const trimmedUrl = url.trim();
    // Basic YouTube URL validation
    if (!trimmedUrl.match(/^(https?:\/\/)?(www\.)?(youtube\.com|youtu\.be|music\.youtube\.com)\/.+/)) {
      toast.error("Please enter a valid YouTube URL");
      return;
    }

    resetState();
    setProcessing(true);
    setError(null);

    try {
      const response = await fetch(`${API}/youtube/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ youtube_url: trimmedUrl }),
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          const trimmedLine = line.trim();
          if (!trimmedLine) continue;

          if (trimmedLine.startsWith("data:") || trimmedLine.startsWith("data: ")) {
            const dataStr = trimmedLine.replace(/^data:\s*/, "");
            try {
              const data = JSON.parse(dataStr);

              if (data.stage) {
                if (data.stage.endsWith("_done")) {
                  setCompletedStages(prev => [...prev, data.stage]);
                  setStageData(prev => ({ ...prev, [data.stage]: data }));
                  // Advance current stage to next
                  const doneIdx = PIPELINE_STAGES.findIndex(s => s.doneKey === data.stage);
                  if (doneIdx >= 0 && doneIdx + 1 < PIPELINE_STAGES.length) {
                    // Don't advance yet — will be set by next "active" event
                  }
                } else if (data.stage === "error") {
                  setError(data.error || "Pipeline failed");
                  setProcessing(false);
                  toast.error(data.error || "Pipeline failed");
                  return;
                } else {
                  setCurrentStage(data.stage);
                }
              }
            } catch {
              // not JSON, skip
            }
          } else if (trimmedLine.startsWith("event:")) {
            const eventType = trimmedLine.replace(/^event:\s*/, "");
            if (eventType === "complete" || eventType === "error") {
              // Next data line will have the payload
            }
          }
        }
      }

      // Process any remaining buffer
      if (buffer.trim()) {
        const remaining = buffer.trim();
        if (remaining.startsWith("data:") || remaining.startsWith("data: ")) {
          const dataStr = remaining.replace(/^data:\s*/, "");
          try {
            const data = JSON.parse(dataStr);
            if (data.status === "complete") {
              setResult(data);
              toast.success("Laser show generated successfully!");
            } else if (data.stage === "error") {
              setError(data.error || "Pipeline failed");
              toast.error(data.error || "Pipeline failed");
            }
          } catch {
            // ignore
          }
        }
      }

      // Check if we got a result from stageData
      if (!result) {
        // The complete event might have been processed inline
        setProcessing(false);
      }

    } catch (e) {
      setError(e.message || "Failed to connect to server");
      toast.error(e.message || "Failed to connect");
    } finally {
      setProcessing(false);
    }
  }, [url, processing, resetState, result]);

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !processing) {
      handleAnalyze();
    }
  };

  const allDone = completedStages.includes("writing_ilda_done");

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      {/* Header */}
      <div className="text-center space-y-2">
        <div className="flex items-center justify-center gap-3">
          <Music className="w-8 h-8 text-green-500" />
          <h2 className="text-2xl font-black text-white tracking-tight">Song to Laser</h2>
        </div>
        <p className="text-sm text-zinc-500 max-w-lg mx-auto">
          Paste a YouTube link → We extract lyrics, analyze the audio, design a laser show with AI, and generate a downloadable .ild file.
        </p>
      </div>

      {/* URL Input */}
      <div className="card-surface p-4">
        <div className="flex gap-3">
          <div className="relative flex-1">
            <Youtube className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-red-500/60" />
            <Input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="https://youtube.com/watch?v=..."
              className="bg-[#0A0A0A] border-white/10 text-white pl-11 h-12 text-base placeholder:text-zinc-600 font-mono"
              disabled={processing}
            />
          </div>
          <Button
            onClick={handleAnalyze}
            disabled={!url.trim() || processing}
            className="bg-green-600 hover:bg-green-700 disabled:opacity-30 h-12 px-6 text-base font-semibold"
          >
            {processing ? (
              <>
                <Loader2 className="w-5 h-5 animate-spin mr-2" />
                Processing
              </>
            ) : (
              <>
                <Zap className="w-5 h-5 mr-2" />
                Generate
              </>
            )}
          </Button>
        </div>
      </div>

      {/* Pipeline Progress */}
      {(processing || allDone || error) && (
        <div className="card-surface p-4">
          <div className="flex items-center gap-2 mb-4">
            <Sparkles className="w-5 h-5 text-green-500" />
            <h3 className="font-bold text-white">Pipeline Progress</h3>
            {allDone && <span className="text-xs text-green-500 ml-auto">Complete!</span>}
          </div>
          <div className="space-y-2">
            {PIPELINE_STAGES.map((stage) => (
              <StageIndicator
                key={stage.key}
                stage={stage}
                currentStage={currentStage}
                completedStages={completedStages}
                stageData={stageData}
              />
            ))}
          </div>

          {error && (
            <div className="mt-4 flex items-start gap-3 p-3 rounded-lg bg-red-500/10 border border-red-500/30">
              <AlertCircle className="w-5 h-5 text-red-400 flex-shrink-0 mt-0.5" />
              <div>
                <p className="text-sm font-medium text-red-400">Pipeline Error</p>
                <p className="text-xs text-red-400/70 mt-1">{error}</p>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Result */}
      {result && <ResultCard result={result} />}

      {/* Empty state */}
      {!processing && !result && !error && (
        <div className="card-surface p-8 text-center">
          <div className="w-16 h-16 rounded-full bg-green-500/10 border border-green-500/20 flex items-center justify-center mx-auto mb-4">
            <Music className="w-8 h-8 text-green-500/50" />
          </div>
          <h3 className="text-lg font-semibold text-white mb-2">Lyrics on Laser</h3>
          <p className="text-sm text-zinc-500 max-w-md mx-auto">
            Enter a YouTube URL above to generate a laser show. The pipeline extracts audio, 
            fetches synced lyrics, analyzes the beat, and creates an ILDA-compatible .ild file 
            with text animations and geometric effects.
          </p>
          <div className="flex flex-wrap gap-2 justify-center mt-5">
            {["Synced Lyrics", "Beat Detection", "AI Show Design", "Hershey Font", "ILDA Format 5", "30fps"].map((tag) => (
              <span key={tag} className="px-2.5 py-1 rounded-full bg-white/5 border border-white/10 text-xs text-zinc-500">
                {tag}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

export default SongToLaser;
