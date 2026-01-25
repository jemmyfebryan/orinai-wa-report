import yaml
from typing import Dict

DB_QUERY_ENDPOINT = {
    "default": "{db_base_url}/query",
    "devsites_orin": "{db_base_url}/mysql/devsites_orin",
    "devsites_orin_dev": "{db_base_url}/mysql/devsites_orin_dev",
    "sharding": "{db_base_url}/mysql/sharding",
    "production": "{db_base_url}/mysql/devsites_orin",
    "development": "{db_base_url}/mysql/devsites_orin_dev",
}

# YAML Config
with open('config.yaml', 'r') as file:
    config_data: Dict = yaml.safe_load(file)

def get_config_data():
    return config_data