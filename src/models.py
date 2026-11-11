"""Modelos de dados do SmartBill AI Pipeline.

Define a estrutura de uma conta (``Bill``) e as categorias possiveis
(``BillCategory``). Valores monetarios usam ``Decimal`` para evitar erros
de arredondamento tipicos de ``float``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum


class BillCategory(str, Enum):
    """Categorias de contas reconhecidas pelo sistema."""

    ENERGY = "energia"
    WATER = "agua"
    INTERNET = "internet"
    PHONE = "telefone"
    RENT = "aluguel"
    CREDIT_CARD = "cartao_de_credito"
    HEALTH = "saude"
    EDUCATION = "educacao"
    TAXES = "impostos"
    OTHER = "outros"

    @classmethod
    def from_text(cls, value: str) -> "BillCategory":
        """Converte um texto em categoria; texto desconhecido vira ``OTHER``."""
        normalized = value.strip().lower()
        for category in cls:
            if category.value == normalized:
                return category
        return cls.OTHER


@dataclass(frozen=True, slots=True)
class Bill:
    """Uma conta, fatura ou boleto ja extraido e validado.

    Attributes:
        provider: Nome do prestador (ex.: "Cemig").
        amount: Valor a pagar, sempre maior que zero.
        due_date: Data de vencimento.
        category: Categoria da conta.
        source_file: Nome do arquivo de origem.

    Raises:
        ValueError: Se o prestador for vazio ou o valor nao for positivo.
    """

    provider: str
    amount: Decimal
    due_date: date
    category: BillCategory
    source_file: str

    def __post_init__(self) -> None:
        """Valida os dados logo na criacao do objeto."""
        if not self.provider.strip():
            raise ValueError("O prestador (provider) nao pode ser vazio.")
        if self.amount <= 0:
            raise ValueError(
                f"O valor deve ser maior que zero (recebido: {self.amount})."
            )