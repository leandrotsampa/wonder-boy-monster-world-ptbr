"""Geração e aplicação de patches IPS."""

from __future__ import annotations

CABECALHO = b"PATCH"
FIM = b"EOF"
OFFSET_PROIBIDO = 0x454F46  # bytes "EOF" — um registro aqui seria lido como fim
MAX_REGISTRO = 0xFFFF
MAX_OFFSET = 0xFFFFFF


class ErroIps(Exception):
    pass


def _trechos(original: bytes, modificado: bytes) -> list[tuple[int, int]]:
    """Trechos contínuos [inicio, fim) onde modificado difere (ou excede) o original."""
    trechos = []
    n_orig = len(original)
    i, n = 0, len(modificado)
    while i < n:
        if i < n_orig and original[i] == modificado[i]:
            i += 1
            continue
        ini = i
        while i < n and (i >= n_orig or original[i] != modificado[i]):
            i += 1
        trechos.append((ini, i))
    return trechos


def gerar_ips(original: bytes, modificado: bytes) -> bytes:
    if len(modificado) < len(original):
        raise ErroIps("IPS não suporta reduzir a ROM")
    if len(modificado) - 1 > MAX_OFFSET:
        raise ErroIps("ROM maior que 16 MB não cabe em IPS")
    saida = bytearray(CABECALHO)
    for ini, fim in _trechos(original, modificado):
        if ini == OFFSET_PROIBIDO:
            ini -= 1
        pos = ini
        while pos < fim:
            tam = min(MAX_REGISTRO, fim - pos)
            if pos == OFFSET_PROIBIDO:
                # só acontece numa quebra de registro; recua 1 byte
                pos -= 1
                tam = min(MAX_REGISTRO, fim - pos)
            saida += pos.to_bytes(3, "big") + tam.to_bytes(2, "big")
            saida += modificado[pos:pos + tam]
            pos += tam
    saida += FIM
    return bytes(saida)


def aplicar_ips(original: bytes, patch: bytes) -> bytes:
    if patch[:5] != CABECALHO:
        raise ErroIps("patch IPS inválido: cabeçalho 'PATCH' ausente")
    rom = bytearray(original)
    i = 5
    while True:
        if patch[i:i + 3] == FIM:
            break
        if i + 5 > len(patch):
            raise ErroIps("patch IPS truncado")
        off = int.from_bytes(patch[i:i + 3], "big")
        tam = int.from_bytes(patch[i + 3:i + 5], "big")
        i += 5
        if tam == 0:  # registro RLE
            if i + 3 > len(patch):
                raise ErroIps("patch IPS truncado")
            tam = int.from_bytes(patch[i:i + 2], "big")
            dados = patch[i + 2:i + 3] * tam
            i += 3
        else:
            if i + tam > len(patch):
                raise ErroIps("patch IPS truncado")
            dados = patch[i:i + tam]
            i += tam
        if off + tam > len(rom):
            rom.extend(bytes(off + tam - len(rom)))
        rom[off:off + tam] = dados
    return bytes(rom)
