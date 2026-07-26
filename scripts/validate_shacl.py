from pathlib import Path
import sys

from rdflib import Graph

try:
    from pyshacl import validate
except ImportError:
    validate = None


ROOT = Path(__file__).resolve().parents[1]
DATA_GRAPH_PATH = ROOT / "output" / "kg.ttl"
SHAPES_GRAPH_PATH = ROOT / "shacl" / "shapes.ttl"
ONTOLOGY_GRAPH_PATH = ROOT / "Ontology" / "gene-practice.owl"


def parse_graph(path: Path, graph_name: str) -> Graph:
    graph = Graph()
    try:
        graph.parse(path, format="turtle")
    except Exception as exc:
        raise RuntimeError(f"Could not parse {graph_name} graph at {path}: {exc}") from exc
    return graph


def main() -> int:
    if validate is None:
        print(
            "pyshacl is not installed. Install it with: python3 -m pip install pyshacl",
            file=sys.stderr,
        )
        return 2

    data_graph = parse_graph(DATA_GRAPH_PATH, "data")
    shapes_graph = parse_graph(SHAPES_GRAPH_PATH, "shapes")
    ontology_graph = parse_graph(ONTOLOGY_GRAPH_PATH, "ontology")

    conforms, report_graph, report_text = validate(
        data_graph,
        shacl_graph=shapes_graph,
        ont_graph=ontology_graph,
        inference="rdfs",
        abort_on_first=False,
        allow_infos=True,
        allow_warnings=False,
        meta_shacl=False,
        advanced=False,
        debug=False,
    )

    report_path = ROOT / "shacl" / "validation-report.ttl"
    report_graph.serialize(destination=report_path, format="turtle")

    print(f"Conforms: {conforms}")
    print(f"Validation report written to: {report_path}")
    print()
    print(report_text)

    return 0 if conforms else 1


if __name__ == "__main__":
    raise SystemExit(main())
