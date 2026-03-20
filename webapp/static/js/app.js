/* NST Exam Evaluator - Main JS */
// Utility functions used across pages

document.addEventListener('DOMContentLoaded', function() {
    // Auto-dismiss flash messages after 5s
    document.querySelectorAll('.flash-message').forEach(el => {
        setTimeout(() => {
            el.style.opacity = '0';
            setTimeout(() => el.remove(), 300);
        }, 5000);
    });
});
