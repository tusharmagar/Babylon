import React, { useState, useEffect, useCallback } from "react";
import {
  Library as LibraryIcon,
  Zap,
  Download,
  Trash2,
  Loader2,
  Music,
  Clock,
  Disc3,
  BarChart3,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || "http://localhost:8001";
const API = `${BACKEND_URL}/api`;


const SongCard = ({ song, onStreamStart, onStreamStop, onDelete, isStreaming, isActive }) => {
  const [busy, setBusy] = useState(false);

  const handleStream = async () => {
    setBusy(true);
    try {
      if (isActive) {
        await onStreamStop();
      } else {
        await onStreamStart(song.job_id);
      }
    } finally {
      setBusy(false);
    }
  };

  const handleDownload = () => {
    const url = `${API}/youtube/download/${song.job_id}`;
    const a = document.createElement("a");
    a.href = url;
    a.download = song.ilda_filename || "show.ild";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  const handleDelete = async () => {
    if (!window.confirm(`Delete "${song.title}"?`)) return;
    setBusy(true);
    try {
      await onDelete(song.job_id);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={`card-surface p-4 flex gap-4 items-center ${isActive ? "ring-2 ring-green-500/50" : ""}`}>
      {song.thumbnail_url ? (
        <img
          src={song.thumbnail_url}
          alt={song.title}
          className="w-20 h-20 rounded-lg object-cover border border-white/10 flex-shrink-0"
        />
      ) : (
        <div className="w-20 h-20 rounded-lg bg-white/5 border border-white/10 flex items-center justify-center flex-shrink-0">
          <Music className="w-8 h-8 text-zinc-600" />
        </div>
      )}

      <div className="flex-1 min-w-0">
        <h3 className="text-base font-bold text-white truncate">{song.title}</h3>
        <p className="text-sm text-zinc-400 truncate">{song.artist}</p>
        <div className="flex items-center gap-3 mt-1 text-xs text-zinc-500">
          <span className="flex items-center gap-1"><Clock className="w-3 h-3" /> {Math.round(song.duration)}s</span>
          {song.bpm > 0 && <span className="flex items-center gap-1"><Disc3 className="w-3 h-3" /> {Math.round(song.bpm)} BPM</span>}
          <span className="flex items-center gap-1"><BarChart3 className="w-3 h-3" /> {song.total_frames?.toLocaleString()} frames</span>
        </div>
      </div>

      <div className="flex items-center gap-2 flex-shrink-0">
        <Button
          onClick={handleStream}
          disabled={busy || (isStreaming && !isActive)}
          className={`h-10 px-4 font-semibold ${
            isActive
              ? "bg-red-600 hover:bg-red-700 text-white"
              : "bg-green-600 hover:bg-green-700 text-white"
          }`}
        >
          {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
          <span className="ml-2">{isActive ? "Stop" : "Play"}</span>
        </Button>
        <Button
          onClick={handleDownload}
          variant="outline"
          className="h-10 w-10 p-0 border-white/10 text-zinc-400 hover:text-white hover:bg-white/10"
          title="Download .ild"
        >
          <Download className="w-4 h-4" />
        </Button>
        <Button
          onClick={handleDelete}
          disabled={busy}
          variant="outline"
          className="h-10 w-10 p-0 border-white/10 text-zinc-400 hover:text-red-400 hover:bg-red-500/10"
          title="Delete"
        >
          <Trash2 className="w-4 h-4" />
        </Button>
      </div>
    </div>
  );
};


const Library = () => {
  const [songs, setSongs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [streamingJobId, setStreamingJobId] = useState(null);

  const loadLibrary = useCallback(async () => {
    try {
      const resp = await fetch(`${API}/library`);
      const data = await resp.json();
      setSongs(data.songs || []);
    } catch (e) {
      toast.error("Failed to load library");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadLibrary();
    // Poll streaming status so we know if anything is currently playing
    const interval = setInterval(async () => {
      try {
        const resp = await fetch(`${API}/stream/status`);
        const data = await resp.json();
        if (!data.playing) {
          setStreamingJobId((prev) => (prev ? null : prev));
        }
      } catch {}
    }, 2000);
    return () => clearInterval(interval);
  }, [loadLibrary]);

  const handleStreamStart = async (jobId) => {
    try {
      const resp = await fetch(`${API}/stream/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_id: jobId }),
      });
      if (!resp.ok) {
        const err = await resp.json();
        throw new Error(err.detail || "Failed to stream");
      }
      setStreamingJobId(jobId);
      toast.success("Streaming to laser!");
    } catch (e) {
      toast.error(e.message || "Failed to stream");
    }
  };

  const handleStreamStop = async () => {
    try {
      await fetch(`${API}/stream/stop`, { method: "POST" });
      setStreamingJobId(null);
      toast.success("Stream stopped");
    } catch {
      toast.error("Failed to stop");
    }
  };

  const handleDelete = async (jobId) => {
    try {
      await fetch(`${API}/library/${jobId}`, { method: "DELETE" });
      setSongs((prev) => prev.filter((s) => s.job_id !== jobId));
      if (streamingJobId === jobId) setStreamingJobId(null);
      toast.success("Deleted");
    } catch {
      toast.error("Failed to delete");
    }
  };

  return (
    <div className="max-w-4xl mx-auto space-y-4">
      <div className="flex items-center gap-3 mb-4">
        <LibraryIcon className="w-6 h-6 text-green-500" />
        <h2 className="text-xl font-black text-white tracking-tight">Library</h2>
        <span className="text-xs text-zinc-500 ml-2">
          {songs.length} saved {songs.length === 1 ? "song" : "songs"}
        </span>
      </div>

      {loading ? (
        <div className="card-surface p-8 text-center">
          <Loader2 className="w-8 h-8 animate-spin text-green-500 mx-auto" />
          <p className="text-sm text-zinc-500 mt-3">Loading library...</p>
        </div>
      ) : songs.length === 0 ? (
        <div className="card-surface p-8 text-center">
          <div className="w-16 h-16 rounded-full bg-green-500/10 border border-green-500/20 flex items-center justify-center mx-auto mb-4">
            <LibraryIcon className="w-8 h-8 text-green-500/50" />
          </div>
          <h3 className="text-lg font-semibold text-white mb-2">No saved songs yet</h3>
          <p className="text-sm text-zinc-500 max-w-md mx-auto">
            Generate a laser show from the Song to Laser tab and it will appear here for instant replay.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {songs.map((song) => (
            <SongCard
              key={song.job_id}
              song={song}
              isStreaming={!!streamingJobId}
              isActive={streamingJobId === song.job_id}
              onStreamStart={handleStreamStart}
              onStreamStop={handleStreamStop}
              onDelete={handleDelete}
            />
          ))}
        </div>
      )}
    </div>
  );
};

export default Library;
