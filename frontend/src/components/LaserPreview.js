import React, { useRef, useEffect, useCallback } from "react";

/**
 * LaserPreview - Canvas component that renders BEYOND SDK point data
 * as a laser-like visualization with glow effects on a dark background.
 */
const LaserPreview = ({ pointData = [], className = "" }) => {
  const canvasRef = useRef(null);

  const parseColor = (colorVal) => {
    // Parse color — can be integer (255, 65280) or hex string ("0x000000FF")
    // BEYOND format: R | (G<<8) | (B<<16) — byte order is R, G, B from low to high
    let colorInt;
    if (typeof colorVal === "string") {
      colorInt = colorVal.startsWith("0x") ? parseInt(colorVal, 16) : parseInt(colorVal, 10);
      colorInt = colorInt || 0;
    } else {
      colorInt = colorVal || 0;
    }

    const r = colorInt & 0xff;
    const g = (colorInt >> 8) & 0xff;
    const b = (colorInt >> 16) & 0xff;

    return { r, g, b, isBlanked: colorInt === 0 };
  };

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    const width = canvas.width;
    const height = canvas.height;

    // Dark background
    ctx.fillStyle = "#050505";
    ctx.fillRect(0, 0, width, height);

    // Draw grid (subtle)
    ctx.strokeStyle = "rgba(34, 197, 94, 0.05)";
    ctx.lineWidth = 0.5;
    const gridSize = 40;
    for (let x = 0; x <= width; x += gridSize) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, height);
      ctx.stroke();
    }
    for (let y = 0; y <= height; y += gridSize) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(width, y);
      ctx.stroke();
    }

    // Draw crosshair at center
    ctx.strokeStyle = "rgba(34, 197, 94, 0.1)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(width / 2, 0);
    ctx.lineTo(width / 2, height);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(0, height / 2);
    ctx.lineTo(width, height / 2);
    ctx.stroke();

    if (!pointData || pointData.length === 0) {
      // Draw placeholder text
      ctx.fillStyle = "rgba(34, 197, 94, 0.2)";
      ctx.font = "14px 'JetBrains Mono', monospace";
      ctx.textAlign = "center";
      ctx.fillText("Laser Preview", width / 2, height / 2 - 10);
      ctx.font = "11px 'JetBrains Mono', monospace";
      ctx.fillStyle = "rgba(255, 255, 255, 0.1)";
      ctx.fillText("Describe a pattern to see it here", width / 2, height / 2 + 15);
      return;
    }

    // Map points to canvas coordinates
    // BEYOND range: -32768 to +32767
    // We use a smaller range for typical patterns: -25000 to +25000
    const mapX = (x) => ((x + 25000) / 50000) * width;
    const mapY = (y) => ((25000 - y) / 50000) * height; // Flip Y axis

    // Draw laser lines with glow effect
    for (let i = 0; i < pointData.length - 1; i++) {
      const p1 = pointData[i];
      const p2 = pointData[i + 1];

      const c1 = parseColor(p1.color);
      const c2 = parseColor(p2.color);

      // Skip if either point is blanked
      if (c1.isBlanked || c2.isBlanked) continue;

      const x1 = mapX(p1.x);
      const y1 = mapY(p1.y);
      const x2 = mapX(p2.x);
      const y2 = mapY(p2.y);

      // Average color between points
      const r = Math.round((c1.r + c2.r) / 2);
      const g = Math.round((c1.g + c2.g) / 2);
      const b = Math.round((c1.b + c2.b) / 2);

      // Outer glow
      ctx.strokeStyle = `rgba(${r}, ${g}, ${b}, 0.15)`;
      ctx.lineWidth = 8;
      ctx.lineCap = "round";
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.lineTo(x2, y2);
      ctx.stroke();

      // Middle glow
      ctx.strokeStyle = `rgba(${r}, ${g}, ${b}, 0.4)`;
      ctx.lineWidth = 4;
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.lineTo(x2, y2);
      ctx.stroke();

      // Core line (bright)
      ctx.strokeStyle = `rgba(${r}, ${g}, ${b}, 1)`;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.lineTo(x2, y2);
      ctx.stroke();

      // White-hot center
      ctx.strokeStyle = `rgba(${Math.min(r + 100, 255)}, ${Math.min(g + 100, 255)}, ${Math.min(b + 100, 255)}, 0.6)`;
      ctx.lineWidth = 0.5;
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.lineTo(x2, y2);
      ctx.stroke();
    }

    // Draw point markers at dwell points (rep_count > 0)
    pointData.forEach((p) => {
      if (p.rep_count > 0) {
        const color = parseColor(p.color);
        if (!color.isBlanked) {
          const x = mapX(p.x);
          const y = mapY(p.y);
          ctx.fillStyle = `rgba(${color.r}, ${color.g}, ${color.b}, 0.8)`;
          ctx.beginPath();
          ctx.arc(x, y, 2, 0, Math.PI * 2);
          ctx.fill();
        }
      }
    });

    // Point count indicator
    ctx.fillStyle = "rgba(255, 255, 255, 0.3)";
    ctx.font = "10px 'JetBrains Mono', monospace";
    ctx.textAlign = "left";
    ctx.fillText(`${pointData.length} pts`, 8, height - 8);
  }, [pointData]);

  useEffect(() => {
    draw();
  }, [draw]);

  // Handle resize
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const resizeObserver = new ResizeObserver(() => {
      const rect = canvas.getBoundingClientRect();
      canvas.width = rect.width * 2; // 2x for retina
      canvas.height = rect.height * 2;
      canvas.getContext("2d").scale(2, 2);
      draw();
    });

    resizeObserver.observe(canvas.parentElement);
    return () => resizeObserver.disconnect();
  }, [draw]);

  return (
    <div className={`relative ${className}`}>
      <canvas
        ref={canvasRef}
        className="w-full h-full rounded-lg"
        style={{ imageRendering: "auto" }}
      />
    </div>
  );
};

export default LaserPreview;
