import React, { useState, useEffect, useRef } from "react";
import axios from "axios";
import {
  Send,
  Bot,
  User,
  Copy,
  Check,
  Download,
  Plus,
  Trash2,
  MessageSquare,
  Code,
  Loader2,
  Sparkles,
  ChevronRight,
  Zap,
  ZapOff,
  Brain,
  Wrench,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { toast } from "sonner";
import LaserPreview from "@/components/LaserPreview";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || "http://localhost:8001";
const API = `${BACKEND_URL}/api`;

// Code block with copy + download
const CodeBlock = ({ code, patternName }) => {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      toast.success("Code copied");
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error("Failed to copy");
    }
  };

  const handleDownload = () => {
    const blob = new Blob([code], { type: "text/x-python" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `beyond_${(patternName || "pattern").toLowerCase().replace(/\s+/g, "_")}.py`;
    a.click();
    URL.revokeObjectURL(url);
    toast.success("Script downloaded");
  };

  return (
    <div className="rounded-lg border border-white/10 bg-[#0A0A0A] overflow-hidden">
      <div className="flex items-center justify-between px-3 py-2 bg-white/5 border-b border-white/10">
        <div className="flex items-center gap-2">
          <Code className="w-3.5 h-3.5 text-green-500" />
          <span className="text-xs text-zinc-400 font-mono">reference_code.py</span>
        </div>
        <div className="flex gap-1">
          <button onClick={handleCopy} className="p-1.5 rounded hover:bg-white/10 transition-colors" title="Copy">
            {copied ? <Check className="w-3.5 h-3.5 text-green-500" /> : <Copy className="w-3.5 h-3.5 text-zinc-400" />}
          </button>
          <button onClick={handleDownload} className="p-1.5 rounded hover:bg-white/10 transition-colors" title="Download">
            <Download className="w-3.5 h-3.5 text-zinc-400" />
          </button>
        </div>
      </div>
      <pre className="p-3 overflow-x-auto text-xs font-mono text-zinc-300 max-h-[250px] overflow-y-auto leading-relaxed">
        <code>{code}</code>
      </pre>
    </div>
  );
};

// Stop-the-stream button — kills whatever is currently playing on the laser
const StopLaserButton = ({ compact = false }) => {
  const [stopping, setStopping] = useState(false);

  const handleStop = async () => {
    setStopping(true);
    try {
      await axios.post(`${API}/laser/stop`);
      toast.success("Laser stopped");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Failed to stop laser");
    } finally {
      setStopping(false);
    }
  };

  return (
    <button
      onClick={handleStop}
      disabled={stopping}
      className={`${compact ? "h-10 w-10 p-0" : "h-11 px-4"} flex-shrink-0 flex items-center justify-center gap-2 rounded-lg bg-red-600/20 border border-red-500/40 text-red-300 hover:bg-red-600/30 disabled:opacity-40 font-semibold text-sm transition-all active:scale-[0.98]`}
      title="Stop laser output"
    >
      {stopping ? <Loader2 className="w-4 h-4 animate-spin" /> : <ZapOff className="w-4 h-4" />}
      {!compact && <span>Stop</span>}
    </button>
  );
};


// Send to Laser button — supports static patterns and animated scene lists
const SendToLaserButton = ({ pointData, patternName, scenes, durationsMs, disabled }) => {
  const [sending, setSending] = useState(false);
  const isAnimated = Array.isArray(scenes) && scenes.length > 1;

  const handleSend = async () => {
    if (!isAnimated && (!pointData || pointData.length === 0)) return;
    setSending(true);
    try {
      if (isAnimated) {
        const res = await axios.post(`${API}/laser/pattern/play`, {
          scenes,
          durations_ms: durationsMs,
          pattern_name: patternName || "AI Animation",
        });
        if (res.data.success) {
          toast.success(
            `Animating ${res.data.scene_count} scenes (${(res.data.total_ms / 1000).toFixed(1)}s loop)`
          );
        }
      } else {
        const res = await axios.post(`${API}/laser/send`, {
          point_data: pointData,
          pattern_name: patternName || "AI Pattern",
        });
        if (res.data.success) {
          toast.success(
            res.data.simulation_mode
              ? `Pattern loaded (simulation) — ${res.data.point_count} points`
              : `Streaming to laser — ${res.data.point_count} points`
          );
        }
      }
    } catch (e) {
      toast.error(e.response?.data?.detail || "Failed to send to laser");
    } finally {
      setSending(false);
    }
  };

  return (
    <button
      onClick={handleSend}
      disabled={disabled || !pointData || pointData.length === 0 || sending}
      className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-lg bg-green-600 hover:bg-green-700 disabled:opacity-30 disabled:cursor-not-allowed text-white font-semibold text-sm transition-all active:scale-[0.98]"
    >
      {sending ? (
        <Loader2 className="w-4 h-4 animate-spin" />
      ) : (
        <Zap className="w-4 h-4" />
      )}
      {sending ? "Sending..." : "Send to Laser"}
    </button>
  );
};

// Chat message component
const ChatMessageItem = ({ message }) => {
  const isUser = message.role === "user";

  if (isUser) {
    return (
      <div className="flex gap-3 justify-end">
        <div className="max-w-[80%]">
          <div className="bg-green-600/20 border border-green-500/30 rounded-2xl rounded-tr-sm px-4 py-2.5">
            <p className="text-sm text-white whitespace-pre-wrap">{message.content}</p>
          </div>
        </div>
        <div className="w-8 h-8 rounded-full bg-green-600/20 border border-green-500/30 flex items-center justify-center flex-shrink-0">
          <User className="w-4 h-4 text-green-500" />
        </div>
      </div>
    );
  }

  // Assistant message
  const hasPoints = message.point_data && message.point_data.length > 0;
  const hasCode = message.python_code && message.python_code.length > 20;

  return (
    <div className="flex gap-3">
      <div className="w-8 h-8 rounded-full bg-blue-600/20 border border-blue-500/30 flex items-center justify-center flex-shrink-0 mt-0.5">
        <Bot className="w-4 h-4 text-blue-400" />
      </div>
      <div className="max-w-[90%] space-y-3 flex-1 min-w-0">
        {/* AI explanation */}
        <div className="bg-[#1A1A1A] border border-white/10 rounded-2xl rounded-tl-sm px-4 py-2.5">
          <p className="text-sm text-zinc-300 whitespace-pre-wrap leading-relaxed">
            {message.content || message.ai_message}
          </p>
        </div>

        {/* Laser Preview + Send to Laser */}
        {hasPoints && (
          <div className="rounded-lg border border-white/10 overflow-hidden">
            <div className="flex items-center gap-2 px-3 py-2 bg-white/5 border-b border-white/10">
              <Sparkles className="w-3.5 h-3.5 text-green-500" />
              <span className="text-xs text-zinc-400">
                Laser Preview — {message.pattern_name || "Pattern"}
              </span>
              {Array.isArray(message.scenes) && message.scenes.length > 1 && (
                <span className="text-[10px] uppercase tracking-wide font-semibold text-purple-400 px-1.5 py-0.5 rounded bg-purple-500/10 border border-purple-500/30">
                  {message.scenes.length} scenes · {((message.durations_ms || []).reduce((a, b) => a + b, 0) / 1000).toFixed(1)}s
                </span>
              )}
              <span className="text-xs text-zinc-600 ml-auto">
                {message.point_data.length} points
              </span>
            </div>
            <div className="h-[280px] bg-[#050505]">
              <LaserPreview pointData={message.point_data} className="w-full h-full" />
            </div>
            <div className="p-2 bg-white/5 border-t border-white/10 flex gap-2">
              <div className="flex-1">
                <SendToLaserButton
                  pointData={message.point_data}
                  patternName={message.pattern_name}
                  scenes={message.scenes}
                  durationsMs={message.durations_ms}
                />
              </div>
              <StopLaserButton />
            </div>
          </div>
        )}

        {/* Python code (reference) */}
        {hasCode && (
          <details className="group">
            <summary className="flex items-center gap-2 cursor-pointer text-xs text-zinc-500 hover:text-zinc-300 transition-colors py-1">
              <Code className="w-3.5 h-3.5" />
              <span>View reference SDK code</span>
              <ChevronRight className="w-3 h-3 transition-transform group-open:rotate-90" />
            </summary>
            <div className="mt-2">
              <CodeBlock code={message.python_code} patternName={message.pattern_name} />
            </div>
          </details>
        )}
      </div>
    </div>
  );
};

// Live streaming assistant message (thinking + tool calls + message, as they arrive)
const StreamingMessage = ({ streaming }) => {
  const [thinkingOpen, setThinkingOpen] = useState(true);
  const hasThinking = streaming.thinking && streaming.thinking.length > 0;
  const hasTools = streaming.toolCalls && streaming.toolCalls.length > 0;

  return (
    <div className="flex gap-3">
      <div className="w-8 h-8 rounded-full bg-blue-600/20 border border-blue-500/30 flex items-center justify-center flex-shrink-0 mt-0.5">
        <Bot className="w-4 h-4 text-blue-400" />
      </div>
      <div className="max-w-[90%] space-y-2 flex-1 min-w-0">
        {/* Thinking (collapsible) */}
        {hasThinking && (
          <div className="rounded-lg border border-white/10 bg-[#0F0F0F] overflow-hidden">
            <button
              onClick={() => setThinkingOpen((v) => !v)}
              className="w-full flex items-center gap-2 px-3 py-2 bg-white/5 border-b border-white/10 text-xs text-zinc-400 hover:bg-white/10 transition-colors"
            >
              <Brain className="w-3.5 h-3.5 text-purple-400" />
              <span className="font-semibold">Thinking</span>
              <ChevronRight
                className={`w-3 h-3 ml-auto transition-transform ${thinkingOpen ? "rotate-90" : ""}`}
              />
            </button>
            {thinkingOpen && (
              <pre className="p-3 text-xs font-mono text-zinc-500 whitespace-pre-wrap leading-relaxed max-h-[180px] overflow-y-auto">
                {streaming.thinking}
              </pre>
            )}
          </div>
        )}

        {/* Tool calls list */}
        {hasTools && (
          <div className="rounded-lg border border-white/10 bg-[#0F0F0F] px-3 py-2 space-y-1.5">
            {streaming.toolCalls.map((t, i) => (
              <div key={i} className="flex items-center gap-2 text-xs">
                {t.done ? (
                  <Check className="w-3.5 h-3.5 text-green-500 flex-shrink-0" />
                ) : (
                  <Loader2 className="w-3.5 h-3.5 text-blue-400 animate-spin flex-shrink-0" />
                )}
                <Wrench className="w-3 h-3 text-zinc-500 flex-shrink-0" />
                <span className="text-zinc-300 font-mono">{t.name}</span>
                {t.done && (
                  <span className="text-zinc-600 ml-1">· {t.point_count} pts</span>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Message text as it streams */}
        {streaming.message && (
          <div className="bg-[#1A1A1A] border border-white/10 rounded-2xl rounded-tl-sm px-4 py-2.5">
            <p className="text-sm text-zinc-300 whitespace-pre-wrap leading-relaxed">
              {streaming.message}
              <span className="inline-block w-1.5 h-3 bg-green-500 ml-0.5 align-middle animate-pulse" />
            </p>
          </div>
        )}

        {/* Idle pulse if nothing yet */}
        {!hasThinking && !hasTools && !streaming.message && (
          <div className="bg-[#1A1A1A] border border-white/10 rounded-2xl rounded-tl-sm px-4 py-3">
            <div className="flex items-center gap-2">
              <Loader2 className="w-4 h-4 text-green-500 animate-spin" />
              <span className="text-sm text-zinc-400">Thinking...</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};


// Suggestion chips
const SUGGESTIONS = [
  "Draw a circle",
  "Draw a 5-point star",
  "Draw the word LASER",
  "Draw a spinning triangle",
  "Draw a heart shape",
  "Draw a spiral",
];

const SuggestionChips = ({ onSelect }) => (
  <div className="flex flex-col items-center gap-4 py-8">
    <div className="flex items-center gap-2 mb-2">
      <Sparkles className="w-5 h-5 text-green-500" />
      <h3 className="text-lg font-semibold text-white">BEYOND AI Builder</h3>
    </div>
    <p className="text-sm text-zinc-500 text-center max-w-md">
      Describe a laser pattern and I'll generate it and stream it directly to BEYOND via the SDK.
    </p>
    <div className="flex flex-wrap gap-2 justify-center mt-2 max-w-lg">
      {SUGGESTIONS.map((s) => (
        <button
          key={s}
          onClick={() => onSelect(s)}
          className="px-3 py-1.5 rounded-full border border-white/10 bg-white/5 text-xs text-zinc-400 hover:text-green-400 hover:border-green-500/30 hover:bg-green-500/5 transition-all"
        >
          {s}
        </button>
      ))}
    </div>
  </div>
);

// Main AI Builder
const AIBuilder = ({ sdkStatus }) => {
  const [sessions, setSessions] = useState([]);
  const [currentSessionId, setCurrentSessionId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => { loadSessions(); }, []);

  useEffect(() => {
    if (currentSessionId) {
      loadMessages(currentSessionId);
    } else {
      setMessages([]);
    }
  }, [currentSessionId]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const loadSessions = async () => {
    try {
      const res = await axios.get(`${API}/chat/sessions`);
      setSessions(res.data.sessions || []);
    } catch (e) {
      console.error("Failed to load sessions:", e);
    }
  };

  const loadMessages = async (sessionId) => {
    try {
      const res = await axios.get(`${API}/chat/${sessionId}/messages`);
      setMessages(res.data.messages || []);
    } catch (e) {
      console.error("Failed to load messages:", e);
    }
  };

  const createNewSession = () => {
    setCurrentSessionId(null);
    setMessages([]);
    inputRef.current?.focus();
  };

  const deleteSession = async (sessionId, e) => {
    e.stopPropagation();
    try {
      await axios.delete(`${API}/chat/${sessionId}`);
      setSessions((prev) => prev.filter((s) => s.id !== sessionId));
      if (currentSessionId === sessionId) {
        setCurrentSessionId(null);
        setMessages([]);
      }
      toast.info("Chat deleted");
    } catch {
      toast.error("Failed to delete chat");
    }
  };

  const [streaming, setStreaming] = useState(null);

  const sendMessage = async (text) => {
    const messageText = text || input.trim();
    if (!messageText || loading) return;

    setInput("");
    setLoading(true);

    const tempUserMsg = {
      id: `temp-${Date.now()}`,
      role: "user",
      content: messageText,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, tempUserMsg]);

    // Initialize streaming state
    setStreaming({ thinking: "", toolCalls: [], message: "" });

    let sessionIdLocal = currentSessionId;
    let finalPayload = null;

    try {
      const resp = await fetch(`${API}/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: messageText, session_id: currentSessionId }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${resp.status}`);
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      const splitFrame = (s) => {
        // SSE frames can be separated by \n\n or \r\n\r\n — handle both
        const idxA = s.indexOf("\n\n");
        const idxB = s.indexOf("\r\n\r\n");
        if (idxA === -1 && idxB === -1) return [-1, 0];
        if (idxA === -1) return [idxB, 4];
        if (idxB === -1) return [idxA, 2];
        return idxA < idxB ? [idxA, 2] : [idxB, 4];
      };

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        while (true) {
          const [sep, sepLen] = splitFrame(buffer);
          if (sep === -1) break;
          const raw = buffer.slice(0, sep);
          buffer = buffer.slice(sep + sepLen);
          let eventName = "message";
          let data = "";
          for (const line of raw.split(/\r?\n/)) {
            if (line.startsWith(":")) continue; // comment / keepalive
            if (line.startsWith("event:")) eventName = line.slice(6).trim();
            else if (line.startsWith("data:")) data += line.slice(5).trim();
          }
          console.log("[SSE]", eventName, data.slice(0, 120));
          if (!data) continue;
          let payload;
          try { payload = JSON.parse(data); } catch (err) {
            console.warn("[SSE] JSON parse failed:", err, data);
            continue;
          }

          if (eventName === "session") {
            sessionIdLocal = payload.session_id;
            if (!currentSessionId) setCurrentSessionId(payload.session_id);
          } else if (eventName === "thinking") {
            setStreaming((s) => s && { ...s, thinking: s.thinking + (payload.delta || "") });
          } else if (eventName === "tool_start") {
            setStreaming((s) => s && {
              ...s,
              toolCalls: [...s.toolCalls, { name: payload.name, done: false, point_count: 0 }],
            });
          } else if (eventName === "tool_done") {
            setStreaming((s) => {
              if (!s) return s;
              const calls = [...s.toolCalls];
              // Mark the first still-pending call with this name as done
              const idx = calls.findIndex((c) => c.name === payload.name && !c.done);
              if (idx >= 0) {
                calls[idx] = { ...calls[idx], done: true, point_count: payload.point_count };
              } else {
                calls.push({ name: payload.name, done: true, point_count: payload.point_count });
              }
              return { ...s, toolCalls: calls };
            });
          } else if (eventName === "message") {
            setStreaming((s) => s && { ...s, message: s.message + (payload.delta || "") });
          } else if (eventName === "final") {
            finalPayload = payload;
          } else if (eventName === "error") {
            throw new Error(payload.error || "AI error");
          }
        }
      }

      if (!finalPayload) throw new Error("Stream ended without a final pattern");

      const aiMsg = {
        id: `ai-${Date.now()}`,
        role: "assistant",
        content: finalPayload.message,
        ai_message: finalPayload.message,
        pattern_name: finalPayload.pattern_name,
        point_data: finalPayload.point_data,
        scenes: finalPayload.scenes,
        durations_ms: finalPayload.durations_ms,
        animated: finalPayload.animated,
        python_code: "",
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, aiMsg]);
      loadSessions();
    } catch (e) {
      toast.error(e.message || "Failed to send message");
      setMessages((prev) => prev.filter((m) => m.id !== tempUserMsg.id));
    } finally {
      setStreaming(null);
      setLoading(false);
    }
  };

  const handleBlackout = async () => {
    try {
      await axios.post(`${API}/laser/blackout`);
      toast.success("Blackout — laser cleared");
    } catch {
      toast.error("Failed to blackout");
    }
  };

  const handleStopStream = async () => {
    try {
      await axios.post(`${API}/laser/stop`);
      toast.success("Stream stopped");
    } catch {
      toast.error("Failed to stop stream");
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  return (
    <div className="flex h-[calc(100vh-120px)] gap-0 overflow-hidden rounded-lg border border-white/10">
      {/* Sessions Sidebar */}
      <div
        className={`${sidebarOpen ? "w-64" : "w-0"} transition-all duration-200 bg-[#0A0A0A] border-r border-white/10 flex flex-col overflow-hidden flex-shrink-0`}
      >
        <div className="p-3 border-b border-white/10">
          <Button
            onClick={createNewSession}
            className="w-full bg-green-600 hover:bg-green-700 text-white text-sm h-9"
            size="sm"
          >
            <Plus className="w-4 h-4 mr-2" />
            New Chat
          </Button>
        </div>
        <ScrollArea className="flex-1">
          <div className="p-2 space-y-1">
            {sessions.map((session) => (
              <button
                key={session.id}
                onClick={() => setCurrentSessionId(session.id)}
                className={`w-full text-left px-3 py-2 rounded-lg text-sm transition-all group flex items-center gap-2 ${
                  currentSessionId === session.id
                    ? "bg-white/10 text-white"
                    : "text-zinc-400 hover:bg-white/5 hover:text-white"
                }`}
              >
                <MessageSquare className="w-3.5 h-3.5 flex-shrink-0" />
                <span className="truncate flex-1">{session.title}</span>
                <button
                  onClick={(e) => deleteSession(session.id, e)}
                  className="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-white/10 transition-all"
                >
                  <Trash2 className="w-3 h-3 text-zinc-500 hover:text-red-400" />
                </button>
              </button>
            ))}
            {sessions.length === 0 && (
              <p className="text-xs text-zinc-600 text-center py-4">No chats yet</p>
            )}
          </div>
        </ScrollArea>
        {/* Quick controls in sidebar */}
        <div className="p-3 border-t border-white/10 space-y-2">
          <button
            onClick={handleStopStream}
            className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg bg-amber-600/20 border border-amber-500/30 text-amber-400 hover:bg-amber-600/30 text-xs font-semibold transition-all"
          >
            <Zap className="w-3.5 h-3.5" />
            STOP STREAM
          </button>
          <button
            onClick={handleBlackout}
            className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg bg-red-600/20 border border-red-500/30 text-red-400 hover:bg-red-600/30 text-xs font-semibold transition-all"
          >
            <ZapOff className="w-3.5 h-3.5" />
            BLACKOUT
          </button>
        </div>
      </div>

      {/* Toggle sidebar */}
      <button
        onClick={() => setSidebarOpen(!sidebarOpen)}
        className="w-5 flex items-center justify-center bg-[#0D0D0D] hover:bg-white/5 border-r border-white/10 transition-colors flex-shrink-0"
      >
        <ChevronRight
          className={`w-3 h-3 text-zinc-600 transition-transform ${sidebarOpen ? "rotate-180" : ""}`}
        />
      </button>

      {/* Main Chat Area */}
      <div className="flex-1 flex flex-col min-w-0 bg-[#121212]">
        {/* Messages */}
        <ScrollArea className="flex-1 px-4 py-4">
          <div className="max-w-3xl mx-auto space-y-4">
            {messages.length === 0 ? (
              <SuggestionChips onSelect={(text) => sendMessage(text)} />
            ) : (
              messages.map((msg) => <ChatMessageItem key={msg.id} message={msg} />)
            )}

            {streaming && <StreamingMessage streaming={streaming} />}

            <div ref={messagesEndRef} />
          </div>
        </ScrollArea>

        {/* Input */}
        <div className="border-t border-white/10 p-4 bg-[#0D0D0D]">
          <div className="max-w-3xl mx-auto">
            <div className="flex gap-2 items-end">
              <div className="flex-1 relative">
                <textarea
                  ref={inputRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="Describe a laser pattern... (e.g., 'Draw a spinning star')"
                  className="w-full bg-[#1A1A1A] border border-white/10 rounded-xl px-4 py-3 pr-12 text-sm text-white placeholder:text-zinc-600 focus:outline-none focus:border-green-500/50 resize-none min-h-[44px] max-h-[120px]"
                  rows={1}
                  disabled={loading}
                  style={{ height: "44px" }}
                  onInput={(e) => {
                    e.target.style.height = "44px";
                    e.target.style.height = Math.min(e.target.scrollHeight, 120) + "px";
                  }}
                />
              </div>
              <Button
                onClick={() => sendMessage()}
                disabled={!input.trim() || loading}
                className="bg-green-600 hover:bg-green-700 disabled:opacity-30 h-[44px] w-[44px] p-0 rounded-xl flex-shrink-0"
                size="icon"
              >
                <Send className="w-4 h-4" />
              </Button>
            </div>
            <p className="text-[10px] text-zinc-600 mt-2 text-center">
              AI generates patterns → Click "Send to Laser" to stream directly to BEYOND via SDK
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};

export default AIBuilder;
