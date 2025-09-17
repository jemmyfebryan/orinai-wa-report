import yaml
import json

# YAML Config
with open('config.yaml', 'r') as file:
    config_data = yaml.safe_load(file)

print(json.dumps(config_data, indent=2))