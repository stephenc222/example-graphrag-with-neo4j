# Use the official Neo4j base image
FROM neo4j:latest

# Set environment variables for Neo4j to set the username to 'username' and password to 'password'
ENV NEO4J_AUTH=neo4j/password
ENV NEO4J_dbms_memory_heap_max__size=2G

# Install additional packages such as curl
# USER root
# RUN apt-get update && apt-get install -y netcat


# Expose the default port for Neo4j (HTTP, HTTPS, Bolt)
EXPOSE 7474 7473 7687

# Copy the seed script to the import directory
# COPY seed.cyp /var/lib/neo4j/import/

# Copy custom entrypoint
# COPY docker-entrypoint.sh /docker-entrypoint.sh
# RUN chmod +x /docker-entrypoint.sh

# USER neo4j

# Set the entrypoint to the custom script
# ENTRYPOINT ["/docker-entrypoint.sh"]


# Copy any custom scripts, configurations or plugins
# COPY ./plugins /plugins
# COPY ./conf /var/lib/neo4j/conf

# Uncomment to include an entrypoint script to customize startup
# COPY ./docker-entrypoint.sh /docker-entrypoint.sh
# ENTRYPOINT ["/docker-entrypoint.sh"]

# The base image includes a command to start Neo4j,
# so we don't need to add a CMD instruction unless we want to customize the startup command.