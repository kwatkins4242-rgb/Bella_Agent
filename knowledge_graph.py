"""
ODIN Knowledge Graph — Layer 3
NetworkX-backed, atomic-save graph for entity relationships
(e.g. "daughter" --name_is--> "Emma", "Watkins Construction" --is_a--> "business").
"""
from __future__ import annotations
import sys
import json
import logging
from pathlib import Path
from datetime import datetime, timezone
import networkx as nx
from typing import Optional, List, Dict, Any

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from settings import get_settings

settings = get_settings()
GRAPH_FILE = settings.graph_file
logger = logging.getLogger("odin.graph")


class KnowledgeGraph:
    def __init__(self) -> None:
        self.graph: nx.DiGraph = nx.DiGraph()
        self._ensure_file()
        self._load()

    # ---------- persistence ----------
    def _ensure_file(self) -> None:
        GRAPH_FILE.parent.mkdir(parents=True, exist_ok=True)
        if not GRAPH_FILE.exists():
            self._save()

    def _load(self) -> None:
        try:
            with GRAPH_FILE.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.error("graph load failed: %s", e)
            return

        self.graph.clear()
        for node in data.get("nodes", []):
            node = dict(node)
            nid = node.pop("id")
            self.graph.add_node(nid, **node)
        for edge in data.get("edges", []):
            self.graph.add_edge(
                edge["source"], edge["target"],
                relation=edge.get("relation", "related_to"),
                weight=edge.get("weight", 1.0),
                created_at=edge.get("created_at", ""),
            )

    def _save(self) -> None:
        data = {
            "version": "1.0",
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "nodes": [{"id": n, **self.graph.nodes[n]} for n in self.graph.nodes],
            "edges": [
                {"source": u, "target": v, **self.graph.edges[u, v]}
                for u, v in self.graph.edges
            ],
        }
        tmp = GRAPH_FILE.with_suffix(".tmp")
        try:
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            tmp.replace(GRAPH_FILE)
        except OSError as e:
            logger.exception("graph save failed: %s", e)

    # ---------- public API ----------
    def add_node(self, node_id: str, **attrs) -> None:
        self.graph.add_node(node_id, **attrs)
        self._save()

    def add_edge(self, source: str, target: str, relation: str = "related_to",
                 weight: float = 1.0) -> None:
        if source not in self.graph:
            self.graph.add_node(source)
        if target not in self.graph:
            self.graph.add_node(target)
        self.graph.add_edge(
            source, target,
            relation=relation, weight=weight,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self._save()

    def remove_node(self, node_id: str) -> bool:
        if node_id in self.graph:
            self.graph.remove_node(node_id)
            self._save()
            return True
        return False

    def get_neighbors(self, node_id: str) -> List[Dict[str, Any]]:
        if node_id not in self.graph:
            return []
        results = []
        for target in self.graph.successors(node_id):
            edge = self.graph.edges[node_id, target]
            results.append({"target": target, "relation": edge.get("relation"), **self.graph.nodes[target]})
        for source in self.graph.predecessors(node_id):
            edge = self.graph.edges[source, node_id]
            results.append({"source": source, "relation": edge.get("relation"), **self.graph.nodes[source]})
        return results

    def query(self, q: str) -> Dict[str, Any]:
        """Substring search across node ids and node attributes."""
        q_lower = q.lower()
        matches = {}
        for n in self.graph.nodes:
            attrs = self.graph.nodes[n]
            if q_lower in n.lower() or q_lower in json.dumps(attrs).lower():
                matches[n] = {"attrs": attrs, "neighbors": self.get_neighbors(n)}
        return matches

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nodes": [{"id": n, **self.graph.nodes[n]} for n in self.graph.nodes],
            "edges": [
                {"source": u, "target": v, **self.graph.edges[u, v]}
                for u, v in self.graph.edges
            ],
        }

    def node_count(self) -> int:
        return self.graph.number_of_nodes()

    def edge_count(self) -> int:
        return self.graph.number_of_edges()
