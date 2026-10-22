"""Phase 3: optional, on-click AI with guardrails (spec 2026-10-21-phase3-ai-design).

``service.AIService`` is the only entry point: ``prepare`` shows what would be sent,
``run`` sends exactly that. Providers live in ``anthropic`` (real, built only when a
call is made) and ``fake`` (tests, ``DAM_AI_FAKE=1``). The key is in ``keys`` (Keychain).
"""
