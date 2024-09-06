from py2neo import Graph, Node, Relationship
from openai import OpenAI
import networkx as nx
from dotenv import load_dotenv
from constants import DOCUMENTS
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
        print(f"Extracting elements from chunk {index + 1}")
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "Extract entities and relationships from the following text."},
                {"role": "user", "content": chunk}
            ]
        )
        entities_and_relations = response.choices[0].message.content
        elements.append(entities_and_relations)
    return elements


def summarize_elements(elements):
    summaries = []
    for index, element in enumerate(elements):
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "Summarize the following entities and relationships in a structured format. Use '->' to represent relationships, after the 'Relationships:' word."},
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

            # Create nodes for entities, remove the index before creating nodes
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

            # Create relationships between entities
            elif relationships_section and line.strip():
                parts = line.split("->")
                if len(parts) >= 2:
                    source = normalize_entity_name(parts[0].strip())
                    target = normalize_entity_name(parts[-1].strip())
                    relation_name = sanitize_relationship_name(
                        " -> ".join(parts[1:-1]).strip())

                    # Strip digits and erroneous spaces from source and target
                    source = ''.join(
                        [i for i in source if not i.isdigit() and i != '.']).strip()
                    target = ''.join(
                        [i for i in target if not i.isdigit() and i != '.']).strip()

                    print(
                        f"Parsed relationship: {source} -> {relation_name} -> {target}")
                    if source in entities and target in entities:
                        if relation_name:  # Ensure relation_name is not empty
                            print(
                                f"Creating relationship: {source} -> {relation_name} -> {target}")
                            relation = Relationship(
                                entities[source], relation_name, entities[target])
                            graph.merge(relation)
                        else:
                            print(
                                f"Skipping relationship: {source} -> {relation_name} -> {target} (relation name is empty)")
                    else:
                        print(
                            f"Skipping relationship: {source} -> {relation_name} -> {target} (one or both entities not found)")


def reindex_graph_in_neo4j(new_summaries, graph):
    if graph is None:
        print("Graph database connection is not available.")
        return

    build_graph_in_neo4j(new_summaries, graph)
    graph.run(
        "CALL db.index.fulltext.createNodeIndex('entityIndex', ['Entity'], ['name'])")


def get_relationship_types(graph):
    query = "CALL db.relationshipTypes()"
    result = graph.run(query).data()
    return [record['relationshipType'] for record in result]


def detect_communities_neo4j(graph):
    if graph is None:
        print("Graph database connection is not available.")
        return []

    # Check and use actual relationship types
    relationship_types = get_relationship_types(graph)
    if not relationship_types:
        print("No relationships found in the graph.")
        return []
    # Build the relationship projection dynamically for GDS 2.9.0
    relationship_projection = ', '.join(
        [f'{sanitize_relationship_name(rel_type)}: {{"type": "{sanitize_relationship_name(rel_type)}", "orientation": "UNDIRECTED"}}'
         for rel_type in relationship_types]
    )
    query = f"""
    CALL gds.graph.project(
        'entityGraph',
        ['Entity'],
        {{{relationship_projection}}}
    )
    """
    query = """
    CALL gds.graph.project(
        'entityGraph',
        ['Entity'],
        {
            protects: {type: 'protects', orientation: 'UNDIRECTED'},
            promotes: {type: 'promotes', orientation: 'UNDIRECTED'},
            includes: {type: 'includes', orientation: 'UNDIRECTED'},
            causes: {type: 'causes', orientation: 'UNDIRECTED'}
        }
    )
    """
    #         {{{relationship_projection}}}

    # Debugging: Print out the constructed query to check syntax
    print("Constructed query for graph projection:")
    print(query)

    try:
        graph.run(query)
    except Exception as e:
        print(f"Graph creation failed: {e}")
        return None

    # Run the Louvain algorithm
    query = """
    CALL gds.louvain.stream('entityGraph', {
        relationshipWeightProperty: null
    })
    YIELD nodeId, communityId
    RETURN gds.util.asNode(nodeId).name AS entityName, communityId
    ORDER BY communityId, entityName
    """
    result = graph.run(query).data()

    communities = {}
    for record in result:
        community_id = record["communityId"]
        entity_name = record["entityName"]
        if community_id not in communities:
            communities[community_id] = []
        communities[community_id].append(entity_name)

    return list(communities.values())


def summarize_communities(communities, graph):
    community_summaries = []
    for index, community in enumerate(communities):
        subgraph = nx.Graph()
        nodes = community
        print(f"Building subgraph for community {index + 1}")
        for node in nodes:
            subgraph.add_node(node)
            edges_query = f"""
            MATCH (n1:Entity {{name: $node_name}})-[r]->(n2:Entity)
            RETURN n1.name, r, n2.name
            """
            relationships = graph.run(edges_query, node_name=node).data()
            for relationship in relationships:
                source = relationship['n1.name']
                target = relationship['n2.name']
                label = relationship['r'].__class__.__name__
                subgraph.add_edge(source, target, label=label)

        edges = list(subgraph.edges(data=True))
        description = "Entities: " + ", ".join(nodes) + "\nRelationships: "
        relationships = []
        for edge in edges:
            relationships.append(
                f"{edge[0]} -> {edge[2]['label']} -> {edge[1]}")
        description += ", ".join(relationships)

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


def graph_rag_pipeline_neo4j(documents, query, graph, chunk_size=600, overlap_size=100):
    print("Splitting documents into chunks")
    chunks = split_documents_into_chunks(documents, chunk_size, overlap_size)
    print("Extracting elements from chunks")

    elements_file = 'data/elements_data.pkl'
    summaries_file = 'data/summaries_data.pkl'
    communities_file = 'data/communities_data.pkl'
    community_summaries_file = 'data/community_summaries_data.pkl'

    elements = load_or_run(elements_file, extract_elements_from_chunks, chunks)
    print("Summarizing elements")
    summaries = load_or_run(summaries_file, summarize_elements, elements)
    print("Building graph in Neo4j")
    build_graph_in_neo4j(summaries, graph)
    print("Detecting communities in the graph")
    communities = load_or_run(
        communities_file, detect_communities_neo4j, graph)
    print("Summarizing communities")
    community_summaries = load_or_run(
        community_summaries_file, summarize_communities, communities, graph)
    print("Generating final answer")
    final_answer = generate_answers_from_communities(
        community_summaries, query)
    return final_answer


# Example usage
query = "What are the main themes in these documents?"
print("Starting the RAG pipeline")
answer = graph_rag_pipeline_neo4j(DOCUMENTS, query, graph)
print('Answer:', answer)
