import pytest

from ferramentas.rom import (ErroRom, calcular_checksum, carregar_rom,
                             corrigir_cabecalho, hashes)


def test_checksum_conhecido():
    rom = bytearray(0x204)
    rom[0x200:0x204] = b"\x00\x01\x00\x02"
    assert calcular_checksum(rom) == 0x0003


def test_checksum_tamanho_impar():
    rom = bytearray(0x203)
    rom[0x200:0x203] = b"\x00\x01\x02"
    assert calcular_checksum(rom) == 0x0201


def test_corrigir_cabecalho(rom_sintetica):
    rom = rom_sintetica
    rom[0x18E:0x190] = b"\x00\x00"
    corrigir_cabecalho(rom)
    assert int.from_bytes(rom[0x18E:0x190], "big") == calcular_checksum(rom)
    assert int.from_bytes(rom[0x1A4:0x1A8], "big") == len(rom) - 1


def test_hash_divergente(tmp_path, rom_sintetica):
    arq = tmp_path / "r.bin"
    arq.write_bytes(rom_sintetica)
    with pytest.raises(ErroRom) as e:
        carregar_rom(arq, {"sha1": "00" * 20})
    msg = str(e.value)
    assert "esperado" in msg
    assert hashes(bytes(rom_sintetica))["sha1"] in msg


def test_hash_correto(tmp_path, rom_sintetica):
    arq = tmp_path / "r.bin"
    arq.write_bytes(rom_sintetica)
    sha1 = hashes(bytes(rom_sintetica))["sha1"]
    assert carregar_rom(arq, {"sha1": sha1}) == rom_sintetica


def test_formato_smd(tmp_path):
    arq = tmp_path / "r.smd"
    arq.write_bytes(bytes(512 + 0x8000))
    with pytest.raises(ErroRom, match="SMD"):
        carregar_rom(arq, None)


def test_esperado_none_aceita(tmp_path, rom_sintetica):
    arq = tmp_path / "r.bin"
    arq.write_bytes(rom_sintetica)
    assert isinstance(carregar_rom(arq, None), bytearray)
    assert carregar_rom(arq, {"sha1": None}) == rom_sintetica


def test_arquivo_inexistente(tmp_path):
    with pytest.raises(ErroRom, match="não encontrad"):
        carregar_rom(tmp_path / "nada.bin", None)


def test_hashes_formato():
    h = hashes(b"abc")
    assert h["sha1"] == "a9993e364706816aba3e25717850c26c9cd0d89d"
    assert h["crc32"] == "352441c2"
