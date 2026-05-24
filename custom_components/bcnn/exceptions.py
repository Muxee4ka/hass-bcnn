"""Exceptions for the Center-SBK integration."""

from __future__ import annotations


class BCNNError(Exception):
    """Base exception for Center-SBK integration."""


class BCNNAuthError(BCNNError):
    """Authentication failed — wrong login or password."""


class BCNNConnectionError(BCNNError):
    """Site is unreachable or returned an unexpected HTTP status."""


class BCNNParseError(BCNNError):
    """HTML structure did not match expectations — site may have changed."""
