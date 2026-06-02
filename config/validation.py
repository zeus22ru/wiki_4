#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared configuration invariant checks."""

from __future__ import annotations


def validate_chunk_bounds(chunk_size: int, chunk_overlap: int) -> None:
    """Validate fixed-size chunking bounds."""
    if chunk_size <= 0:
        raise ValueError("CHUNK_SIZE должен быть положительным")
    if chunk_overlap < 0:
        raise ValueError("CHUNK_OVERLAP должен быть неотрицательным")
    if chunk_overlap >= chunk_size:
        raise ValueError("CHUNK_OVERLAP должен быть меньше CHUNK_SIZE")
