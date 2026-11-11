"""Módulo de ingestão de documentos.

Responsabilidade única: varrer um diretório de entrada e separar os arquivos
em *válidos* (suportados e íntegros) e *ignorados* (com o motivo registrado).

Este módulo NÃO lê o conteúdo dos documentos nem conhece o LLM. Ele apenas
entrega à próxima etapa do pipeline uma lista confiável de ``IngestedFile``.

Validações aplicadas a cada arquivo:
    1. Não é arquivo oculto (ex.: ``.DS_Store``).
    2. Extensão suportada (PDF, PNG, JPEG, WEBP, GIF).
    3. Arquivo legível, não vazio e dentro do limite de tamanho.
    4. Assinatura binária (*magic bytes*) compatível com a extensão,
       evitando, por exemplo, um ``.pdf`` que na verdade é um ``.exe``.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterable

from src.exceptions import InputDirectoryError

logger = logging.getLogger(__name__)

# A API da Anthropic limita o tamanho total da requisição (32 MB).
DEFAULT_MAX_FILE_SIZE_MB: int = 32
_BYTES_PER_MB: int = 1024 * 1024
_HEADER_SIZE: int = 12  # bytes suficientes para identificar todos os formatos


class DocumentKind(str, Enum):
    """Categoria do documento, usada para escolher a estratégia de extração."""

    PDF = "pdf"
    IMAGE = "image"


# Mapeamento extensão -> categoria. Ponto único de extensão (Open/Closed):
# para suportar um novo formato, basta registrá-lo aqui e em _SIGNATURES.
SUPPORTED_EXTENSIONS: dict[str, DocumentKind] = {
    ".pdf": DocumentKind.PDF,
    ".png": DocumentKind.IMAGE,
    ".jpg": DocumentKind.IMAGE,
    ".jpeg": DocumentKind.IMAGE,
    ".webp": DocumentKind.IMAGE,
    ".gif": DocumentKind.IMAGE,
}

# Assinaturas binárias esperadas no início de cada formato.
_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    ".pdf": (b"%PDF-",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".gif": (b"GIF87a", b"GIF89a"),
    # WEBP é tratado à parte: "RIFF" (bytes 0-3) + "WEBP" (bytes 8-11).
}


@dataclass(frozen=True, slots=True)
class IngestedFile:
    """Arquivo validado e pronto para a etapa de extração.

    Attributes:
        path: Caminho absoluto do arquivo.
        kind: Categoria do documento (PDF ou imagem).
        size_bytes: Tamanho do arquivo em bytes.
    """

    path: Path
    kind: DocumentKind
    size_bytes: int


@dataclass(frozen=True, slots=True)
class SkippedFile:
    """Arquivo descartado durante a ingestão, com o motivo documentado."""

    path: Path
    reason: str


@dataclass(slots=True)
class IngestionResult:
    """Resultado agregado da varredura do diretório.

    Attributes:
        valid: Arquivos aprovados em todas as validações.
        skipped: Arquivos rejeitados, com o motivo.
    """

    valid: list[IngestedFile] = field(default_factory=list)
    skipped: list[SkippedFile] = field(default_factory=list)

    @property
    def total_scanned(self) -> int:
        """Total de arquivos analisados (válidos + ignorados)."""
        return len(self.valid) + len(self.skipped)


class DocumentIngestor:
    """Varre um diretório e separa arquivos suportados dos não suportados.

    Example:
        >>> ingestor = DocumentIngestor(Path("data/input"), recursive=True)
        >>> result = ingestor.scan()
        >>> for doc in result.valid:
        ...     print(doc.path.name, doc.kind.value)
    """

    def __init__(
        self,
        input_dir: Path | str,
        *,
        recursive: bool = False,
        max_file_size_mb: int = DEFAULT_MAX_FILE_SIZE_MB,
        supported_extensions: Iterable[str] | None = None,
    ) -> None:
        """Inicializa o ingestor.

        Args:
            input_dir: Diretório contendo faturas, contas e boletos.
            recursive: Se ``True``, percorre também os subdiretórios.
            max_file_size_mb: Tamanho máximo aceito por arquivo, em MB.
            supported_extensions: Subconjunto opcional de extensões a aceitar
                (ex.: ``[".pdf"]``). Por padrão, aceita todas as suportadas.

        Raises:
            ValueError: Se ``max_file_size_mb`` não for positivo ou se alguma
                extensão informada não for suportada pelo projeto.
        """
        if max_file_size_mb <= 0:
            raise ValueError("max_file_size_mb deve ser maior que zero.")

        self._input_dir = Path(input_dir).expanduser()
        self._recursive = recursive
        self._max_size_bytes = max_file_size_mb * _BYTES_PER_MB
        self._extensions = self._resolve_extensions(supported_extensions)

    # ------------------------------------------------------------------ #
    # API pública
    # ------------------------------------------------------------------ #
    def scan(self) -> IngestionResult:
        """Executa a varredura e retorna os arquivos válidos e ignorados.

        Returns:
            ``IngestionResult`` com os arquivos ordenados por nome, o que
            garante execuções determinísticas (útil para testes e logs).

        Raises:
            InputDirectoryError: Se o diretório for inválido ou ilegível.
        """
        self._validate_input_dir()
        logger.info(
            "Iniciando varredura em '%s' (recursivo=%s).",
            self._input_dir,
            self._recursive,
        )

        result = IngestionResult()
        for path in self._iter_files():
            rejection = self._check_file(path)
            if rejection is not None:
                result.skipped.append(SkippedFile(path=path, reason=rejection))
                logger.warning("Arquivo ignorado '%s': %s", path.name, rejection)
                continue

            ingested = IngestedFile(
                path=path.resolve(),
                kind=SUPPORTED_EXTENSIONS[path.suffix.lower()],
                size_bytes=path.stat().st_size,
            )
            result.valid.append(ingested)
            logger.debug("Arquivo aceito: %s (%s)", path.name, ingested.kind.value)

        logger.info(
            "Varredura concluída: %d analisado(s), %d válido(s), %d ignorado(s).",
            result.total_scanned,
            len(result.valid),
            len(result.skipped),
        )
        return result

    # ------------------------------------------------------------------ #
    # Métodos internos
    # ------------------------------------------------------------------ #
    @staticmethod
    def _resolve_extensions(requested: Iterable[str] | None) -> frozenset[str]:
        """Normaliza e valida as extensões solicitadas."""
        if requested is None:
            return frozenset(SUPPORTED_EXTENSIONS)

        normalized = {
            ext.lower() if ext.startswith(".") else f".{ext.lower()}"
            for ext in requested
        }
        unknown = normalized - SUPPORTED_EXTENSIONS.keys()
        if unknown:
            raise ValueError(
                f"Extensões não suportadas pelo projeto: {sorted(unknown)}. "
                f"Suportadas: {sorted(SUPPORTED_EXTENSIONS)}."
            )
        return frozenset(normalized)

    def _validate_input_dir(self) -> None:
        """Garante que o diretório de entrada existe e é legível."""
        if not self._input_dir.exists():
            raise InputDirectoryError(
                f"Diretório de entrada não encontrado: '{self._input_dir}'."
            )
        if not self._input_dir.is_dir():
            raise InputDirectoryError(
                f"O caminho informado não é um diretório: '{self._input_dir}'."
            )
        if not os.access(self._input_dir, os.R_OK | os.X_OK):
            raise InputDirectoryError(
                f"Sem permissão de leitura no diretório: '{self._input_dir}'."
            )

    def _iter_files(self) -> list[Path]:
        """Lista arquivos regulares do diretório, ordenados e sem ocultos."""
        pattern = self._input_dir.rglob("*") if self._recursive else self._input_dir.iterdir()
        return sorted(
            p
            for p in pattern
            if p.is_file()
            and not any(part.startswith(".") for part in p.relative_to(self._input_dir).parts)
        )

    def _check_file(self, path: Path) -> str | None:
        """Aplica todas as validações a um arquivo.

        Args:
            path: Caminho do arquivo a validar.

        Returns:
            ``None`` se o arquivo for válido; caso contrário, uma string com
            o motivo da rejeição.
        """
        extension = path.suffix.lower()
        if extension not in self._extensions:
            return f"extensão não suportada ('{extension or 'sem extensão'}')"

        try:
            size = path.stat().st_size
        except OSError as exc:
            return f"não foi possível obter metadados ({exc.strerror})"

        if size == 0:
            return "arquivo vazio"
        if size > self._max_size_bytes:
            return (
                f"excede o limite de {self._max_size_bytes // _BYTES_PER_MB} MB "
                f"({size / _BYTES_PER_MB:.1f} MB)"
            )

        try:
            with path.open("rb") as handle:
                header = handle.read(_HEADER_SIZE)
        except OSError as exc:
            return f"arquivo ilegível ({exc.strerror})"

        if not self._signature_matches(extension, header):
            return "conteúdo não corresponde à extensão (arquivo corrompido ou renomeado)"

        return None

    @staticmethod
    def _signature_matches(extension: str, header: bytes) -> bool:
        """Verifica se os primeiros bytes batem com o formato esperado."""
        if extension == ".webp":
            return header[:4] == b"RIFF" and header[8:12] == b"WEBP"
        signatures = _SIGNATURES.get(extension, ())
        return any(header.startswith(sig) for sig in signatures)
