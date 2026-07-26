from __future__ import annotations

import argparse
import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]

GRAPHDB = "http://localhost:7200"
REPOSITORY = "gene-kg"

ONTOLOGY_GRAPH = "http://example.org/graph/ontology"
INSTANCE_GRAPH = "http://example.org/graph/instances"
SHACL_GRAPH = "http://example.org/graph/shacl"
METADATA_GRAPH = "http://example.org/graph/metadata"

PIPELINE = "http://example.org/graph/pipeline#"

ONTOLOGY_PATH = ROOT / "Ontology" / "gene-practice.owl"
INSTANCE_PATH = ROOT / "output" / "kg.ttl"
SHACL_PATH = ROOT / "shacl" / "shapes.ttl"
NAMED_GRAPH_SHACL_PATH = ROOT / "shacl" / "named-graph-shapes.ttl"
LOG_PATH = ROOT / "logs" / "graphdb-upload.log"


def configure_logging() -> logging.Logger:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("graphdb-upload")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    file_handler = logging.FileHandler(LOG_PATH)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


LOGGER = configure_logging()


class GraphDBError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_files(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.relative_to(ROOT).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def statements_url(graphdb: str, repository: str, graph_iri: str | None = None) -> str:
    base = f"{graphdb.rstrip('/')}/repositories/{repository}/statements"
    if graph_iri is None:
        return base
    return f"{base}?context={quote(f'<{graph_iri}>', safe='')}"


def repository_url(graphdb: str, repository: str) -> str:
    return f"{graphdb.rstrip('/')}/repositories/{repository}"


def http_request(
    method: str,
    url: str,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> bytes:
    request = Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urlopen(request, timeout=60) as response:
            return response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise GraphDBError(f"GraphDB HTTP {exc.code} for {method} {url}: {detail}") from exc
    except URLError as exc:
        raise GraphDBError(f"Could not connect to GraphDB at {url}: {exc.reason}") from exc


def sparql_query(graphdb: str, repository: str, query: str) -> dict[str, Any]:
    data = urlencode({"query": query}).encode("utf-8")
    body = http_request(
        "POST",
        repository_url(graphdb, repository),
        data=data,
        headers={
            "Accept": "application/sparql-results+json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    return json.loads(body.decode("utf-8"))


def sparql_update(graphdb: str, repository: str, update: str) -> None:
    data = urlencode({"update": update}).encode("utf-8")
    http_request(
        "POST",
        statements_url(graphdb, repository),
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )


def delete_graph(graphdb: str, repository: str, graph_iri: str) -> None:
    http_request("DELETE", statements_url(graphdb, repository, graph_iri))


def upload_turtle_graph(graphdb: str, repository: str, graph_iri: str, path: Path) -> None:
    http_request(
        "PUT",
        statements_url(graphdb, repository, graph_iri),
        data=path.read_bytes(),
        headers={"Content-Type": "text/turtle"},
    )


def append_turtle_graph(graphdb: str, repository: str, graph_iri: str, path: Path) -> None:
    http_request(
        "POST",
        statements_url(graphdb, repository, graph_iri),
        data=path.read_bytes(),
        headers={"Content-Type": "text/turtle"},
    )


def replace_turtle_graph_from_files(
    graphdb: str,
    repository: str,
    graph_iri: str,
    paths: list[Path],
) -> None:
    delete_graph(graphdb, repository, graph_iri)
    upload_turtle_graph(graphdb, repository, graph_iri, paths[0])
    for path in paths[1:]:
        append_turtle_graph(graphdb, repository, graph_iri, path)


def count_graph_triples(graphdb: str, repository: str, graph_iri: str) -> int:
    result = sparql_query(
        graphdb,
        repository,
        f"""
        SELECT (COUNT(*) AS ?triples)
        WHERE {{
            GRAPH <{graph_iri}> {{ ?s ?p ?o }}
        }}
        """,
    )
    value = result["results"]["bindings"][0]["triples"]["value"]
    return int(value)


def remote_ontology_hash(graphdb: str, repository: str) -> str | None:
    result = sparql_query(
        graphdb,
        repository,
        f"""
        PREFIX pipeline: <{PIPELINE}>

        SELECT ?hash
        WHERE {{
            GRAPH <{METADATA_GRAPH}> {{
                <{ONTOLOGY_GRAPH}> pipeline:sha256 ?hash .
            }}
        }}
        LIMIT 1
        """,
    )
    bindings = result["results"]["bindings"]
    if not bindings:
        return None
    return bindings[0]["hash"]["value"]


def upsert_graph_metadata(
    graphdb: str,
    repository: str,
    graph_iri: str,
    role: str,
    source_path: str,
    file_hash: str,
    triple_count: int,
) -> None:
    uploaded_at = datetime.now(timezone.utc).isoformat()
    update = f"""
    PREFIX pipeline: <{PIPELINE}>
    PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

    DELETE {{
        GRAPH <{METADATA_GRAPH}> {{
            <{graph_iri}> ?p ?o .
        }}
    }}
    INSERT {{
        GRAPH <{METADATA_GRAPH}> {{
            <{graph_iri}> a pipeline:NamedGraph ;
                pipeline:role "{role}" ;
                pipeline:filePath "{source_path}" ;
                pipeline:sha256 "{file_hash}" ;
                pipeline:lastUploadedAt "{uploaded_at}"^^xsd:dateTime ;
                pipeline:tripleCount "{triple_count}"^^xsd:integer .
        }}
    }}
    WHERE {{
        OPTIONAL {{
            GRAPH <{METADATA_GRAPH}> {{
                <{graph_iri}> ?p ?o .
            }}
        }}
    }}
    """
    sparql_update(graphdb, repository, update)


def ensure_file(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Required file not found: {path}")
    if path.stat().st_size == 0:
        raise ValueError(f"Required file is empty: {path}")


def run_pipeline(graphdb: str, repository: str, upload_shacl: bool) -> None:
    ensure_file(ONTOLOGY_PATH)
    ensure_file(INSTANCE_PATH)
    if upload_shacl:
        ensure_file(SHACL_PATH)
        ensure_file(NAMED_GRAPH_SHACL_PATH)

    ontology_hash = sha256_file(ONTOLOGY_PATH)
    instance_hash = sha256_file(INSTANCE_PATH)

    LOGGER.info("GraphDB server: %s", graphdb)
    LOGGER.info("Repository: %s", repository)
    LOGGER.info("Named graph strategy: ontology=%s", ONTOLOGY_GRAPH)
    LOGGER.info("Named graph strategy: instances=%s", INSTANCE_GRAPH)
    LOGGER.info("Named graph strategy: shacl=%s", SHACL_GRAPH)
    LOGGER.info("Named graph strategy: metadata=%s", METADATA_GRAPH)

    previous_hash = remote_ontology_hash(graphdb, repository)
    ontology_changed = previous_hash != ontology_hash

    if ontology_changed:
        LOGGER.info("Ontology changed: yes")
        LOGGER.info("Ontology upload included")
        delete_graph(graphdb, repository, ONTOLOGY_GRAPH)
        LOGGER.info("Old ontology graph deleted")
        upload_turtle_graph(graphdb, repository, ONTOLOGY_GRAPH, ONTOLOGY_PATH)
        LOGGER.info("New ontology graph uploaded")
    else:
        LOGGER.info("Ontology changed: no")
        LOGGER.info("Ontology upload skipped")

    LOGGER.info("Deleting old instance graph")
    delete_graph(graphdb, repository, INSTANCE_GRAPH)
    LOGGER.info("Old instance graph deleted")
    upload_turtle_graph(graphdb, repository, INSTANCE_GRAPH, INSTANCE_PATH)
    LOGGER.info("New instance graph uploaded")

    if upload_shacl:
        shacl_paths = [SHACL_PATH, NAMED_GRAPH_SHACL_PATH]
        shacl_hash = sha256_files(shacl_paths)
        shacl_source_paths = ",".join(path.relative_to(ROOT).as_posix() for path in shacl_paths)
        LOGGER.info("Replacing SHACL graph")
        replace_turtle_graph_from_files(graphdb, repository, SHACL_GRAPH, shacl_paths)
        LOGGER.info("New SHACL graph uploaded")
        shacl_triples = count_graph_triples(graphdb, repository, SHACL_GRAPH)
        upsert_graph_metadata(
            graphdb,
            repository,
            SHACL_GRAPH,
            "shacl",
            shacl_source_paths,
            shacl_hash,
            shacl_triples,
        )
        LOGGER.info("SHACL graph triple number: %s", shacl_triples)

    ontology_triples = count_graph_triples(graphdb, repository, ONTOLOGY_GRAPH)
    instance_triples = count_graph_triples(graphdb, repository, INSTANCE_GRAPH)

    upsert_graph_metadata(
        graphdb,
        repository,
        ONTOLOGY_GRAPH,
        "ontology",
        ONTOLOGY_PATH.relative_to(ROOT).as_posix(),
        ontology_hash,
        ontology_triples,
    )
    upsert_graph_metadata(
        graphdb,
        repository,
        INSTANCE_GRAPH,
        "instances",
        INSTANCE_PATH.relative_to(ROOT).as_posix(),
        instance_hash,
        instance_triples,
    )

    LOGGER.info("Ontology graph triple number: %s", ontology_triples)
    LOGGER.info("Instance graph triple number: %s", instance_triples)
    LOGGER.info("Upload verification succeeded")
    LOGGER.info("Pipeline completed")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replace GraphDB named graphs for the gene KG pipeline."
    )
    parser.add_argument("--graphdb", default=GRAPHDB, help=f"GraphDB URL. Default: {GRAPHDB}")
    parser.add_argument(
        "--repository",
        default=REPOSITORY,
        help=f"GraphDB repository ID. Default: {REPOSITORY}",
    )
    parser.add_argument(
        "--skip-shacl-upload",
        action="store_true",
        help="Do not replace the SHACL named graph.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        run_pipeline(
            graphdb=args.graphdb,
            repository=args.repository,
            upload_shacl=not args.skip_shacl_upload,
        )
        return 0
    except Exception as exc:
        LOGGER.exception("Pipeline failed: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
