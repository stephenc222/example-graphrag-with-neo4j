from graph_database import GraphDatabaseConnection
from py2neo import Node, Relationship
from logger import Logger
import re


class GraphManager:
    logger = Logger('GraphManager').get_logger()

    def __init__(self, db_connection=GraphDatabaseConnection()):
        # Clear the database for this example
        db_connection.clear_database()
        self.graph = db_connection.connect()

    def build_graph(self, summaries):
        if self.graph is None:
            self.logger.error("Graph database connection is not available.")
            return

        entities = {}

        for summary in summaries:
            lines = summary.split("\n")
            entities_section = False
            relationships_section = False

            for line in lines:
                if line.startswith("### Entities:") or line.startswith("**Entities:**") or line.startswith("Entities:"):
                    entities_section = True
                    relationships_section = False
                    continue
                elif line.startswith("### Relationships:") or line.startswith("**Relationships:**") or line.startswith("Relationships:"):
                    entities_section = False
                    relationships_section = True
                    continue

                if entities_section and line.strip():
                    if line[0].isdigit() and '.' in line:
                        entity_name = line.split(".", 1)[1].strip()
                    else:
                        entity_name = line.strip()
                    entity_name = self.normalize_entity_name(
                        entity_name.replace("**", ""))
                    node = Node("Entity", name=entity_name)
                    self.logger.debug(f"Creating node: {entity_name}")
                    self.graph.merge(node, "Entity", "name")
                    entities[entity_name] = node

                elif relationships_section and line.strip():
                    parts = line.split("->")
                    if len(parts) >= 2:
                        source = self.normalize_entity_name(parts[0].strip())
                        target = self.normalize_entity_name(parts[-1].strip())

                        relationship_part = parts[1].strip()
                        relation_name = self.sanitize_relationship_name(
                            relationship_part.split("[")[0].strip())
                        strength = re.search(
                            r"\[strength:\s*(\d\.\d)\]", relationship_part)
                        weight = float(strength.group(1)) if strength else 1.0

                        self.logger.debug(
                            f"Parsed relationship: {source} -> {relation_name} -> {target} [weight: {weight}]")
                        if source in entities and target in entities:
                            if relation_name:
                                self.logger.debug(
                                    f"Creating relationship: {source} -> {relation_name} -> {target} with weight {weight}")
                                relation = Relationship(
                                    entities[source], relation_name, entities[target])
                                relation["weight"] = weight
                                self.graph.merge(relation)
                            else:
                                self.logger.debug(
                                    f"Skipping relationship: {source} -> {relation_name} -> {target} (relation name is empty)")
                        else:
                            self.logger.debug(
                                f"Skipping relationship: {source} -> {relation_name} -> {target} (one or both entities not found)")

    def reproject_graph(self, graph_name="entityGraph"):
        self.drop_existing_projection(graph_name)
        self.verify_relationship_weights()

        self.graph.run(
            "MATCH (n:Entity) WHERE n.communityId IS NULL SET n.communityId = 0")

        relationship_types = self.get_relationship_types()
        if not relationship_types:
            self.logger.info("No relationships found to project.")
            return

        query = f"""
        CALL gds.graph.project(
            $graph_name,
            {{
                Entity: {{
                    label: 'Entity',
                    properties: ['communityId']
                }}
            }},
            {{
                {', '.join([f"{rel_type}: {{ type: '{rel_type}', orientation: 'UNDIRECTED', properties: {{ weight: {{ defaultValue: 1.0 }} }} }}" for rel_type in relationship_types])}
            }}
        )
        """
        try:
            self.graph.run(query, graph_name=graph_name)
            self.logger.debug(f"Graph re-projected successfully")
        except Exception as e:
            self.logger.error(f"Graph re-projection failed: {e}")

    def calculate_centrality_measures(self, graph_name="entityGraph"):
        self.reproject_graph(graph_name)

        check_query = f"CALL gds.graph.exists($graph_name) YIELD exists"
        exists_result = self.graph.run(
            check_query, graph_name=graph_name).evaluate()

        if not exists_result:
            raise Exception(f"Graph projection '{graph_name}' does not exist.")

        degree_centrality_query = f"""
        CALL gds.degree.stream($graph_name)
        YIELD nodeId, score
        RETURN gds.util.asNode(nodeId).name AS entityName, score
        ORDER BY score DESC
        LIMIT 10
        """
        degree_centrality_result = self.graph.run(
            degree_centrality_query, graph_name=graph_name).data()

        betweenness_centrality_query = f"""
        CALL gds.betweenness.stream($graph_name)
        YIELD nodeId, score
        RETURN gds.util.asNode(nodeId).name AS entityName, score
        ORDER BY score DESC
        LIMIT 10
        """
        betweenness_centrality_result = self.graph.run(
            betweenness_centrality_query, graph_name=graph_name).data()

        closeness_centrality_query = f"""
        CALL gds.closeness.stream($graph_name)
        YIELD nodeId, score
        RETURN gds.util.asNode(nodeId).name AS entityName, score
        ORDER BY score DESC
        LIMIT 10
        """
        closeness_centrality_result = self.graph.run(
            closeness_centrality_query, graph_name=graph_name).data()

        centrality_data = {
            "degree": degree_centrality_result,
            "betweenness": betweenness_centrality_result,
            "closeness": closeness_centrality_result
        }

        return centrality_data

    def summarize_centrality_measures(self, centrality_data):
        summary = "### Centrality Measures Summary:\n"

        summary += "#### Top Degree Centrality Nodes (most connected):\n"
        for record in centrality_data["degree"]:
            summary += f" - {record['entityName']} with score {record['score']}\n"

        summary += "\n#### Top Betweenness Centrality Nodes (influential intermediaries):\n"
        for record in centrality_data["betweenness"]:
            summary += f" - {record['entityName']} with score {record['score']}\n"

        summary += "\n#### Top Closeness Centrality Nodes (closest to all others):\n"
        for record in centrality_data["closeness"]:
            summary += f" - {record['entityName']} with score {record['score']}\n"

        return summary

    def drop_existing_projection(self, graph_name):
        drop_query = f"CALL gds.graph.exists('{graph_name}') YIELD exists"
        result = self.graph.run(drop_query).evaluate()
        if result:
            drop_query = f"CALL gds.graph.drop('{graph_name}')"
            self.graph.run(drop_query)

    def verify_relationship_weights(self):
        query = "MATCH ()-[r]->() WHERE r.weight IS NULL RETURN r LIMIT 5"
        missing_weights = self.graph.run(query).data()
        if missing_weights:
            self.logger.warning(
                "Warning: Some relationships do not have weights assigned:", missing_weights)

    def get_relationship_types(self):
        query = "MATCH ()-[r]->() RETURN DISTINCT type(r) AS rel_type"
        result = self.graph.run(query).data()
        return [record['rel_type'] for record in result]

    def normalize_entity_name(self, name):
        return name.strip().lower()

    def sanitize_relationship_name(self, name):
        return re.sub(r'\W+', '_', name.strip().lower())

    def summarize_communities(self, communities):
        community_summaries = []
        for index, community in enumerate(communities):
            nodes = community
            print(f"Summarizing community {index + 1}")

            relationships = []
            for node in nodes:
                edges_query = """
                MATCH (n1:Entity {name: $node_name})-[r]->(n2:Entity)
                RETURN n1.name AS source, r, n2.name AS target
                """
                relationships_data = self.graph.run(
                    edges_query, node_name=node).data()
                for relationship in relationships_data:
                    source = relationship['source']
                    target = relationship['target']
                    relation_type = relationship['r'].__class__.__name__
                    relationships.append(
                        f"{source} -> {relation_type} -> {target}")

            description = f"Entities: {', '.join(nodes)}\nRelationships: {', '.join(relationships)}"

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "Summarize the following community of entities and relationships."},
                    {"role": "user", "content": description}
                ]
            )

            summary = response.choices[0].message.content.strip()
            community_summaries.append(summary)

        return community_summaries
