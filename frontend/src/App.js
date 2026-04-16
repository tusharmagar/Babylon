import { useState, useEffect, useRef, useCallback } from "react";
import "@/App.css";
import axios from "axios";
import { Settings, Power, Square, AlertTriangle, Terminal, Wifi, WifiOff, Trash2 } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Toaster } from "@/components/ui/sonner";
import { toast } from "sonner";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

// Cue Button Component
const CueButton = ({ cueNumber, onClick, isActive }) => {
  return (
    <button
      data-testid={`cue-btn-${cueNumber}`}
      onClick={() => onClick(cueNumber)}
      className={`cue-button h-24 rounded-lg flex flex-col items-center justify-center gap-1 btn-press cue-btn ${isActive ? 'active' : ''}`}
    >
      <span className="text-2xl font-bold">{cueNumber}</span>
      <span className="text-xs opacity-50">CUE</span>
    </button>
  );
};

// Connection Status Indicator
const ConnectionStatus = ({ connected, host, port }) => {
  return (
    <div className="flex items-center gap-3" data-testid="connection-status">
      <div className={`status-dot ${connected ? 'online pulse-online' : 'offline pulse-offline'}`} />
      <div className="flex flex-col">
        <span className="text-sm font-medium text-white">
          {connected ? 'Connected' : 'Disconnected'}
        </span>
        {host && port && (
          <span className="text-xs text-zinc-500">{host}:{port}</span>
        )}
      </div>
    </div>
  );
};

// Log Entry Component
const LogEntry = ({ log }) => {
  const timestamp = new Date(log.timestamp).toLocaleTimeString();
  const typeClass = log.type === 'ERROR' ? 'log-error' : 
                    log.type === 'CONNECTION' ? 'log-connection' : 'log-command';
  
  return (
    <div className="text-xs py-1 border-b border-white/5 font-mono">
      <span className="log-timestamp">[{timestamp}]</span>{' '}
      <span className={typeClass}>[{log.type}]</span>{' '}
      <span className="text-white">{log.message}</span>
      {log.response && (
        <span className="log-response"> → {log.response}</span>
      )}
    </div>
  );
};

// Parse ngrok URL helper
const parseNgrokUrl = (url) => {
  // Handle formats like: tcp://0.tcp.in.ngrok.io:18361 or 0.tcp.in.ngrok.io:18361
  let cleaned = url.trim();
  
  // Remove tcp:// prefix if present
  if (cleaned.startsWith('tcp://')) {
    cleaned = cleaned.substring(6);
  }
  
  // Split host and port
  const parts = cleaned.split(':');
  if (parts.length === 2) {
    const host = parts[0];
    const port = parseInt(parts[1], 10);
    if (host && !isNaN(port)) {
      return { host, port };
    }
  }
  
  return null;
};

// Settings Dialog Component
const SettingsDialog = ({ open, onOpenChange, config, onSave, onConnect, onDisconnect, connected }) => {
  const [ngrokUrl, setNgrokUrl] = useState('');
  const [timeout, setTimeout] = useState(config.timeout || 5);

  useEffect(() => {
    if (config.host && config.port) {
      setNgrokUrl(`tcp://${config.host}:${config.port}`);
    }
    setTimeout(config.timeout || 5);
  }, [config]);

  const handleUrlChange = (e) => {
    setNgrokUrl(e.target.value);
  };

  const handleConnect = async () => {
    const parsed = parseNgrokUrl(ngrokUrl);
    if (!parsed) {
      toast.error('Invalid URL format. Use: tcp://host:port or host:port');
      return;
    }
    await onConnect({ host: parsed.host, port: parsed.port, timeout: parseFloat(timeout) });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-[#121212] border-white/10 text-white max-w-md">
        <DialogHeader>
          <DialogTitle className="font-bold text-xl">Connection Settings</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-4">
          <div className="space-y-2">
            <Label htmlFor="ngrokUrl" className="text-zinc-400">ngrok URL</Label>
            <Input
              id="ngrokUrl"
              data-testid="settings-ngrok-url-input"
              value={ngrokUrl}
              onChange={handleUrlChange}
              placeholder="tcp://0.tcp.in.ngrok.io:18361"
              className="bg-[#0A0A0A] border-white/10 text-white placeholder:text-zinc-600 font-mono text-sm"
            />
            <p className="text-xs text-zinc-500">Paste your full ngrok TCP URL</p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="timeout" className="text-zinc-400">Timeout (seconds)</Label>
            <Input
              id="timeout"
              data-testid="settings-timeout-input"
              type="number"
              step="0.5"
              value={timeout}
              onChange={(e) => setTimeout(e.target.value)}
              placeholder="5"
              className="bg-[#0A0A0A] border-white/10 text-white placeholder:text-zinc-600"
            />
          </div>
          <div className="flex gap-3 pt-4">
            {connected ? (
              <Button
                data-testid="settings-disconnect-btn"
                onClick={onDisconnect}
                variant="destructive"
                className="flex-1"
              >
                <WifiOff className="w-4 h-4 mr-2" />
                Disconnect
              </Button>
            ) : (
              <Button
                data-testid="settings-connect-btn"
                onClick={handleConnect}
                className="flex-1 bg-green-600 hover:bg-green-700"
              >
                <Wifi className="w-4 h-4 mr-2" />
                Connect
              </Button>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
};

// Main App Component
function App() {
  const [connected, setConnected] = useState(false);
  const [config, setConfig] = useState({ host: '', port: 16063, timeout: 5 });
  const [logs, setLogs] = useState([]);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [blackoutActive, setBlackoutActive] = useState(false);
  const [activeCue, setActiveCue] = useState(null);
  const logsEndRef = useRef(null);

  // Scroll logs to bottom
  const scrollLogsToBottom = useCallback(() => {
    logsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  useEffect(() => {
    scrollLogsToBottom();
  }, [logs, scrollLogsToBottom]);

  // Fetch initial status and config
  useEffect(() => {
    const fetchInitialData = async () => {
      try {
        const [statusRes, configRes, logsRes] = await Promise.all([
          axios.get(`${API}/status`),
          axios.get(`${API}/config`),
          axios.get(`${API}/logs`)
        ]);
        
        setConnected(statusRes.data.connected);
        if (configRes.data.host) {
          setConfig(configRes.data);
        }
        setLogs(logsRes.data.logs || []);
      } catch (e) {
        console.error('Failed to fetch initial data:', e);
      }
    };
    fetchInitialData();
  }, []);

  // Poll for status updates
  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const [statusRes, logsRes] = await Promise.all([
          axios.get(`${API}/status`),
          axios.get(`${API}/logs?limit=50`)
        ]);
        setConnected(statusRes.data.connected);
        setLogs(logsRes.data.logs || []);
      } catch (e) {
        setConnected(false);
      }
    }, 2000);
    return () => clearInterval(interval);
  }, []);

  // Connect to BEYOND
  const handleConnect = async (connectionConfig) => {
    try {
      await axios.post(`${API}/connect`, connectionConfig);
      setConnected(true);
      setConfig(connectionConfig);
      toast.success(`Connected to ${connectionConfig.host}:${connectionConfig.port}`);
      setSettingsOpen(false);
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Connection failed');
    }
  };

  // Disconnect from BEYOND
  const handleDisconnect = async () => {
    try {
      await axios.post(`${API}/disconnect`);
      setConnected(false);
      toast.info('Disconnected from BEYOND');
      setSettingsOpen(false);
    } catch (e) {
      toast.error('Disconnect failed');
    }
  };

  // Start a cue
  const handleStartCue = async (cueNumber) => {
    if (!connected) {
      toast.error('Not connected to BEYOND');
      return;
    }
    try {
      const res = await axios.post(`${API}/cue/start`, { page: 1, cue: cueNumber });
      if (res.data.success) {
        setActiveCue(cueNumber);
        toast.success(`Started Cue ${cueNumber}`);
      } else {
        toast.error(res.data.error || 'Failed to start cue');
      }
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Failed to start cue');
    }
  };

  // Stop all playback
  const handleStopAll = async () => {
    if (!connected) {
      toast.error('Not connected to BEYOND');
      return;
    }
    try {
      const res = await axios.post(`${API}/stop-all`);
      if (res.data.success) {
        setActiveCue(null);
        toast.success('Stopped all playback');
      } else {
        toast.error(res.data.error || 'Failed to stop');
      }
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Failed to stop');
    }
  };

  // Toggle blackout
  const handleBlackoutToggle = async () => {
    if (!connected) {
      toast.error('Not connected to BEYOND');
      return;
    }
    try {
      const endpoint = blackoutActive ? `${API}/blackout/off` : `${API}/blackout/on`;
      const res = await axios.post(endpoint);
      if (res.data.success) {
        setBlackoutActive(!blackoutActive);
        toast.success(blackoutActive ? 'Blackout OFF' : 'Blackout ON');
      } else {
        toast.error(res.data.error || 'Failed to toggle blackout');
      }
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Failed to toggle blackout');
    }
  };

  // Clear logs
  const handleClearLogs = async () => {
    try {
      await axios.delete(`${API}/logs`);
      setLogs([]);
      toast.info('Logs cleared');
    } catch (e) {
      toast.error('Failed to clear logs');
    }
  };

  // Generate cue numbers 1-20
  const cueNumbers = Array.from({ length: 20 }, (_, i) => i + 1);

  return (
    <div className="app-container">
      <div className="bg-texture" />
      <Toaster position="top-right" theme="dark" />
      
      {/* Header */}
      <header className="header-glass sticky top-0 z-50 px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-3">
              <Power className="w-8 h-8 text-green-500" />
              <div>
                <h1 className="text-xl font-black tracking-tight" data-testid="app-title">BEYOND CONTROL</h1>
                <p className="text-xs text-zinc-500">PangoScript Remote Interface</p>
              </div>
            </div>
          </div>
          
          <div className="flex items-center gap-6">
            <ConnectionStatus connected={connected} host={config.host} port={config.port} />
            <Button
              data-testid="settings-btn"
              variant="ghost"
              size="icon"
              onClick={() => setSettingsOpen(true)}
              className="text-zinc-400 hover:text-white hover:bg-white/10"
            >
              <Settings className="w-5 h-5" />
            </Button>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto p-6 relative z-10">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          
          {/* Cue Grid */}
          <div className="lg:col-span-8">
            <div className="card-surface p-4">
              <div className="flex items-center gap-2 mb-4">
                <Square className="w-5 h-5 text-green-500" />
                <h2 className="font-bold text-lg">Cue Triggers</h2>
                <span className="text-xs text-zinc-500 ml-2">Page 1</span>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-5 gap-3" data-testid="cue-grid">
                {cueNumbers.map((num) => (
                  <CueButton
                    key={num}
                    cueNumber={num}
                    onClick={handleStartCue}
                    isActive={activeCue === num}
                  />
                ))}
              </div>
            </div>
          </div>

          {/* Controls Panel */}
          <div className="lg:col-span-4 flex flex-col gap-6">
            
            {/* Master Controls */}
            <div className="card-surface p-4">
              <div className="flex items-center gap-2 mb-4">
                <AlertTriangle className="w-5 h-5 text-amber-500" />
                <h2 className="font-bold text-lg">Master Controls</h2>
              </div>
              <div className="space-y-3">
                <button
                  data-testid="stop-all-btn"
                  onClick={handleStopAll}
                  className="stop-button w-full h-16 rounded-lg text-lg btn-press flex items-center justify-center gap-2"
                >
                  <Square className="w-6 h-6" />
                  STOP ALL
                </button>
                <button
                  data-testid="blackout-btn"
                  onClick={handleBlackoutToggle}
                  className={`blackout-button w-full h-16 rounded-lg text-lg btn-press flex items-center justify-center gap-2 ${blackoutActive ? 'active' : ''}`}
                >
                  <Power className="w-6 h-6" />
                  {blackoutActive ? 'BLACKOUT ON' : 'BLACKOUT'}
                </button>
              </div>
            </div>

            {/* Command Logs */}
            <div className="card-surface p-4 flex-1 flex flex-col min-h-[300px]">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                  <Terminal className="w-5 h-5 text-green-500" />
                  <h2 className="font-bold text-lg">Command Log</h2>
                </div>
                <Button
                  data-testid="clear-logs-btn"
                  variant="ghost"
                  size="icon"
                  onClick={handleClearLogs}
                  className="text-zinc-500 hover:text-white hover:bg-white/10 h-8 w-8"
                >
                  <Trash2 className="w-4 h-4" />
                </Button>
              </div>
              <div className="terminal-panel flex-1 p-3 overflow-hidden relative">
                <div className="terminal-scanlines absolute inset-0" />
                <ScrollArea className="h-full terminal-scroll" data-testid="command-logs">
                  <div className="relative z-10">
                    {logs.length === 0 ? (
                      <div className="text-zinc-600 text-xs font-mono">No commands yet...</div>
                    ) : (
                      logs.map((log) => (
                        <LogEntry key={log.id} log={log} />
                      ))
                    )}
                    <div ref={logsEndRef} />
                  </div>
                </ScrollArea>
              </div>
            </div>
          </div>
        </div>
      </main>

      {/* Settings Dialog */}
      <SettingsDialog
        open={settingsOpen}
        onOpenChange={setSettingsOpen}
        config={config}
        onSave={setConfig}
        onConnect={handleConnect}
        onDisconnect={handleDisconnect}
        connected={connected}
      />
    </div>
  );
}

export default App;
