"""Results viewing routes with chart data."""
import numpy as np
from flask import Blueprint, render_template, jsonify
from webapp.services import run_manager

results_bp = Blueprint("results", __name__)

CLUSTER_COLORS = ['#3b82f6', '#ef4444', '#10b981', '#f59e0b', '#8b5cf6']
CLUSTER_NAMES = ['Cluster A', 'Cluster B', 'Cluster C', 'Cluster D', 'Cluster E']


def _build_chart_data(scores):
    """Build Plotly-ready chart data from master scores, with KMeans clustering on Part A scores."""
    part_a_scores = []
    scatter_x, scatter_y, scatter_labels = [], [], []

    for s in scores:
        a = s.get("Part A Final (50)", 0)
        if isinstance(a, (int, float)) and a > 0:
            part_a_scores.append(a)

        b_raw = s.get("Part B Raw (130)", "NO SUBMISSION")
        if isinstance(a, (int, float)) and isinstance(b_raw, (int, float)):
            scatter_x.append(a)
            scatter_y.append(s.get("Part B Final (130)", 0))
            scatter_labels.append(f"{s.get('Roll Number', '')} {s.get('Name', '')}")

    # KMeans clustering on Part A scores
    clusters = _cluster_part_a(part_a_scores)

    # KMeans on scatter (Part A vs Part B) if enough points
    scatter_clusters = _cluster_scatter(scatter_x, scatter_y)

    return {
        "part_a_scores": part_a_scores,
        "part_a_clusters": clusters,
        "scatter": {
            "x": scatter_x, "y": scatter_y,
            "labels": scatter_labels,
            "clusters": scatter_clusters,
        },
    }


def _cluster_part_a(scores, n_clusters=3):
    """Cluster Part A scores using KMeans. Returns cluster info for histogram coloring."""
    if len(scores) < n_clusters:
        return None
    try:
        from sklearn.cluster import KMeans
        X = np.array(scores).reshape(-1, 1)
        n_clusters = min(n_clusters, len(set(scores)))
        km = KMeans(n_clusters=n_clusters, n_init=10, random_state=42)
        labels = km.fit_predict(X)
        centers = sorted(km.cluster_centers_.flatten())
        tier_names = ['Low', 'Mid', 'High'] if n_clusters == 3 else [f'Tier {i+1}' for i in range(n_clusters)]
        center_order = np.argsort(km.cluster_centers_.flatten())
        label_map = {old: new for new, old in enumerate(center_order)}
        mapped = [label_map[l] for l in labels]
        return {
            "labels": mapped,
            "centers": [float(c) for c in sorted(centers)],
            "tier_names": tier_names,
            "n_clusters": n_clusters,
        }
    except ImportError:
        return None


def _cluster_scatter(x_vals, y_vals, n_clusters=3):
    """Cluster scatter points (Part A vs Part B) using KMeans."""
    if len(x_vals) < 3:
        return None
    try:
        from sklearn.cluster import KMeans
        from sklearn.preprocessing import StandardScaler
        X = np.column_stack([x_vals, y_vals])
        n_clusters = min(n_clusters, len(X))
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)
        km = KMeans(n_clusters=n_clusters, n_init=10, random_state=42)
        labels = km.fit_predict(X_scaled)
        centers = scaler.inverse_transform(km.cluster_centers_)
        center_order = np.argsort(centers[:, 0] + centers[:, 1])
        label_map = {old: new for new, old in enumerate(center_order)}
        mapped = [label_map[l] for l in labels]
        return {
            "labels": mapped,
            "centers": [[float(c[0]), float(c[1])] for c in centers[center_order]],
            "n_clusters": n_clusters,
            "colors": CLUSTER_COLORS[:n_clusters],
            "names": CLUSTER_NAMES[:n_clusters],
        }
    except ImportError:
        return None


@results_bp.route("/results/<run_id>")
def results_overview(run_id):
    meta = run_manager.get_meta(run_id)
    if not meta:
        return "Run not found", 404

    data = run_manager.get_results_data(run_id)
    scores = data.get("master_scores", [])

    valid_scores = [s for s in scores if s.get("Status") == "valid"]
    a_scores = [s.get("Part A Final (50)", 0) for s in valid_scores
                if isinstance(s.get("Part A Final (50)"), (int, float))]
    b_scores = [s.get("Part B Final (130)", 0) for s in valid_scores
                if isinstance(s.get("Part B Final (130)"), (int, float))
                and s.get("Part B Raw (130)") not in ["NO SUBMISSION", "N/A", "N/A (disqualified)"]]

    stats = {
        "total": len(scores),
        "valid": len(valid_scores),
        "disqualified": sum(1 for s in scores if s.get("Status") != "valid"),
        "part_b_count": len(b_scores),
        "flagged": sum(1 for s in scores if s.get("Needs Review") == "YES"),
        "a_avg": round(sum(a_scores) / max(len(a_scores), 1), 1),
        "a_max": max(a_scores) if a_scores else 0,
        "a_min": min(a_scores) if a_scores else 0,
        "b_avg": round(sum(b_scores) / max(len(b_scores), 1), 1) if b_scores else 0,
    }

    chart_data = _build_chart_data(scores)

    return render_template("results.html", run_id=run_id, meta=meta,
                           scores=scores, stats=stats, chart_data=chart_data)


@results_bp.route("/results/<run_id>/student/<roll>")
def student_detail(run_id, roll):
    meta = run_manager.get_meta(run_id)
    if not meta:
        return "Run not found", 404

    detail = run_manager.get_student_detail(run_id, roll)
    if not detail.get("info") and not detail.get("part_a"):
        return "Student not found", 404

    return render_template("student_detail.html", run_id=run_id,
                           detail=detail, roll=roll)


@results_bp.route("/results/<run_id>/data")
def results_data(run_id):
    """JSON API for results data."""
    data = run_manager.get_results_data(run_id)
    return jsonify(data)


@results_bp.route("/results/<run_id>/chart-data")
def chart_data(run_id):
    """JSON API for Plotly chart data."""
    data = run_manager.get_results_data(run_id)
    scores = data.get("master_scores", [])
    return jsonify(_build_chart_data(scores))
