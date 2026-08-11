import json
import sys
from pathlib import Path

def deduplicate_by_name(traits):
    """Remove duplicates by trait_name, keeping first occurrence."""
    seen = set()
    unique = []
    for trait in traits:
        name = trait.get("trait_name")
        if name not in seen:
            seen.add(name)
            unique.append(trait)
    return unique, len(traits) - len(unique)

def deduplicate_by_description(traits, similarity_threshold=0.8):
    """
    Remove traits with similar descriptions using cosine similarity.
    Keeps the first occurrence in case of similarity.
    Returns (new_traits, num_removed)
    """
    if len(traits) < 2:
        return traits, 0

    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
    except ImportError:
        print("Warning: sklearn not available. Skipping description-based deduplication.")
        return traits, 0

    # Extract descriptions
    descriptions = [trait.get("description", "") for trait in traits]

    # Vectorize
    vectorizer = TfidfVectorizer()
    tfidf_matrix = vectorizer.fit_transform(descriptions)

    # Compute cosine similarity
    similarity_matrix = cosine_similarity(tfidf_matrix)

    # We'll keep the first trait and remove any later trait that is similar to any kept trait
    to_keep = [True] * len(traits)
    for i in range(len(traits)):
        if not to_keep[i]:
            continue
        for j in range(i+1, len(traits)):
            if not to_keep[j]:
                continue
            if similarity_matrix[i][j] >= similarity_threshold:
                # Mark j for removal
                to_keep[j] = False

    new_traits = [traits[i] for i in range(len(traits)) if to_keep[i]]
    removed = len(traits) - len(new_traits)
    return new_traits, removed

def main():
    seed_path = Path("asomien/config/personality_seed.json")
    if not seed_path.exists():
        print(f"Error: {seed_path} not found")
        sys.exit(1)

    with open(seed_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    total_removed = 0
    changes_made = False

    # Process core_traits
    if "core_traits" in data:
        original_count = len(data["core_traits"])
        # Step 1: deduplicate by name
        data["core_traits"], removed_by_name = deduplicate_by_name(data["core_traits"])
        # Step 2: deduplicate by description
        data["core_traits"], removed_by_desc = deduplicate_by_description(data["core_traits"])
        removed_core = removed_by_name + removed_by_desc
        if removed_core > 0:
            changes_made = True
            total_removed += removed_core
            print(f"Core traits: removed {removed_by_name} duplicate names, {removed_by_desc} similar descriptions (total {removed_core})")

    # Process adaptive_traits
    if "adaptive_traits" in data:
        original_count = len(data["adaptive_traits"])
        # Step 1: deduplicate by name
        data["adaptive_traits"], removed_by_name = deduplicate_by_name(data["adaptive_traits"])
        # Step 2: deduplicate by description
        data["adaptive_traits"], removed_by_desc = deduplicate_by_description(data["adaptive_traits"])
        removed_adaptive = removed_by_name + removed_by_desc
        if removed_adaptive > 0:
            changes_made = True
            total_removed += removed_adaptive
            print(f"Adaptive traits: removed {removed_by_name} duplicate names, {removed_by_desc} similar descriptions (total {removed_adaptive})")

    if changes_made or total_removed > 0:
        # Write back with indentation
        with open(seed_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"Deduplicated personality_seed.json (removed {total_removed} traits total)")
    else:
        print("No duplicates found in personality_seed.json")

if __name__ == "__main__":
    main()