from py2neo import Graph
from logger import Logger
import os


DB_URL = os.getenv("DB_URL")
DB_USERNAME = os.getenv("DB_USERNAME")
DB_PASSWORD = os.getenv("DB_PASSWORD")


class GraphDatabaseConnection:
    logger = Logger("GraphDatabaseConnection").get_logger()

    def __init__(self, db_url=DB_URL, username=DB_USERNAME, password=DB_PASSWORD):
        self.db_url = db_url
        self.username = username
        self.password = password
        self.graph = self.connect()

    def connect(self):
        try:
            graph = Graph(self.db_url, auth=(self.username, self.password))
            self.logger.info("Connected to the database")
            return graph
        except Exception as e:
            self.logger.error(f"Error connecting to the database: {e}")
            return None

    def clear_database(self):
        if self.graph:
            self.graph.delete_all()
            self.logger.info("Deleted all data from the database")
