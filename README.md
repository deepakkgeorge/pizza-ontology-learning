# Pizza Ontology Learning

Learning ontology engineering using the Pizza Ontology.

Topics to explore:
- OWL
- RDF
- Protégé
- Reasoning
- SPARQL

## GraphDB upload

Repository config is in `gene-kg-config.ttl` for repository `gene-kg`.

Named graph strategy:
- Ontology: `http://example.org/graph/ontology`
- Instances: `http://example.org/graph/instances`
- SHACL: `http://example.org/graph/shacl`
- Pipeline metadata: `http://example.org/graph/metadata`

Run the upload pipeline after GraphDB is running at `http://localhost:7200` and
the `gene-kg` repository exists:

```bash
python3 scripts/graph-db-post.py
```

The pipeline skips ontology upload when `Ontology/gene-practice.owl` has the same
SHA-256 hash as the value stored in the metadata graph. The instance graph is
deleted and uploaded every run. Logs are written to `logs/graphdb-upload.log`.

More detail is in `docs/named-graph-strategy.md`. The named-graph metadata SHACL
policy is in `shacl/named-graph-shapes.ttl`.
