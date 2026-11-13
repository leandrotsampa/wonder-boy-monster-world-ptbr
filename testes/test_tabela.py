import pytest

from ferramentas.tabela import ErroTabela, Tabela

TBL = "41=A\n42=B\n80=ã\nE0=á\nF0=[quebra]\nF001=[nome]\nFF=[fim]"
DADOS = bytes([0x41, 0x80, 0xF0, 0x42, 0xF0, 0x01, 0xFF])


def test_decodificar():
    assert Tabela.de_texto(TBL).decodificar(DADOS) == "Aã[quebra]B[nome][fim]"


def test_codificar_ida_e_volta():
    t = Tabela.de_texto(TBL)
    assert t.codificar(t.decodificar(DADOS)) == DADOS


def test_byte_desconhecido():
    t = Tabela.de_texto(TBL)
    assert t.decodificar(b"\x10") == "[$10]"
    assert t.codificar("[$10]") == b"\x10"


def test_caractere_ausente():
    with pytest.raises(ErroTabela) as e:
        Tabela.de_texto(TBL).codificar("Aç", "vila.npc1")
    assert "vila.npc1" in str(e.value) and "ç" in str(e.value)


def test_controle_desconhecido():
    with pytest.raises(ErroTabela, match="xyz"):
        Tabela.de_texto(TBL).codificar("A[xyz]", "id1")


def test_carregar_utf8(tmp_path):
    arq = tmp_path / "t.tbl"
    arq.write_bytes(TBL.encode("utf-8"))
    assert Tabela.carregar(arq).decodificar(b"\x80") == "ã"


def test_comentarios_e_igual():
    t = Tabela.de_texto("# comentário\n\n3D==\n41=A\n")
    assert t.decodificar(b"\x3d\x41") == "=A"
    assert t.caracteres() == {"=", "A"}


def test_hex_duplicado():
    with pytest.raises(ErroTabela):
        Tabela.de_texto("41=A\n41=B")


def test_literal_com_colchete_na_tabela():
    t = Tabela.de_texto("5B=[\n5D=]\n24=$\n30=0\n33=3\n")
    assert t.codificar(t.decodificar(b"\x03[")) == b"\x03["
