# Example GraphRAG with Neo4j

This project is an example of GraphRAG, providing a system for processing documents, extracting entities and relationships, and managing them in a graph database. It leverages OpenAI's GPT models for natural language processing tasks and Neo4j for graph database management.

## Project Structure

- `app.py`: Main application script that initializes components and runs the document processing and querying workflow.
- `graph_manager.py`: Manages the graph database, including building and reprojecting the graph, calculating centrality measures, and managing graph operations.
- `query_handler.py`: Handles user queries by leveraging the graph data and OpenAI's GPT models for natural language processing.
- `document_processor.py`: Processes documents by splitting them into chunks, extracting entities and relationships, and summarizing them.
- `graph_database.py`: Manages the connection to the Neo4j graph database.
- `logger.py`: Provides a logging utility to log messages to both console and file with configurable log levels.

## Setup

1. **Clone the repository:**

   ```sh
   git clone git@github.com:stephenc222/example-graphrag-with-neo4j.git
   cd example-graphrag-with-neo4j
   ```

2. **Install dependencies:**

   ```sh
   pip install -r requirements.txt
   ```

3. **Set up environment variables:**
   Create a `.env` file in the root directory and add the following variables:

   ```env
   OPENAI_API_KEY=your_openai_api_key
   DB_URL=your_neo4j_db_url
   DB_USERNAME=your_neo4j_username
   DB_PASSWORD=your_neo4j_password
   LOG_LEVEL=INFO  # Optional, default is INFO
   ```

## Usage

1. Build the neo4j docker container

   ```sh
   sh build.sh
   ```

2. Start the neo4j docker container

   ```sh
   sh start.sh
   ```

3. Install the dependencies

   ```sh
   pip install -r requirements.txt
   ```

4. Run the application:

   ```sh
   python app.py
   ```

5. Initial Indexing:
   The application will first index the initial set of documents defined in `constants.py` as `DOCUMENTS`.

6. Querying:
   After indexing, the application will handle a predefined query to extract themes from the documents. Centrality measures will also be calculated to enhance the query responses.

7. Reindexing with New Documents:
   The application will then add new documents defined in `constants.py` as `DOCUMENTS_TO_ADD_TO_INDEX` and reindex the graph.

8. Second Query:
   After reindexing, the application will handle another predefined query to extract themes from the updated set of documents.

## Code Overview

### `app.py`

- **Overview**: Acts as the entry point of the application.
- **Responsibilities**:
  - Initializes the components: logger, document processor, graph manager, and query handler.
  - Handles the main workflow:
    1. Performs initial indexing of documents.
    2. Executes a user query.
    3. Reindexes the graph with new documents.
    4. Runs a second user query based on the updated graph.
  - Uses the logging utility to track the workflow progress.

### `graph_manager.py`

- **Overview**: Manages graph-related operations in the Neo4j database.
- **Responsibilities**:
  - Builds the graph from document summaries.
  - Reprojects the graph for community and centrality analysis.
  - Performs calculations such as degree centrality, betweenness centrality, and closeness centrality.
  - Supports reindexing with new documents and recalculating centrality measures.

### `query_handler.py`

- **Overview**: Handles natural language queries.
- **Responsibilities**:
  - Extracts answers from the graph using centrality measures.
  - Uses OpenAI GPT models to provide concise answers based on graph data and centrality results.

### `document_processor.py`

- **Overview**: Manages the extraction and summarization of entities and relationships from documents.
- **Responsibilities**:
  - Splits documents into chunks.
  - Extracts entities and relationships from the chunks using OpenAI GPT models.
  - Summarizes the extracted entities and relationships for graph processing.

### `graph_database.py`

- **Overview**: Manages the Neo4j database connection.
- **Responsibilities**:
  - Provides utility functions to connect to the Neo4j database.
  - Clears the database if necessary.

### `logger.py`

- **Overview**: Provides a logging utility for the application.
- **Responsibilities**:
  - Logs messages to both console and file.
  - Supports configurable log levels via environment variables (`LOG_LEVEL`).
  - Ensures logs are created in the correct format.

## Centrality Measures and Their Importance

Centrality measures help identify the most important nodes (entities) in a graph based on their structural properties. These measures help in identifying key themes and influential concepts in the documents.

1. **Degree Centrality**: Measures how many connections a node has. Nodes with a high degree centrality are the most connected and can represent key topics or ideas in the document set.
2. **Betweenness Centrality**: Identifies nodes that act as bridges between other nodes. Nodes with high betweenness centrality often represent concepts that connect different themes.

3. **Closeness Centrality**: Measures how quickly a node can reach all other nodes. Entities with high closeness centrality are well-connected to all other entities and can be key summarizers or connectors of information.

### Example Centrality Calculation:

```python
# Example for calculating centrality
graph_manager = GraphManager(db_url, db_username, db_password)
graph_manager.calculate_centrality_measures()
```

## Example Query Workflow

1. **Initial Indexing**:
   The system processes an initial set of documents, extracting entities and relationships, and storing them in a Neo4j graph.

2. **Querying**:
   A user query is handled by leveraging the centrality measures calculated from the graph, providing an intelligent answer using the OpenAI GPT model.

3. **Reindexing**:
   The system reindexes the graph when new documents are added, recalculates the centrality measures, and processes another user query.

### Sample Query Execution

```python
# Query the system after indexing
query = "What are the main themes in these documents?"
answer = query_handler.ask_question_with_centrality(query)
print(f"Answer: {answer}")
```

## Logging

Each component has its own logger, ensuring that log messages provide insight into the progress of document processing, graph operations, and query handling.

The log level can be configured dynamically at runtime using the `LOG_LEVEL` environment variable.

## Dependencies

- `openai`: For interacting with OpenAI's GPT models.
- `dotenv`: For loading environment variables from a `.env` file.
- `py2neo`: For interacting with the Neo4j graph database.
- `pickle`: For saving and loading processed data.
- `logging`: For tracking the workflow progress across the application.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE.txt) file for details.
