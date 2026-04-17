import React, { useState, useEffect, useCallback } from "react";
import {
  Image as ImageIcon, Upload, Play, Square, Trash2,
  Loader2, Zap, Clock, BarChart3,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || "http://localhost:8001";
const API = `${BACKEND_URL}/api`;


const GifCard = ({ gif, onPlay, onStop, onDelete, isPlaying, isActive, anyPlaying }) => {
  const [busy, setBusy] = useState(false);

  const handleToggle = async () => {
    setBusy(true);
    try {
      if (isActive) await onStop();
      else await onPlay(gif.gif_id);
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async () => {
    if (!window.confirm(`Delete "${gif.name}"?`)) return;
    setBusy(true);
    try {
      await onDelete(gif.gif_id);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={`card-surface overflow-hidden ${isActive ? "ring-2 ring-green-500/50" : ""}`}>
      <div className="relative bg-black aspect-square overflow-hidden">
        <img
          src={`${API}/gifs/${gif.gif_id}/preview`}
          alt={gif.name}
          className="w-full h-full object-contain"
        />
        {isActive && (
          <div className="absolute top-2 right-2 flex items-center gap-1.5 px-2 py-1 rounded-full bg-green-600/90 text-white text-xs font-semibold">
            <span className="w-2 h-2 rounded-full bg-white animate-pulse" />
            PLAYING
          </div>
        )}
      </div>
      <div className="p-3 space-y-2">
        <h3 className="text-sm font-bold text-white truncate" title={gif.name}>{gif.name}</h3>
        <div className="flex items-center gap-3 text-xs text-zinc-500">
          <span className="flex items-center gap-1"><Clock className="w-3 h-3" /> {(gif.duration_ms/1000).toFixed(1)}s</span>
          <span className="flex items-center gap-1"><BarChart3 className="w-3 h-3" /> {gif.frame_count} f</span>
          <span>~{gif.avg_points} pts</span>
        </div>
        <div className="flex gap-2 pt-1">
          <Button
            onClick={handleToggle}
            disabled={busy || (anyPlaying && !isActive)}
            className={`flex-1 h-9 font-semibold text-sm ${
              isActive
                ? "bg-red-600 hover:bg-red-700 text-white"
                : "bg-green-600 hover:bg-green-700 text-white"
            }`}
          >
            {busy ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : isActive ? (
              <Square className="w-4 h-4" />
            ) : (
              <Zap className="w-4 h-4" />
            )}
            <span className="ml-1.5">{isActive ? "Stop" : "Play"}</span>
          </Button>
          <Button
            onClick={handleDelete}
            disabled={busy}
            variant="outline"
            className="h-9 w-9 p-0 border-white/10 text-zinc-400 hover:text-red-400 hover:bg-red-500/10"
          >
            <Trash2 className="w-4 h-4" />
          </Button>
        </div>
      </div>
    </div>
  );
};


const GifLibrary = () => {
  const [gifs, setGifs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [url, setUrl] = useState("");
  const [uploading, setUploading] = useState(false);
  const [playingId, setPlayingId] = useState(null);

  const loadGifs = useCallback(async () => {
    try {
      const resp = await fetch(`${API}/gifs`);
      const data = await resp.json();
      setGifs(data.gifs || []);
    } catch (e) {
      toast.error("Failed to load GIFs");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadGifs();
    // Poll SDK status for the currently-playing GIF name
    const interval = setInterval(async () => {
      try {
        const resp = await fetch(`${API}/laser/status`);
        const data = await resp.json();
        if (!data.gif_active) setPlayingId(null);
      } catch {}
    }, 2000);
    return () => clearInterval(interval);
  }, [loadGifs]);

  const handleUpload = async () => {
    if (!url.trim() || uploading) return;
    setUploading(true);
    try {
      const resp = await fetch(`${API}/gifs/upload`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: url.trim() }),
      });
      if (!resp.ok) {
        const err = await resp.json();
        throw new Error(err.detail || "Upload failed");
      }
      const meta = await resp.json();
      setGifs(prev => [meta, ...prev]);
      setUrl("");
      toast.success(`Added "${meta.name}" (${meta.frame_count} frames)`);
    } catch (e) {
      toast.error(e.message || "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  const handlePlay = async (gifId) => {
    try {
      const resp = await fetch(`${API}/gifs/${gifId}/play`, { method: "POST" });
      if (!resp.ok) {
        const err = await resp.json();
        throw new Error(err.detail || "Failed to play");
      }
      setPlayingId(gifId);
      toast.success("Playing on laser");
    } catch (e) {
      toast.error(e.message || "Failed to play");
    }
  };

  const handleStop = async () => {
    try {
      await fetch(`${API}/gifs/stop`, { method: "POST" });
      setPlayingId(null);
      toast.success("Stopped");
    } catch {
      toast.error("Failed to stop");
    }
  };

  const handleDelete = async (gifId) => {
    try {
      await fetch(`${API}/gifs/${gifId}`, { method: "DELETE" });
      setGifs(prev => prev.filter(g => g.gif_id !== gifId));
      if (playingId === gifId) setPlayingId(null);
      toast.success("Deleted");
    } catch {
      toast.error("Failed to delete");
    }
  };

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <div className="flex items-center gap-3">
        <ImageIcon className="w-6 h-6 text-green-500" />
        <h2 className="text-xl font-black text-white tracking-tight">GIFs</h2>
        <span className="text-xs text-zinc-500 ml-2">{gifs.length} saved</span>
      </div>

      {/* Upload */}
      <div className="card-surface p-4">
        <div className="flex gap-3">
          <div className="relative flex-1">
            <Upload className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-zinc-500" />
            <Input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleUpload()}
              placeholder="Tenor URL or direct .gif URL..."
              className="bg-[#0A0A0A] border-white/10 text-white pl-11 h-11 placeholder:text-zinc-600 font-mono text-sm"
              disabled={uploading}
            />
          </div>
          <Button
            onClick={handleUpload}
            disabled={!url.trim() || uploading}
            className="bg-green-600 hover:bg-green-700 disabled:opacity-30 h-11 px-5 font-semibold"
          >
            {uploading ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : <Upload className="w-4 h-4 mr-2" />}
            {uploading ? "Processing..." : "Add GIF"}
          </Button>
        </div>
        <p className="text-xs text-zinc-500 mt-2">
          Paste a Tenor URL or direct .gif link. The GIF will be vectorized into laser frames (~10s).
        </p>
      </div>

      {/* Grid */}
      {loading ? (
        <div className="card-surface p-8 text-center">
          <Loader2 className="w-8 h-8 animate-spin text-green-500 mx-auto" />
        </div>
      ) : gifs.length === 0 ? (
        <div className="card-surface p-8 text-center">
          <div className="w-16 h-16 rounded-full bg-green-500/10 border border-green-500/20 flex items-center justify-center mx-auto mb-4">
            <ImageIcon className="w-8 h-8 text-green-500/50" />
          </div>
          <h3 className="text-lg font-semibold text-white mb-2">No GIFs yet</h3>
          <p className="text-sm text-zinc-500 max-w-md mx-auto">
            Paste a Tenor URL above to add your first GIF. Great for instrumental sections and vibes.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
          {gifs.map((gif) => (
            <GifCard
              key={gif.gif_id}
              gif={gif}
              isPlaying={!!playingId}
              isActive={playingId === gif.gif_id}
              anyPlaying={!!playingId}
              onPlay={handlePlay}
              onStop={handleStop}
              onDelete={handleDelete}
            />
          ))}
        </div>
      )}
    </div>
  );
};

export default GifLibrary;
