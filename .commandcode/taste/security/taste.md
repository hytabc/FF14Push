# Security Taste
- Wants account bans (封号) enforced as a hard, server-side cut-off: banned users cannot log in and any already-authenticated banned session is forcibly logged out, rather than merely blocking the next login. Confidence: 0.6
- Prefers the frontend to surface no meaningful/descriptive text for security-sensitive states (e.g. banned accounts) — deliberately vague UI copy to prevent users from reverse-engineering the underlying logic. Confidence: 0.55
- Treats XSS/injection protection as a baseline requirement to build into new features (security hardening expected by default, not as an afterthought). Confidence: 0.55
- Wants a ban/penalty to extend across all public-facing surfaces, not just authentication: banned players must also be hidden from shared views like the leaderboard, not merely blocked from logging in. Confidence: 0.5
