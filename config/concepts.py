"""Load and validate concept taxonomy."""

import sys
from pathlib import Path
import yaml


def load_concepts():
    """Load and validate the concept taxonomy from YAML."""
    yaml_path = Path(__file__).parent / 'concepts.yaml'

    with open(yaml_path) as f:
        data = yaml.safe_load(f)

    concepts = data.get('concepts', {})

    # Validate prerequisites
    concept_ids = set(concepts.keys())
    for concept_id, concept in concepts.items():
        prerequisites = concept.get('prerequisites', [])
        for prereq in prerequisites:
            if prereq not in concept_ids:
                raise ValueError(
                    f"Concept {concept_id} has unknown prerequisite: {prereq}"
                )

    return concepts


def get_concept(concept_id: str):
    """Get a single concept by ID."""
    concepts = load_concepts()
    if concept_id not in concepts:
        raise ValueError(f"Unknown concept: {concept_id}")
    return concepts[concept_id]
