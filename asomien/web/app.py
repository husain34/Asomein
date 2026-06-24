"""
asomien/web/app.py

FastAPI Web Dashboard for Observability
"""

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
import sqlite3
import logging
import os

logger = logging.getLogger(__name__)

INDEX_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Asomien Command Center</title>
    <script src="https://unpkg.com/htmx.org@1.9.10"></script>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600&family=Fira+Code&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-color: #0B0E14;
            --panel-bg: rgba(22, 27, 34, 0.65);
            --border-color: rgba(255, 255, 255, 0.08);
            --accent-primary: #8a2be2;
            --accent-secondary: #00d2ff;
            --text-main: #e6edf3;
            --text-muted: #8b949e;
        }
        
        body { 
            font-family: 'Outfit', sans-serif; 
            background-color: var(--bg-color); 
            background-image: 
                radial-gradient(circle at 15% 50%, rgba(138, 43, 226, 0.08) 0%, transparent 50%),
                radial-gradient(circle at 85% 30%, rgba(0, 210, 255, 0.08) 0%, transparent 50%);
            color: var(--text-main); 
            margin: 0; 
            padding: 2rem 4rem;
            min-height: 100vh;
        }
        
        h1 {
            font-weight: 600;
            font-size: 2.2rem;
            margin-bottom: 2rem;
            background: linear-gradient(90deg, var(--accent-primary), var(--accent-secondary));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            letter-spacing: -0.5px;
        }

        h2 { 
            font-weight: 400;
            font-size: 1.2rem;
            border-bottom: 1px solid var(--border-color); 
            padding-bottom: 0.8rem; 
            margin-top: 0; 
            color: #fff; 
            text-transform: uppercase;
            letter-spacing: 1px;
        }

        .grid { 
            display: grid; 
            grid-template-columns: 1fr 1.2fr; 
            gap: 2rem; 
            height: calc(100vh - 8rem); 
        }

        .panel { 
            background: var(--panel-bg);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border: 1px solid var(--border-color); 
            border-radius: 16px;
            padding: 1.5rem; 
            overflow-y: auto; 
            box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.3);
            transition: transform 0.3s ease, box-shadow 0.3s ease;
        }
        
        .panel:hover {
            transform: translateY(-2px);
            box-shadow: 0 12px 40px 0 rgba(0, 0, 0, 0.4);
            border: 1px solid rgba(255, 255, 255, 0.15);
        }

        /* Custom Scrollbar */
        ::-webkit-scrollbar { width: 8px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 10px; }
        ::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.2); }

        ul { list-style-type: none; padding-left: 0; margin: 0; }
        li { 
            margin-bottom: 12px; 
            background: rgba(255,255,255,0.02);
            border: 1px solid rgba(255,255,255,0.03);
            border-radius: 8px; 
            padding: 12px; 
            font-size: 0.95rem;
            line-height: 1.5;
            transition: background 0.2s;
        }
        li:hover { background: rgba(255,255,255,0.05); }

        table { border-collapse: separate; border-spacing: 0; width: 100%; margin-top: 1rem; }
        th, td { 
            padding: 12px; 
            text-align: left; 
            border-bottom: 1px solid var(--border-color);
            font-size: 0.95rem;
        }
        th { 
            color: var(--text-muted); 
            font-weight: 400; 
            text-transform: uppercase; 
            font-size: 0.8rem;
            letter-spacing: 1px;
        }
        
        #log-panel li {
            font-family: 'Fira Code', monospace;
            font-size: 0.85rem;
            padding: 8px;
            margin-bottom: 4px;
            background: rgba(0,0,0,0.2);
            border: none;
            border-left: 3px solid var(--accent-secondary);
            border-radius: 0 4px 4px 0;
            color: #a5d6ff;
        }
        #log-panel li:hover { background: rgba(0,0,0,0.4); }
        
        .pulse {
            display: inline-block;
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #2ea043;
            box-shadow: 0 0 10px #2ea043;
            margin-right: 8px;
            animation: pulse 2s infinite;
        }
        
        @keyframes pulse {
            0% { box-shadow: 0 0 0 0 rgba(46, 160, 67, 0.7); }
            70% { box-shadow: 0 0 0 10px rgba(46, 160, 67, 0); }
            100% { box-shadow: 0 0 0 0 rgba(46, 160, 67, 0); }
        }
    </style>
</head>
<body>
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 2rem;">
        <h1 style="margin-bottom: 0;"><span class="pulse"></span> Asomien Command Center</h1>
        <button hx-post="/publish_now" hx-swap="none" onclick="this.innerText='Publishing...'; setTimeout(() => this.innerText='Instant Publish', 5000);" style="background: linear-gradient(90deg, var(--accent-primary), var(--accent-secondary)); color: white; border: none; padding: 12px 24px; border-radius: 8px; font-weight: 600; cursor: pointer; font-family: 'Outfit', sans-serif; font-size: 1rem; box-shadow: 0 4px 15px rgba(138, 43, 226, 0.4); transition: opacity 0.2s;" onmouseover="this.style.opacity=0.9" onmouseout="this.style.opacity=1">Instant Publish</button>
    </div>
    <div class="grid">
        <div class="left-col" style="display: flex; flex-direction: column; gap: 2rem; height: 100%;">
            <div class="panel" style="flex: 1;" id="status-panel" hx-get="/status" hx-trigger="load, every 5s">Loading Status...</div>
            <div class="panel" style="flex: 1.5;" id="personality-panel" hx-get="/personality" hx-trigger="load, every 10s">Loading Personality...</div>
        </div>
        <div class="right-col" style="display: flex; flex-direction: column; gap: 2rem; height: 100%;">
            <div class="panel" style="flex: 1.5;" id="memory-panel" hx-get="/memory" hx-trigger="load, every 10s">Loading Memory...</div>
            <div class="panel" style="flex: 1;" id="log-panel" hx-get="/logs" hx-trigger="load, every 2s">Loading Logs...</div>
        </div>
    </div>
</body>
</html>
"""

def create_app(orchestrator):
    app = FastAPI(title="Asomien Observability Dashboard")
    app.state.orchestrator = orchestrator

    @app.get("/", response_class=HTMLResponse)
    def index():
        return INDEX_HTML

    @app.post("/publish_now")
    def publish_now():
        """Instantly trigger a publish cycle."""
        import threading
        threading.Thread(target=app.state.orchestrator.run_publish_cycle, daemon=True).start()
        return {"status": "Publish cycle triggered"}

    @app.get("/status")
    def status(request: Request):
        """Returns JSON by default, or HTML partial if requested via HTMX."""
        is_warmup = orchestrator.is_warmup_phase()
        system_state = orchestrator.get_system_state()
        
        reflections = []
        if orchestrator.memory:
            try:
                with sqlite3.connect(orchestrator.memory.db_path) as conn:
                    cursor = conn.execute("SELECT rule_text, created_at FROM rules ORDER BY created_at DESC LIMIT 5")
                    reflections = [{"rule": row[0], "created_at": row[1]} for row in cursor.fetchall()]
            except Exception as e:
                reflections = [{"error": str(e)}]
                
        # If HTMX request, return HTML partial
        if "hx-request" in request.headers:
            html = "<h2>System Status</h2>"
            html += f"<div><strong>Warmup Phase:</strong> {is_warmup}</div>"
            metrics = system_state.get("metrics")
            if metrics:
                html += f"<div><strong>Metrics:</strong> {metrics}</div>"
            else:
                html += "<div><strong>Metrics:</strong> Pending...</div>"
            
            html += "<h3 style='color: #fff;'>Last 5 Reflections</h3><ul>"
            if not reflections:
                html += "<li>No reflections yet.</li>"
            for ref in reflections:
                if "error" in ref:
                    html += f"<li>Error: {ref['error']}</li>"
                else:
                    html += f"<li>[{ref['created_at']}] {ref['rule']}</li>"
            html += "</ul>"
            return HTMLResponse(content=html)

        return {
            "warmup_phase": is_warmup,
            "metrics": system_state.get("metrics"),
            "last_5_reflection_nodes": reflections
        }

    @app.get("/personality", response_class=HTMLResponse)
    def personality():
        """Returns HTML partial of Personality."""
        state = orchestrator.get_system_state()
        traits = state.get("personality_traits", {})
        
        rules = []
        if orchestrator.memory:
            try:
                with sqlite3.connect(orchestrator.memory.db_path) as conn:
                    cursor = conn.execute("SELECT rule_text, confidence FROM rules WHERE is_active=1 ORDER BY confidence DESC")
                    rules = cursor.fetchall()
            except Exception:
                pass

        html = "<h2>Personality Traits</h2><ul>"
        if not traits:
            html += "<li>No traits computed yet.</li>"
        for t, v in traits.items():
            html += f"<li><strong>{t}</strong>: {v:.4f}</li>"
        html += "</ul>"
        
        html += "<h2>Active Persona Rules</h2>"
        if not rules:
            html += "<p>No active persona rules yet.</p>"
        else:
            html += "<table><tr><th>Rule</th><th>Confidence</th></tr>"
            for r, c in rules:
                html += f"<tr><td>{r}</td><td>{c:.4f}</td></tr>"
            html += "</table>"
        
        return html

    @app.get("/memory", response_class=HTMLResponse)
    def memory():
        """Returns HTML partial of Memory."""
        nodes = []
        if orchestrator.memory:
            try:
                with sqlite3.connect(orchestrator.memory.db_path) as conn:
                    cursor = conn.execute("SELECT source, headline, summary, discovered_at FROM research_nodes ORDER BY discovered_at DESC LIMIT 20")
                    nodes = cursor.fetchall()
            except Exception:
                pass
                
        html = "<h2>Recent Research</h2><ul>"
        if not nodes:
            html += "<li>No research nodes yet.</li>"
        for source, headline, summary, dt in nodes:
            html += f"<li><strong>[{dt}] [{source}] {headline}</strong>: {summary}</li>"
        html += "</ul>"
        
        return html

    @app.get("/logs", response_class=HTMLResponse)
    def logs():
        """Returns the last 20 lines of the action log."""
        log_path = "logs/actions.log"
        lines = []
        if os.path.exists(log_path):
            try:
                with open(log_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()[-20:]
            except Exception as e:
                lines = [f"Error reading logs: {e}"]
        else:
            lines = ["Log file not found."]

        html = "<h2>System Log Stream</h2><ul>"
        for line in lines:
            html += f"<li>{line.strip()}</li>"
        html += "</ul>"
        
        return html

    return app

def start_server(orchestrator):
    import uvicorn
    app = create_app(orchestrator)
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="error")
