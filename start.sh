#!/bin/bash

docker run --name my-neo4j-container -p 7474:7474 -p 7687:7687 --env NEO4J_PLUGINS='["graph-data-science"]' my-neo4j-image