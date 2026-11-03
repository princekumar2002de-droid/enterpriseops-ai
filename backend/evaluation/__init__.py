"""Evaluation harness: compares engine/agent output with the ground truth in ``eval``.

Lives outside ``app`` on purpose: the application never imports ground truth (ADR-018).
"""
