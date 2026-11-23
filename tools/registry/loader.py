"""YAML loading that rejects duplicate keys.

PyYAML's default loaders silently keep the LAST value of a duplicated key, so a subscription
declared twice in one tenant file would be merged without warning. This loader fails instead.
"""
import yaml


class DuplicateKeyError(yaml.YAMLError):
    pass


class UniqueKeyLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        seen = {}
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                raise DuplicateKeyError(
                    f"duplicate key '{key}' at line {key_node.start_mark.line + 1} "
                    f"(first defined at line {seen[key] + 1})")
            seen[key] = key_node.start_mark.line
        return super().construct_mapping(node, deep=deep)


def load_yaml(path):
    with open(path, encoding="utf-8") as fh:
        return yaml.load(fh, Loader=UniqueKeyLoader)
