import { useState, useEffect } from "react";
import "@/App.css";
import axios from "axios";
import { Settings, Power, Cpu, LayoutGrid, Zap, ZapOff } from "lucide-react";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Toaster } from "@/components/ui/sonner";
import { toast } from "sonner";
import AIBuilder from "@/components/AIBuilder";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

// SDK Status Indicator
const SDKStatus = ({ status }) => {
  const isLive = status.initialized && !status.simulation_mode;
  const isSimulation = status.initialized && status.simulation_mode;

  return (
    <div className="flex items-center gap-3" data-testid="sdk-status">
      <div
        className={`status-dot ${
          isLive ? "online pulse-online" : isSimulation ? "simulation" : "offline pulse-offline"
        }`}
      />
      <div className="flex flex-col">
        <span className="text-sm font-medium text-white">
          {isLive ? "BEYOND Connected" : isSimulation ? "Simulation Mode" : "SDK Offline"}
        </span>
        {status.streaming && (
          <span className="text-xs text-green-500">
            Streaming: {status.current_pattern || "Active"} ({status.point_count} pts)
          </span>
        )}
        {!status.streaming && status.initialized && (
          <span className="text-xs text-zinc-500">Idle — no pattern loaded</span>
        )}
      </div>
    </div>
  );
};

// Master controls panel for the Cues/Controls tab
const LaserControls = ({ status, onBlackout }) => {
  return (
    <div className="card-surface p-6 max-w-md mx-auto">
      <div className="flex items-center gap-2 mb-6">
        <Power className="w-5 h-5 text-amber-500" />
        <h2 className="font-bold text-lg">Laser Controls</h2>
      </div>

      {/* Status info */}
      <div className="space-y-3 mb-6">
        <div className="flex justify-between text-sm">
          <span className="text-zinc-500">SDK Status</span>
          <span className={status.initialized ? "text-green-500" : "text-red-500"}>
            {status.initialized
              ? status.simulation_mode
                ? "Simulation"
                : "Connected"
              : "Offline"}
          </span>
        </div>
        <div className="flex justify-between text-sm">
          <span className="text-zinc-500">Streaming</span>
          <span className={status.streaming ? "text-green-500" : "text-zinc-400"}>
            {status.streaming ? `${status.current_pattern} (${status.point_count} pts)` : "Idle"}
          </span>
        </div>
        <div className="flex justify-between text-sm">
          <span className="text-zinc-500">Frames Sent</span>
          <span className="text-zinc-400">{status.frames_sent?.toLocaleString() || 0}</span>
        </div>
        <div className="flex justify-between text-sm">
          <span className="text-zinc-500">Scan Rate</span>
          <span className="text-zinc-400">{status.scan_rate?.toLocaleString() || 30000} pps</span>
        </div>
        {status.last_error && (
          <div className="text-xs text-red-400 mt-2 p-2 bg-red-500/10 rounded">
            {status.last_error}
          </div>
        )}
      </div>

      {/* Blackout / Stop */}
      <div className="space-y-3">
        <button
          data-testid="blackout-btn"
          onClick={onBlackout}
          className="stop-button w-full h-16 rounded-lg text-lg btn-press flex items-center justify-center gap-2"
        >
          <ZapOff className="w-6 h-6" />
          BLACKOUT
        </button>
        <p className="text-xs text-zinc-600 text-center">
          Clears all laser output and stops streaming
        </p>
      </div>
    </div>
  );
};

// Main App
function App() {
  const [sdkStatus, setSdkStatus] = useState({
    initialized: false,
    simulation_mode: true,
    streaming: false,
    point_count: 0,
    current_pattern: "",
    frames_sent: 0,
    fps: 30,
    scan_rate: 30000,
    last_error: null,
  });

  // Poll SDK status
  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const res = await axios.get(`${API}/laser/status`);
        setSdkStatus(res.data);
      } catch {
        // Server not reachable
      }
    };
    fetchStatus();
    const interval = setInterval(fetchStatus, 2000);
    return () => clearInterval(interval);
  }, []);

  const handleBlackout = async () => {
    try {
      await axios.post(`${API}/laser/blackout`);
      toast.success("Blackout — laser cleared");
    } catch {
      toast.error("Failed to send blackout");
    }
  };

  return (
    <div className="app-container">
      <div className="bg-texture" />
      <Toaster position="top-right" theme="dark" />

      {/* Header */}
      <header className="header-glass sticky top-0 z-50 px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Zap className="w-8 h-8 text-green-500" />
            <div>
              <h1 className="text-xl font-black tracking-tight" data-testid="app-title">
                BEYOND CONTROL
              </h1>
              <p className="text-xs text-zinc-500">SDK Direct — AI Laser Builder</p>
            </div>
          </div>
          <SDKStatus status={sdkStatus} />
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto p-6 relative z-10">
        <Tabs defaultValue="ai-builder" className="w-full">
          <TabsList className="bg-[#1A1A1A] border border-white/10 mb-6 p-1 h-auto">
            <TabsTrigger
              value="ai-builder"
              className="data-[state=active]:bg-green-600 data-[state=active]:text-white text-zinc-400 px-4 py-2 rounded-md text-sm font-semibold transition-all gap-2"
            >
              <Cpu className="w-4 h-4" />
              AI Builder
            </TabsTrigger>
            <TabsTrigger
              value="controls"
              className="data-[state=active]:bg-green-600 data-[state=active]:text-white text-zinc-400 px-4 py-2 rounded-md text-sm font-semibold transition-all gap-2"
            >
              <LayoutGrid className="w-4 h-4" />
              Controls
            </TabsTrigger>
          </TabsList>

          <TabsContent value="ai-builder">
            <AIBuilder sdkStatus={sdkStatus} />
          </TabsContent>

          <TabsContent value="controls">
            <LaserControls status={sdkStatus} onBlackout={handleBlackout} />
          </TabsContent>
        </Tabs>
      </main>
    </div>
  );
}

export default App;
