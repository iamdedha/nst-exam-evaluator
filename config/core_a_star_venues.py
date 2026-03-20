"""
CORE A* venues list (2009-2012 era) as specified in the exam document.
"""

CORE_A_STAR_VENUES = {
    # Core Machine Learning
    "neurips", "nips", "icml", "jmlr", "aistats", "pami",
    # General AI
    "aaai", "ijcai",
    # Computer Vision
    "cvpr", "iccv", "eccv",
    # Speech and NLP
    "acl", "emnlp",
    # Data Mining and Databases
    "kdd", "icdm", "icde",
    # Full names (for fuzzy matching)
    "neural information processing systems",
    "international conference on machine learning",
    "journal of machine learning research",
    "artificial intelligence and statistics",
    "ieee transactions on pattern analysis and machine intelligence",
    "association for the advancement of artificial intelligence",
    "international joint conference on artificial intelligence",
    "conference on computer vision and pattern recognition",
    "international conference on computer vision",
    "european conference on computer vision",
    "association for computational linguistics",
    "empirical methods in natural language processing",
    "knowledge discovery and data mining",
    "international conference on data mining",
    "international conference on data engineering",
    # Common variations
    "ieee transactions on pattern analysis",
    "advances in neural information processing systems",
    "proceedings of the international conference on machine learning",
    "acm sigkdd",
    "sigkdd",
}

VALID_METHODS = {"arima", "time series", "gmm", "gaussian mixture", "svm", "support vector", "kernel"}

VALID_YEARS = range(2009, 2013)  # 2009-2012 inclusive
