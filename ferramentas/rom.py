"""Carga, validação e checksum do cabeçalho de ROMs do Mega Drive."""

from __future__ import annotations

import hashlib
import zlib
from pathlib import Path

OFFSET_CHECKSUM = 0x18E
OFFSET_FIM_ROM = 0x1A4
INICIO_SOMA = 0x200


class ErroRom(Exception):
    pass


def hashes(dados: bytes) -> dict[str, str]:
    return {
        "sha1": hashlib.sha1(dados).hexdigest(),
        "crc32": "%08x" % (zlib.crc32(dados) & 0xFFFFFFFF),
    }


def _parece_smd(dados: bytes) -> bool:
    return len(dados) % 0x4000 == 512 and dados[0x100:0x104] != b"SEGA"


def carregar_rom(caminho: Path, esperado: dict | None) -> bytearray:
    caminho = Path(caminho)
    if not caminho.is_file():
        raise ErroRom(f"ROM não encontrada: {caminho}")
    dados = caminho.read_bytes()
    if _parece_smd(dados):
        raise ErroRom(
            f"{caminho.name}: ROM em formato SMD (cabeçalho de 512 bytes/entrelaçada); "
            "converta para .bin antes de usar."
        )
    if esperado and esperado.get("sha1"):
        obtido = hashes(dados)["sha1"]
        if obtido != esperado["sha1"].lower():
            raise ErroRom(
                f"{caminho.name}: hash SHA-1 não confere.\n"
                f"  esperado: {esperado['sha1']}\n  obtido:   {obtido}"
            )
    return bytearray(dados)


def calcular_checksum(rom: bytes) -> int:
    corpo = bytes(rom[INICIO_SOMA:])
    if len(corpo) % 2:
        corpo += b"\x00"
    soma = 0
    for i in range(0, len(corpo), 2):
        soma += (corpo[i] << 8) | corpo[i + 1]
    return soma & 0xFFFF


def corrigir_cabecalho(rom: bytearray) -> None:
    rom[OFFSET_CHECKSUM:OFFSET_CHECKSUM + 2] = calcular_checksum(rom).to_bytes(2, "big")
    rom[OFFSET_FIM_ROM:OFFSET_FIM_ROM + 4] = (len(rom) - 1).to_bytes(4, "big")
