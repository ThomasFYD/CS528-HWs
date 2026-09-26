from math import floor
from statistics import mean, median


def percentile(values, fraction):
    if not values:
        raise ValueError("Cannot calculate a percentile of empty data")

    sorted_values = sorted(values)
    position = (len(sorted_values) - 1) * fraction

    lower_index = floor(position)
    upper_index = min(lower_index + 1, len(sorted_values) - 1)
    weight = position - lower_index

    lower_value = sorted_values[lower_index]
    upper_value = sorted_values[upper_index]

    return lower_value + weight * (upper_value - lower_value)


def calculate_degree_statistics(adjacency):
    degrees = [len(neighbors) for neighbors in adjacency.values()]

    return {
        "average": mean(degrees),
        "median": median(degrees),
        "minimum": min(degrees),
        "maximum": max(degrees),
        "quintiles": {
            "0%": percentile(degrees, 0.0),
            "20%": percentile(degrees, 0.2),
            "40%": percentile(degrees, 0.4),
            "60%": percentile(degrees, 0.6),
            "80%": percentile(degrees, 0.8),
            "100%": percentile(degrees, 1.0),
        },
    }


def print_degree_statistics(label, results):
    print(f"\n{label}")
    print(f"Average: {results['average']:.4f}")
    print(f"Median: {results['median']}")
    print(f"Minimum: {results['minimum']}")
    print(f"Maximum: {results['maximum']}")
    print("Quintiles:")

    for percentile_name, value in results["quintiles"].items():
        print(f"  {percentile_name}: {value}")