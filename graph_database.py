from neo4j import GraphDatabase


class GraphDatabaseConnection:
    def __init__(self, uri, user, password):
        if not uri or not user or not password:
            raise ValueError(
                "URI, user, and password must be provided to initialize the DatabaseConnection.")
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self):
        self.driver.close()

    def get_session(self):
        return self.driver.session()

    def clear_database(self):
        with self.get_session() as session:
            session.run("MATCH (n) DETACH DELETE n")
