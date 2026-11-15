"""Load a world into HydraDB and answer with algo.SSpaths.

Edge property ``cost`` is the learned weight for that edge's current
(relation, source) pair. SSpaths minimizes the sum. The caller then keeps
the cheapest path that ends on a person, so a short expensive chain loses
to a longer cheap one.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from dreamgraph.config import SOURCES
from dreamgraph.hydra_client import (
    HttpTransport,
    HydraClient,
    build_ss_paths,
    cell_value,
)
from dreamgraph.search import Prediction
from dreamgraph.world import World


class HydraGraph:
    def __init__(self, base_url: str, token: str):
        self.client = HydraClient(HttpTransport(base_url, token))

    def load(self, world: World) -> None:
        """MERGE every edge, then SET source and cost so a re-load updates labels."""

        for edge in world.edges:
            self.client.query(
                "MERGE (a:Entity {id: $src})-[:OWNS {rel_id: $rel, hop: $hop, source: $source, cost: 1.0}]->(b:Entity {id: $dst})",
                {
                    "src": edge.src,
                    "dst": edge.dst,
                    "rel": edge.rel_id,
                    "hop": edge.hop,
                    "source": edge.source,
                },
            )
            self.client.query(
                "MATCH (a:Entity {id: $src})-[r:OWNS]->(b:Entity {id: $dst}) "
                "SET r.source = $source, r.cost = 1.0, r.rel_id = $rel, r.hop = $hop",
                {
                    "src": edge.src,
                    "dst": edge.dst,
                    "rel": edge.rel_id,
                    "hop": edge.hop,
                    "source": edge.source,
                },
            )

    def stamp_source_costs(self, costs: dict[str, float]) -> None:
        for source in SOURCES:
            self.client.query(
                "MATCH (a:Entity)-[r:OWNS]->(b:Entity) WHERE r.source = $source SET r.cost = $cost",
                {"source": source, "cost": round(float(costs[source]), 5)},
            )

    def swap_drift_labels(self, rel_ids: list[int]) -> None:
        for rel_id in rel_ids:
            self._relabel(rel_id, "wikidata", "wiki_tmp")
            self._relabel(rel_id, "scraper", "wikidata")
            self._relabel(rel_id, "wiki_tmp", "scraper")

    def _relabel(self, rel_id: int, old: str, new: str) -> None:
        self.client.query(
            "MATCH (a:Entity)-[r:OWNS]->(b:Entity) WHERE r.rel_id = $rel AND r.source = $old SET r.source = $new",
            {"rel": rel_id, "old": old, "new": new},
        )

    def owner(self, world: World, rel_id: int, costs: dict[str, float] | None) -> Prediction:
        """Min pathWeight among person-ending paths from this company's leaf.

        ``costs is None`` asks for the unweighted procedure. Otherwise the
        caller has already stamped ``costs`` onto matching source labels.
        """

        cypher, params = build_ss_paths(
            src=world.leaf[rel_id],
            weighted=costs is not None,
            total=8,
            max_len=3,
            rel_types=["OWNS"],
        )
        best: tuple[float, tuple[int, ...], tuple[str, ...]] | None = None
        for row in self.client.rows(cypher, params):
            path = row[0]
            if not isinstance(path, dict):
                continue
            nodes = tuple(int(node["id"]) for node in path["nodes"])
            if len(nodes) < 2 or nodes[-1] not in world.persons:
                continue
            weight = float(row[1])
            sources = tuple(rel["properties"].get("source", "") for rel in path["relationships"])
            key = (round(weight, 6), nodes)
            if best is None or key < (best[0], best[1]):
                best = (key[0], nodes, sources)
        if best is None:
            return Prediction(None, (world.leaf[rel_id],), (), float("inf"))
        return Prediction(best[1][-1], best[1], best[2], best[0])


def concurrent_latencies(base_url: str, token: str, src: int, rounds: int = 40, clients: int = 20) -> list[float]:
    """Milliseconds for ``clients`` workers each issuing ``rounds`` weighted searches."""

    cypher, params = build_ss_paths(src=src, weighted=True, total=8, max_len=3, rel_types=["OWNS"])

    def one_client(_: int) -> list[float]:
        client = HydraClient(HttpTransport(base_url, token))
        samples = []
        for _turn in range(rounds):
            import time

            started = time.perf_counter()
            client.query(cypher, params)
            samples.append((time.perf_counter() - started) * 1000.0)
        return samples

    samples: list[float] = []
    with ThreadPoolExecutor(max_workers=clients) as pool:
        futures = [pool.submit(one_client, index) for index in range(clients)]
        for future in as_completed(futures):
            samples.extend(future.result())
    return samples


def _weight_value(cell) -> float:
    value = cell_value(cell)
    return float(value)
