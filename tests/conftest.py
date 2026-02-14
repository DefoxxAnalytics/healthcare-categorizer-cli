from pathlib import Path
import pytest
import yaml


ROOT = Path(__file__).parent.parent

PATH_ALIASES = {"sc_mapping": "category_mapping"}
COLUMN_ALIASES = {"spend_category": "category_source", "line_memo": "description"}
CLASSIFICATION_ALIASES = {"sc_code_pattern": "category_code_pattern"}


def _apply_test_aliases(config):
    for section, aliases in [
        ("paths", PATH_ALIASES),
        ("columns", COLUMN_ALIASES),
        ("classification", CLASSIFICATION_ALIASES),
    ]:
        if section not in config:
            continue
        for old, new in aliases.items():
            if old in config[section] and new not in config[section]:
                config[section][new] = config[section].pop(old)
    return config


def pytest_addoption(parser):
    parser.addoption(
        "--client-dir",
        default=str(ROOT / "clients" / "cchmc"),
        help="Path to client directory containing config.yaml and data/reference/",
    )


@pytest.fixture(scope="session")
def client_dir(request):
    return Path(request.config.getoption("--client-dir")).resolve()


@pytest.fixture(scope="session")
def client_config(client_dir):
    config_path = client_dir / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return _apply_test_aliases(config)


@pytest.fixture(scope="session")
def refinement(client_dir, client_config):
    path = client_dir / client_config["paths"]["refinement_rules"]
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="session")
def category_mapping(client_dir, client_config):
    path = client_dir / client_config["paths"]["category_mapping"]
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="session")
def sc_mapping(category_mapping):
    return category_mapping


@pytest.fixture(scope="session")
def keyword_rules(client_dir, client_config):
    path = client_dir / client_config["paths"]["keyword_rules"]
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="session")
def taxonomy_keys(client_dir, client_config):
    import pandas as pd
    path = client_dir / client_config["paths"]["taxonomy"]
    df = pd.read_excel(path)
    return set(df["Key"].dropna().astype(str))


@pytest.fixture(scope="session")
def valid_category_codes(category_mapping):
    return set(str(k).strip() for k in category_mapping.get("mappings", {}).keys())


@pytest.fixture(scope="session")
def valid_sc_codes(valid_category_codes):
    return valid_category_codes


@pytest.fixture(scope="session")
def has_context_rules(client_config):
    return client_config["columns"].get("line_of_service") is not None


@pytest.fixture(scope="session")
def has_cost_center_rules(client_config):
    return client_config["columns"].get("cost_center") is not None


@pytest.fixture(scope="session")
def test_assertions(client_dir):
    path = client_dir / "test_assertions.yaml"
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
