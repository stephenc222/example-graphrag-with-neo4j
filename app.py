from py2neo import Graph, Node, Relationship
from openai import OpenAI
from dotenv import load_dotenv
from constants import DOCUMENTS, DOCUMENTS_TO_ADD_TO_INDEX
import os
import pickle
import re


load_dotenv()


DB_URL = os.getenv("DB_URL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

DB_USERNAME = os.getenv("DB_USERNAME")
DB_PASSWORD = os.getenv("DB_PASSWORD")

MODEL = "gpt-4o-2024-08-06"

# Connect to the Neo4j database
try:
    graph = Graph(DB_URL, auth=(DB_USERNAME, DB_PASSWORD))
    print("Connected to the database")
    graph.delete_all()
    print("Deleted all data from the database")
except Exception as e:
    print(f"Error connecting to the database: {e}")
    graph = None
    exit(1)

client = OpenAI(api_key=OPENAI_API_KEY)


def sanitize_relationship_name(name):
    # Replace spaces and special characters with underscores
    return re.sub(r'\W+', '_', name.strip().lower())


def split_documents_into_chunks(documents, chunk_size=600, overlap_size=100):
    chunks = []
    for document in documents:
        for i in range(0, len(document), chunk_size - overlap_size):
            chunk = document[i:i + chunk_size]
            chunks.append(chunk)
    return chunks


def extract_elements_from_chunks(chunks):
    elements = []
    for index, chunk in enumerate(chunks):
        print(
            f"Extracting elements and relationship strength from chunk {index + 1}")
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system",
                    "content": "Extract entities, relationships, and their strength from the following text. Use common terms such as 'related to', 'depends on', 'influences', etc., for relationships, and estimate a strength between 0.0 (very weak) and 1.0 (very strong). Format: Parsed relationship: Entity1 -> Relationship -> Entity2 [strength: X.X]. Do not include any other text in your response. Use this exact format: Parsed relationship: Entity1 -> Relationship -> Entity2 [strength: X.X]."},
                {"role": "user", "content": chunk}
            ]
        )
        entities_and_relations = response.choices[0].message.content
        elements.append(entities_and_relations)
    return elements


def summarize_elements(elements):
    summaries = []
    for index, element in enumerate(elements):
        print(f"Summarizing element {index + 1}")
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "Summarize the following entities and relationships in a structured format. Use common terms such as 'related to', 'depends on', 'influences', etc., for relationships. Use '->' to represent relationships after the 'Relationships:' word."},
                {"role": "user", "content": element}
            ]
        )
        summary = response.choices[0].message.content
        summaries.append(summary)
    return summaries


def normalize_entity_name(name):
    return name.strip().lower()  # Convert to lowercase and strip any extra whitespace


def build_graph_in_neo4j(summaries, graph):
    if graph is None:
        print("Graph database connection is not available.")
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

            # Create nodes for entities
            if entities_section and line.strip():
                if line[0].isdigit() and '.' in line:  # Check for numbered entities
                    entity_name = line.split(".", 1)[1].strip()
                else:
                    entity_name = line.strip()
                entity_name = normalize_entity_name(
                    entity_name.replace("**", ""))
                node = Node("Entity", name=entity_name)
                print(f"Creating node: {entity_name}")
                graph.merge(node, "Entity", "name")
                entities[entity_name] = node

            # Create relationships between entities with strength
            elif relationships_section and line.strip():
                parts = line.split("->")
                if len(parts) >= 2:
                    source = normalize_entity_name(parts[0].strip())
                    target = normalize_entity_name(parts[-1].strip())

                    # Extract relationship and strength
                    relationship_part = parts[1].strip()
                    relation_name = sanitize_relationship_name(
                        relationship_part.split("[")[0].strip())
                    strength = re.search(
                        r"\[strength:\s*(\d\.\d)\]", relationship_part)
                    print(f"Relationship name: {relation_name}")
                    print(f"Strength: {strength}")
                    # Default weight if missing
                    weight = float(strength.group(1)) if strength else 1.0

                    print(
                        f"Parsed relationship: {source} -> {relation_name} -> {target} [weight: {weight}]")
                    if source in entities and target in entities:
                        if relation_name:  # Ensure relation_name is not empty
                            print(
                                f"Creating relationship: {source} -> {relation_name} -> {target} with weight {weight}")
                            relation = Relationship(
                                entities[source], relation_name, entities[target])
                            relation["weight"] = weight
                            graph.merge(relation)
                        else:
                            print(
                                f"Skipping relationship: {source} -> {relation_name} -> {target} (relation name is empty)")
                    else:
                        print(
                            f"Skipping relationship: {source} -> {relation_name} -> {target} (one or both entities not found)")


def drop_existing_projection(graph_name):
    # Drop the in-memory GDS graph if it already exists
    drop_query = f"CALL gds.graph.exists('{graph_name}') YIELD exists"
    result = graph.run(drop_query).evaluate()
    if result:
        print(f"Graph projection '{graph_name}' exists, dropping it.")
        drop_query = f"CALL gds.graph.drop('{graph_name}')"
        graph.run(drop_query)
    else:
        print(
            f"Graph projection '{graph_name}' does not exist, no need to drop.")


def verify_relationship_weights(graph):
    query = "MATCH ()-[r]->() WHERE r.weight IS NULL RETURN r LIMIT 5"
    missing_weights = graph.run(query).data()
    if missing_weights:
        print("Warning: Some relationships do not have weights assigned:",
              missing_weights)
    else:
        print("All relationships have weights.")


def reproject_graph(graph, graph_name="entityGraph"):
    drop_existing_projection(graph_name)

    # Verify that all relationships have weight
    verify_relationship_weights(graph)

    # Ensure all nodes have communityId property
    graph.run(
        "MATCH (n:Entity) WHERE n.communityId IS NULL SET n.communityId = 0")

    relationship_types = get_relationship_types(graph)
    print("Relationship Types:", relationship_types)
    if not relationship_types:
        print("No relationships found to project.")
        return

    # Graph projection
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
        graph.run(query, graph_name=graph_name)
        print(f"Graph re-projected successfully")
    except Exception as e:
        print(f"Graph re-projection failed: {e}")


def reindex_with_new_documents(new_documents, graph):
    # Same logic as initial indexing, but updates graph with new documents
    chunks = split_documents_into_chunks(new_documents)

    elements_file = 'data/new_elements_data.pkl'
    summaries_file = 'data/new_summaries_data.pkl'

    elements = load_or_run(elements_file, extract_elements_from_chunks, chunks)
    summaries = load_or_run(summaries_file, summarize_elements, elements)

    # Update the graph with new nodes and relationships
    build_graph_in_neo4j(summaries, graph)

    # Re-project the graph in GDS
    reproject_graph(graph)


def reindex_graph_in_neo4j(new_summaries, graph):
    if graph is None:
        print("Graph database connection is not available.")
        return

    build_graph_in_neo4j(new_summaries, graph)
    graph.run(
        "CALL db.index.fulltext.createNodeIndex('entityIndex', ['Entity'], ['name'])")


def get_relationship_types(graph):
    query = "MATCH ()-[r]->() RETURN DISTINCT type(r) AS rel_type"
    result = graph.run(query).data()
    return [record['rel_type'] for record in result]


def summarize_communities(communities, graph):
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
            relationships_data = graph.run(edges_query, node_name=node).data()
            for relationship in relationships_data:
                source = relationship['source']
                target = relationship['target']
                relation_type = relationship['r'].__class__.__name__
                relationships.append(
                    f"{source} -> {relation_type} -> {target}")

        description = f"Entities: {', '.join(nodes)}\nRelationships: {', '.join(relationships)}"

        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "Summarize the following community of entities and relationships."},
                {"role": "user", "content": description}
            ]
        )

        summary = response.choices[0].message.content.strip()
        community_summaries.append(summary)

    return community_summaries


def generate_answers_from_communities(community_summaries, query):
    intermediate_answers = []
    for index, summary in enumerate(community_summaries):
        print(f"Generating answer from community summary {index + 1}")
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "Answer the following query based on the provided summary."},
                {"role": "user", "content": f"Query: {query} Summary: {summary}"}
            ]
        )
        intermediate_answers.append(response.choices[0].message.content)

    final_response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system",
                "content": "Combine these answers into a final, concise response."},
            {"role": "user", "content": f"Intermediate answers: {intermediate_answers}"}
        ]
    )
    final_answer = final_response.choices[0].message.content
    return final_answer


def load_or_run(file_path, run_function, *args):
    directory = os.path.dirname(file_path)
    if not os.path.exists(directory):
        os.makedirs(directory)
        print(f"Created directory {directory}")

    if os.path.exists(file_path):
        print(f"Loading data from {file_path}")
        with open(file_path, 'rb') as file:
            data = pickle.load(file)
    else:
        print(f"Running function to generate data for {file_path}")
        data = run_function(*args)
        if data is not None:
            with open(file_path, 'wb') as file:
                pickle.dump(data, file)
    return data


def initial_indexing(documents, graph):
    # Split documents, extract elements, summarize, and build graph
    chunks = split_documents_into_chunks(documents)

    elements_file = 'data/initial_elements_data.pkl'
    summaries_file = 'data/initial_summaries_data.pkl'

    elements = load_or_run(elements_file, extract_elements_from_chunks, chunks)
    summaries = load_or_run(summaries_file, summarize_elements, elements)

    build_graph_in_neo4j(summaries, graph)


def ask_question(query, graph):
    # Detect communities and summarize them to answer the question
    communities = detect_communities_with_modularity(graph, threshold=0.1)

    # Filter communities by size (optional)
    communities = filter_communities_by_size(communities, min_size=1)

    community_summaries = summarize_communities(communities, graph)
    return generate_answers_from_communities(community_summaries, query)


def detect_communities_with_modularity(graph, threshold=0.3, graph_name="entityGraph"):
    reproject_graph(graph, graph_name=graph_name)

    # Check if the graph projection exists
    check_query = f"CALL gds.graph.exists($graph_name) YIELD exists"
    exists_result = graph.run(check_query, graph_name=graph_name).evaluate()

    if not exists_result:
        raise Exception(f"Graph projection '{graph_name}' does not exist.")

    # Run Louvain to detect communities and write result to nodes
    louvain_query = """
    CALL gds.louvain.write($graph_name, {
        writeProperty: 'communityId'
    })
    YIELD nodePropertiesWritten, communityCount
    """
    try:
        graph.run(louvain_query, graph_name=graph_name)
        print(f"Louvain algorithm completed for graph '{graph_name}'")
    except Exception as e:
        print(f"Error running Louvain algorithm: {e}")
        return None

    verify_community_query = """
    MATCH (n:Entity) WHERE n.communityId IS NOT NULL
    RETURN n
    """
    try:
        result = graph.run(verify_community_query).data()
        print("Community Distribution:", result)
    except Exception as e:
        print(f"Error verifying communityId: {e}")
        return None

    if result == 0:
        print("No nodes have the 'communityId' property. Modularity cannot be calculated.")
        return None

    # Calculate modularity using gds.modularity.stream
    modularity_query = """
    CALL gds.modularity.stream($graph_name, {
        communityProperty: 'communityId',
        relationshipWeightProperty: 'weight'
    })
    YIELD communityId, modularity
    RETURN communityId, modularity
    ORDER BY modularity DESC
    """
    try:
        modularity_result = graph.run(
            modularity_query, graph_name=graph_name).data()
        if not modularity_result:
            raise Exception("Modularity calculation returned no data.")
        print(
            f"Modularity calculation completed with {len(modularity_result)} results.")
        # Print modularity results in a human-friendly format
        print("Modularity Results:")
        for record in modularity_result:
            print(
                f"Community ID: {record['communityId']}, Modularity: {record['modularity']}")
    except Exception as e:
        print(f"Error calculating modularity: {e}")
        return None

    communities = {}
    for record in modularity_result:
        community_id = record["communityId"]
        modularity = record["modularity"]
        if modularity >= threshold:
            if community_id not in communities:
                communities[community_id] = []
            communities[community_id].append(community_id)

    return {cid: community for cid, community in communities.items() if len(community) >= 3}


def filter_communities_by_size(communities, min_size=2):
    """
    Filter out communities that have fewer than min_size nodes.
    """
    if not communities:
        print("No communities detected or modularity calculation failed.")
        return {}

    filtered_communities = {cid: nodes for cid,
                            nodes in communities.items() if len(nodes) >= min_size}
    print(
        f"Filtered communities: {len(filtered_communities)} remaining after applying size threshold.")
    return filtered_communities


def calculate_centrality_measures(graph, graph_name="entityGraph"):
    """
    Calculate centrality measures such as degree, betweenness, and closeness
    for nodes in the projected graph and return the most central nodes.
    """
    # Ensure the graph is projected first
    reproject_graph(graph, graph_name)

    # Check if the graph projection exists
    check_query = f"CALL gds.graph.exists($graph_name) YIELD exists"
    exists_result = graph.run(check_query, graph_name=graph_name).evaluate()

    if not exists_result:
        raise Exception(f"Graph projection '{graph_name}' does not exist.")

    # Calculate Degree Centrality
    degree_centrality_query = f"""
    CALL gds.degree.stream($graph_name)
    YIELD nodeId, score
    RETURN gds.util.asNode(nodeId).name AS entityName, score
    ORDER BY score DESC
    LIMIT 10
    """
    degree_centrality_result = graph.run(
        degree_centrality_query, graph_name=graph_name).data()
    print("Top Degree Centrality Nodes:", degree_centrality_result)

    # Calculate Betweenness Centrality
    betweenness_centrality_query = f"""
    CALL gds.betweenness.stream($graph_name)
    YIELD nodeId, score
    RETURN gds.util.asNode(nodeId).name AS entityName, score
    ORDER BY score DESC
    LIMIT 10
    """
    betweenness_centrality_result = graph.run(
        betweenness_centrality_query, graph_name=graph_name).data()
    print("Top Betweenness Centrality Nodes:", betweenness_centrality_result)

    # Calculate Closeness Centrality
    closeness_centrality_query = f"""
    CALL gds.closeness.stream($graph_name)
    YIELD nodeId, score
    RETURN gds.util.asNode(nodeId).name AS entityName, score
    ORDER BY score DESC
    LIMIT 10
    """
    closeness_centrality_result = graph.run(
        closeness_centrality_query, graph_name=graph_name).data()
    print("Top Closeness Centrality Nodes:", closeness_centrality_result)

    # Combine the results
    centrality_data = {
        "degree": degree_centrality_result,
        "betweenness": betweenness_centrality_result,
        "closeness": closeness_centrality_result
    }

    return centrality_data


def summarize_centrality_measures(centrality_data):
    """
    Summarize the centrality measures into a meaningful report.
    """
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


def ask_question_with_centrality(query, graph):
    """
    This function answers the user's question by first calculating centrality measures
    and then providing an answer based on the most central entities.
    """
    # Calculate centrality measures
    centrality_data = calculate_centrality_measures(graph)

    # Summarize the centrality measures
    centrality_summary = summarize_centrality_measures(centrality_data)

    # Use LLM to generate a final answer based on the centrality summary
    print("Generating final answer from centrality data...")
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "Use the centrality measures to answer the following query."},
            {"role": "user", "content": f"Query: {query} Centrality Summary: {centrality_summary}"}
        ]
    )

    final_answer = response.choices[0].message.content
    return final_answer


if __name__ == "__main__":
    initial_documents = DOCUMENTS  # Initial set of documents

    # Index the initial documents
    initial_indexing(initial_documents, graph)

    # First question after initial indexing
    query_1 = "What are the main themes in these documents?"
    print(query_1)
    answer_1 = ask_question_with_centrality(query_1, graph)
    print('Answer to query 1:', answer_1)

    # Adding new documents and reindexing
    new_documents = DOCUMENTS_TO_ADD_TO_INDEX  # New documents to be added
    reindex_with_new_documents(new_documents, graph)

    # Second question after reindexing with new documents
    query_2 = "What are the main themes in these documents?"
    print(query_2)
    answer_2 = ask_question_with_centrality(query_2, graph)
    print('Answer to query 2:', answer_2)
