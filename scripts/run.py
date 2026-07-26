import morph_kgc

graph = morph_kgc.materialize("config/config.ini")

graph.serialize(
    destination="output/kg.ttl",
    format="turtle"
)