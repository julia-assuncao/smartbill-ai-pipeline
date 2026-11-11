"""Testes automaticos do modulo de ingestao."""

from pathlib import Path

import pytest

from src.exceptions import InputDirectoryError
from src.ingestion import DocumentIngestor, DocumentKind

PDF_BYTES = b"%PDF-1.4 teste"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 10


def test_aceita_pdf_valido(tmp_path: Path) -> None:
    (tmp_path / "boleto.pdf").write_bytes(PDF_BYTES)
    result = DocumentIngestor(tmp_path).scan()
    assert [f.path.name for f in result.valid] == ["boleto.pdf"]
    assert result.valid[0].kind == DocumentKind.PDF
    assert result.skipped == []


def test_aceita_imagem_png(tmp_path: Path) -> None:
    (tmp_path / "conta.png").write_bytes(PNG_BYTES)
    result = DocumentIngestor(tmp_path).scan()
    assert result.valid[0].kind == DocumentKind.IMAGE


def test_recusa_extensao_nao_suportada(tmp_path: Path) -> None:
    (tmp_path / "notas.txt").write_text("oi")
    result = DocumentIngestor(tmp_path).scan()
    assert result.valid == []
    assert "extensao" in result.skipped[0].reason.replace("ã", "a")


def test_recusa_arquivo_vazio(tmp_path: Path) -> None:
    (tmp_path / "vazio.pdf").write_bytes(b"")
    result = DocumentIngestor(tmp_path).scan()
    assert result.skipped[0].reason == "arquivo vazio"


def test_recusa_pdf_falso(tmp_path: Path) -> None:
    (tmp_path / "falso.pdf").write_text("oi")
    result = DocumentIngestor(tmp_path).scan()
    assert result.valid == []
    assert len(result.skipped) == 1


def test_recusa_arquivo_grande(tmp_path: Path) -> None:
    (tmp_path / "grande.pdf").write_bytes(PDF_BYTES + b"0" * (2 * 1024 * 1024))
    result = DocumentIngestor(tmp_path, max_file_size_mb=1).scan()
    assert result.valid == []
    assert "excede" in result.skipped[0].reason


def test_ignora_arquivos_ocultos(tmp_path: Path) -> None:
    (tmp_path / ".oculto.pdf").write_bytes(PDF_BYTES)
    result = DocumentIngestor(tmp_path).scan()
    assert result.total_scanned == 0


def test_modo_recursivo(tmp_path: Path) -> None:
    pasta = tmp_path / "sub"
    pasta.mkdir()
    (pasta / "fatura.pdf").write_bytes(PDF_BYTES)
    assert DocumentIngestor(tmp_path).scan().valid == []
    assert len(DocumentIngestor(tmp_path, recursive=True).scan().valid) == 1


def test_diretorio_inexistente(tmp_path: Path) -> None:
    with pytest.raises(InputDirectoryError):
        DocumentIngestor(tmp_path / "nao_existe").scan()


def test_caminho_e_um_arquivo(tmp_path: Path) -> None:
    arquivo = tmp_path / "a.pdf"
    arquivo.write_bytes(PDF_BYTES)
    with pytest.raises(InputDirectoryError):
        DocumentIngestor(arquivo).scan()
