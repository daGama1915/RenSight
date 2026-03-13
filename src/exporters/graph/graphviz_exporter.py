"""
exporters/graph/graphviz_exporter.py
--------------------------------------
Exports a NarrativeGraph to multiple formats:

  DOT  — pure-Python, no dependencies
  PNG  — calls ``dot`` directly via subprocess  (no Python graphviz package needed)
  SVG  — calls ``dot`` directly via subprocess
  HTML — self-contained interactive vis.js network  (no binary needed at all)

PNG/SVG requirements: Graphviz system binaries must be installed.
  Ubuntu/Debian : sudo apt install graphviz
  Fedora/RHEL   : sudo dnf install graphviz
  macOS Homebrew: brew install graphviz
  Windows       : https://graphviz.org/download/
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from typing import Optional

from ir.narrative_graph import NarrativeGraph

logger = logging.getLogger(__name__)

_GRAPHVIZ_SEARCH_PATHS = [
    "/usr/bin", "/usr/local/bin", "/snap/bin",
    "/usr/local/opt/graphviz/bin",
    "/opt/homebrew/bin", "/opt/homebrew/opt/graphviz/bin",
    os.path.expanduser("~/anaconda3/bin"),
    os.path.expanduser("~/miniconda3/bin"),
    os.path.expanduser("~/mambaforge/bin"),
    r"C:\Program Files\Graphviz\bin",
    r"C:\Program Files (x86)\Graphviz\bin",
]


def _find_dot_binary() -> Optional[str]:
    """Return full path to ``dot`` or None if not found."""
    found = shutil.which("dot")
    if found:
        return found
    for directory in _GRAPHVIZ_SEARCH_PATHS:
        for name in ("dot", "dot.exe"):
            candidate = os.path.join(directory, name)
            if os.path.isfile(candidate):
                return candidate
    return None


# ── DOT ───────────────────────────────────────────────────────────────────────

def export_dot(
    graph: NarrativeGraph,
    output_dir: str,
    filename: str = "narrative_graph.dot",
) -> str:
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, filename)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(graph.to_dot())
    logger.info("DOT written to '%s'.", out_path)
    return out_path


# ── PNG / SVG via subprocess ───────────────────────────────────────────────────

def export_png(
    graph: NarrativeGraph,
    output_dir: str,
    filename: str = "narrative_graph",
) -> Optional[str]:
    return _render_via_subprocess(graph, output_dir, filename, fmt="png")


def export_svg(
    graph: NarrativeGraph,
    output_dir: str,
    filename: str = "narrative_graph",
) -> Optional[str]:
    return _render_via_subprocess(graph, output_dir, filename, fmt="svg")


def _render_via_subprocess(
    graph: NarrativeGraph,
    output_dir: str,
    filename: str,
    fmt: str,
) -> Optional[str]:
    """
    Call ``dot`` directly via subprocess — completely bypasses the
    graphviz Python package so PATH issues with that package can't interfere.
    """
    dot_bin = _find_dot_binary()
    if dot_bin is None:
        logger.warning(
            "Graphviz 'dot' binary not found.\n"
            "  Ubuntu/Debian : sudo apt install graphviz\n"
            "  macOS Homebrew: brew install graphviz\n"
            "  Windows       : https://graphviz.org/download/"
        )
        return None

    os.makedirs(output_dir, exist_ok=True)
    tmp_dot  = os.path.join(output_dir, f"_tmp_{filename}.dot")
    out_path = os.path.join(output_dir, f"{filename}.{fmt}")

    try:
        with open(tmp_dot, "w", encoding="utf-8") as fh:
            fh.write(graph.to_dot())

        env = os.environ.copy()
        bin_dir = os.path.dirname(dot_bin)
        if bin_dir and bin_dir not in env.get("PATH", ""):
            env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")

        result = subprocess.run(
            [dot_bin, f"-T{fmt}", tmp_dot, "-o", out_path],
            capture_output=True, text=True, env=env, timeout=120,
        )
        if result.returncode == 0:
            logger.info("Graph %s written to '%s'.", fmt.upper(), out_path)
            return out_path
        logger.warning("dot exited %d: %s", result.returncode, result.stderr.strip())
        return None

    except subprocess.TimeoutExpired:
        logger.warning("dot timed out (graph may be too large for image export).")
        return None
    except Exception as exc:
        logger.warning("dot render failed: %s", exc)
        return None
    finally:
        try:
            os.remove(tmp_dot)
        except OSError:
            pass


# ── Interactive HTML ───────────────────────────────────────────────────────────

def export_html_interactive(
    graph: NarrativeGraph,
    output_dir: str,
    filename: str = "narrative_graph_interactive.html",
) -> str:
    """
    Export a self-contained interactive HTML network built with vis.js.

    Features
    --------
    - Pan, zoom, drag nodes
    - Click a node → highlight its neighbours; click canvas → restore
    - Toggle edge types (jump / call / sequential) on/off
    - Search bar highlights matching labels
    - Colour-coded nodes (entry, menu, plain) and edges
    - Stats bar, fit-view and freeze-layout buttons
    - Tooltip shows file, line and menu IDs on hover
    - Requires internet to load vis.js from CDN on first open
    """
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, filename)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(_build_html(graph))
    logger.info("Interactive HTML graph written to '%s'.", out_path)
    return out_path


def _build_html(graph: NarrativeGraph) -> str:  # noqa: C901
    EDGE_COLORS = {
        "jump":       "#1a1a1a",
        "call":       "#2563eb",
        "sequential": "#9ca3af",
        "choice":     "#dc2626",
    }
    NODE_COLOR = {
        "entry": {"bg": "#bbf7d0", "border": "#16a34a"},
        "menu":  {"bg": "#fde68a", "border": "#d97706"},
        "plain": {"bg": "#e0e7ff", "border": "#6366f1"},
    }

    vis_nodes = []
    for nid, attrs in graph.G.nodes(data=True):
        has_menu = bool(attrs.get("menu_ids"))
        is_entry = attrs.get("is_entry", False) or nid == "start"
        key      = "entry" if is_entry else ("menu" if has_menu else "plain")
        shape    = "star" if is_entry else ("box" if has_menu else "ellipse")
        col      = NODE_COLOR[key]

        tip_parts = [nid]
        if attrs.get("file"):
            tip_parts.append(f"File: {attrs['file']} (line {attrs.get('line',0)})")
        if attrs.get("menu_ids"):
            tip_parts.append("Menus: " + ", ".join(attrs["menu_ids"]))

        vis_nodes.append({
            "id": nid, "label": nid, "shape": shape,
            "color": {"background": col["bg"], "border": col["border"],
                      "highlight": {"background": col["bg"], "border": "#000"}},
            "title": "<br>".join(tip_parts),
            "font":  {"size": 11},
        })

    vis_edges = []
    for i, (src, dst, attrs) in enumerate(graph.G.edges(data=True)):
        etype = attrs.get("edge_type", "sequential")
        tip   = etype + (f": {attrs['choice_text']}" if attrs.get("choice_text") else "")
        vis_edges.append({
            "id": i, "from": src, "to": dst,
            "color": {"color": EDGE_COLORS.get(etype, "#9ca3af"),
                      "highlight": "#f59e0b"},
            "title": tip, "arrows": "to", "edge_type": etype,
        })

    n_nodes = graph.label_count
    n_edges = graph.edge_count
    n_menus = len(graph.labels_with_menus())
    n_jump  = sum(1 for *_, a in graph.G.edges(data=True) if a.get("edge_type") == "jump")
    n_call  = sum(1 for *_, a in graph.G.edges(data=True) if a.get("edge_type") == "call")
    n_seq   = sum(1 for *_, a in graph.G.edges(data=True) if a.get("edge_type") == "sequential")

    nodes_json = json.dumps(vis_nodes, ensure_ascii=False)
    edges_json = json.dumps(vis_edges, ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Narrative Graph — Interactive</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/vis/4.21.0/vis.min.js"></script>
<link  href="https://cdnjs.cloudflare.com/ajax/libs/vis/4.21.0/vis.min.css" rel="stylesheet">
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
      background:#0f172a;color:#e2e8f0;height:100vh;
      display:flex;flex-direction:column;overflow:hidden}}
#topbar{{display:flex;align-items:center;gap:10px;padding:7px 12px;
         background:#1e293b;border-bottom:1px solid #334155;
         flex-shrink:0;flex-wrap:wrap}}
#topbar h1{{font-size:14px;font-weight:600;color:#f1f5f9;margin-right:4px;white-space:nowrap}}
.chip{{background:#334155;border-radius:10px;padding:2px 9px;
       font-size:11px;color:#94a3b8;white-space:nowrap}}
.chip b{{color:#e2e8f0}}
#search{{background:#334155;border:1px solid #475569;border-radius:6px;
         padding:4px 10px;color:#e2e8f0;font-size:12px;width:180px}}
#search::placeholder{{color:#64748b}}
.btn{{padding:3px 11px;border-radius:5px;border:1px solid #475569;
      background:#334155;color:#cbd5e1;font-size:11px;cursor:pointer;transition:background .15s;white-space:nowrap}}
.btn:hover{{background:#475569}}
.btn.on{{background:#4f46e5;border-color:#4f46e5;color:#fff}}
.legend{{display:flex;gap:8px;align-items:center;margin-left:auto;flex-wrap:wrap}}
.li{{display:flex;align-items:center;gap:4px;font-size:10px;color:#94a3b8;white-space:nowrap}}
.dot{{width:9px;height:9px;border-radius:50%;flex-shrink:0}}
.ln{{width:18px;height:2px;flex-shrink:0}}
#canvas{{flex:1}}
#info{{position:absolute;right:12px;top:64px;background:#1e293b;border:1px solid #334155;
       border-radius:8px;padding:10px 13px;width:240px;font-size:11px;line-height:1.65;
       display:none;z-index:10;max-height:60vh;overflow-y:auto}}
#info h2{{font-size:12px;color:#f1f5f9;margin-bottom:5px;word-break:break-all}}
.kv{{display:flex;justify-content:space-between;gap:6px}}
.kv span:first-child{{color:#94a3b8}}
.kv span:last-child{{color:#e2e8f0;font-weight:500;word-break:break-all;text-align:right}}
#statusbar{{padding:3px 12px;background:#1e293b;border-top:1px solid #334155;
            font-size:10px;color:#64748b;flex-shrink:0}}
</style>
</head>
<body>
<div id="topbar">
  <h1>Narrative Graph</h1>
  <span class="chip">Nodes <b>{n_nodes}</b></span>
  <span class="chip">Edges <b>{n_edges}</b></span>
  <span class="chip">Menus <b>{n_menus}</b></span>
  <span class="chip">Jumps <b>{n_jump}</b></span>
  <span class="chip">Calls <b>{n_call}</b></span>
  <span class="chip">Sequential <b>{n_seq}</b></span>
  <input id="search" type="text" placeholder="Search label…" oninput="doSearch(this.value)">
  <button class="btn on"  id="b-seq"  onclick="toggleType('sequential',this)">Sequential</button>
  <button class="btn on"  id="b-jump" onclick="toggleType('jump',this)">Jumps</button>
  <button class="btn on"  id="b-call" onclick="toggleType('call',this)">Calls</button>
  <button class="btn"     id="b-fit"  onclick="net.fit()">Fit view</button>
  <button class="btn"     id="b-phys" onclick="togglePhysics(this)">Unfreeze</button>
  <div class="legend">
    <div class="li"><div class="dot" style="background:#fde68a;border:1.5px solid #d97706"></div>Has menu</div>
    <div class="li"><div class="dot" style="background:#bbf7d0;border:1.5px solid #16a34a"></div>Entry</div>
    <div class="li"><div class="dot" style="background:#e0e7ff;border:1.5px solid #6366f1"></div>Label</div>
    <div class="li"><div class="ln" style="background:#1a1a1a"></div>Jump</div>
    <div class="li"><div class="ln" style="background:#2563eb"></div>Call</div>
    <div class="li"><div class="ln" style="background:#9ca3af"></div>Sequential</div>
  </div>
</div>
<div id="canvas"></div>
<div id="info"><h2 id="info-title"></h2><div id="info-body"></div></div>
<div id="statusbar">Loading…</div>
<script>
const NODES=new vis.DataSet({nodes_json});
const EDGES=new vis.DataSet({edges_json});
const hidden=new Set();
const net=new vis.Network(
  document.getElementById("canvas"),
  {{nodes:NODES,edges:EDGES}},
  {{
    nodes:{{borderWidth:1.5}},
    edges:{{smooth:{{type:"dynamic"}},width:1.3,selectionWidth:2.5}},
    physics:{{
      enabled:true,solver:"forceAtlas2Based",
      forceAtlas2Based:{{gravitationalConstant:-80,centralGravity:0.008,
                          springLength:120,springConstant:0.06,damping:0.5}},
      stabilization:{{iterations:250,fit:true}}
    }},
    interaction:{{hover:true,tooltipDelay:120,keyboard:true,zoomView:true}}
  }}
);
const sb=document.getElementById("statusbar");
net.on("stabilizationProgress",p=>{{sb.textContent="Stabilising… "+Math.round(p.iterations/p.total*100)+"%"}});
net.on("stabilizationIterationsDone",()=>{{
  sb.textContent="Ready — {n_nodes} nodes · {n_edges} edges";
  net.setOptions({{physics:{{enabled:false}}}});
}});
net.on("click",p=>{{
  const panel=document.getElementById("info");
  if(!p.nodes.length){{
    NODES.update(NODES.get().map(n=>({{id:n.id,opacity:1}})));
    EDGES.update(EDGES.get().map(e=>({{id:e.id,hidden:hidden.has(e.edge_type)}})));
    panel.style.display="none"; return;
  }}
  const nid=p.nodes[0];
  const cEdges=net.getConnectedEdges(nid);
  const cNodes=new Set(net.getConnectedNodes(nid)); cNodes.add(nid);
  NODES.update(NODES.get().map(n=>({{id:n.id,opacity:cNodes.has(n.id)?1:0.12}})));
  EDGES.update(EDGES.get().map(e=>({{id:e.id,hidden:hidden.has(e.edge_type)?true:!cEdges.includes(e.id)}})));
  const succ=net.getConnectedNodes(nid,"to");
  const pred=net.getConnectedNodes(nid,"from");
  const raw=NODES.get(nid);
  document.getElementById("info-title").textContent=nid;
  document.getElementById("info-body").innerHTML=
    `<div class="kv"><span>Successors</span><span>${{succ.length}}</span></div>`+
    `<div class="kv"><span>Predecessors</span><span>${{pred.length}}</span></div>`+
    (raw.title?`<div style="margin-top:6px;color:#94a3b8;font-size:10px">${{raw.title}}</div>`:"");
  panel.style.display="block";
}});
function toggleType(type,btn){{
  if(hidden.has(type)){{
    hidden.delete(type); btn.classList.add("on");
    EDGES.update(EDGES.get().filter(e=>e.edge_type===type).map(e=>({{id:e.id,hidden:false}})));
  }}else{{
    hidden.add(type); btn.classList.remove("on");
    EDGES.update(EDGES.get().filter(e=>e.edge_type===type).map(e=>({{id:e.id,hidden:true}})));
  }}
}}
function doSearch(q){{
  if(!q){{NODES.update(NODES.get().map(n=>({{id:n.id,opacity:1}}))); sb.textContent="Ready"; return;}}
  const lq=q.toLowerCase();
  const hits=NODES.get().filter(n=>n.id.toLowerCase().includes(lq));
  NODES.update(NODES.get().map(n=>({{id:n.id,opacity:n.id.toLowerCase().includes(lq)?1:0.08}})));
  sb.textContent=hits.length+" match(es) for \\""+q+"\\"";
  if(hits.length===1) net.focus(hits[0].id,{{scale:1.8,animation:true}});
}}
let physOn=false;
function togglePhysics(btn){{
  physOn=!physOn;
  net.setOptions({{physics:{{enabled:physOn}}}});
  btn.textContent=physOn?"Freeze":"Unfreeze";
  btn.classList.toggle("on",physOn);
}}
</script>
</body>
</html>"""
