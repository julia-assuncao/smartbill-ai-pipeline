"""Hierarquia de exceções do domínio do SmartBill AI Pipeline.

Todas as exceções do projeto herdam de ``SmartBillError``, permitindo que
camadas superiores (ex.: CLI) capturem qualquer falha esperada com um único
``except`` sem engolir erros de programação (``TypeError``, ``KeyError``...).
"""

from __future__ import annotations


class SmartBillError(Exception):
    """Exceção base para todos os erros esperados da aplicação."""


class IngestionError(SmartBillError):
    """Falha irrecuperável na etapa de ingestão (ex.: diretório inválido)."""


class InputDirectoryError(IngestionError):
    """O diretório de entrada não existe, não é um diretório ou não é legível."""
