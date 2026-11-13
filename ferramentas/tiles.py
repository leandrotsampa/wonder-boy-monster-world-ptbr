"""Tiles 4bpp do Mega Drive <-> PNG indexado, e paletas (CRAM)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

BYTES_TILE = 32


class ErroTiles(Exception):
    pass


def cor_md_para_rgb(palavra: int) -> tuple[int, int, int]:
    r = (palavra >> 1) & 7
    g = (palavra >> 5) & 7
    b = (palavra >> 9) & 7
    return (r * 36, g * 36, b * 36)


def rgb_para_cor_md(rgb: tuple[int, int, int]) -> int:
    r, g, b = (min(7, max(0, round(c / 36))) for c in rgb[:3])
    return (b << 9) | (g << 5) | (r << 1)


def paleta_de_bytes(dados: bytes) -> list[tuple[int, int, int]]:
    if len(dados) < 32:
        raise ErroTiles("paleta precisa de 32 bytes")
    return [cor_md_para_rgb(int.from_bytes(dados[i:i + 2], "big")) for i in range(0, 32, 2)]


def tiles_para_png(dados: bytes, largura_tiles: int, paleta: list[tuple[int, int, int]],
                   caminho: Path) -> None:
    if len(dados) % BYTES_TILE:
        raise ErroTiles(f"tamanho {len(dados)} não é múltiplo de {BYTES_TILE}")
    n = len(dados) // BYTES_TILE
    largura_tiles = max(1, min(largura_tiles, n or 1))
    altura_tiles = max(1, -(-n // largura_tiles))
    w, h = largura_tiles * 8, altura_tiles * 8
    pixels = bytearray(w * h)
    for t in range(n):
        tx, ty = (t % largura_tiles) * 8, (t // largura_tiles) * 8
        base = t * BYTES_TILE
        for y in range(8):
            for xb in range(4):
                byte = dados[base + y * 4 + xb]
                pos = (ty + y) * w + tx + xb * 2
                pixels[pos] = byte >> 4
                pixels[pos + 1] = byte & 0x0F
    img = Image.frombytes("P", (w, h), bytes(pixels))
    plano = [c for cor in paleta[:16] for c in cor]
    img.putpalette(plano + [0] * (768 - len(plano)))
    img.save(caminho)


def png_para_tiles(caminho: Path, quantidade: int | None = None) -> bytes:
    img = Image.open(caminho)
    if img.mode != "P":
        raise ErroTiles(f"{Path(caminho).name}: PNG precisa ser indexado (modo P), é {img.mode}")
    w, h = img.size
    if w % 8 or h % 8:
        raise ErroTiles(f"{Path(caminho).name}: dimensões {w}x{h} não são múltiplas de 8")
    pixels = img.tobytes()
    if max(pixels, default=0) > 15:
        i = next(i for i, p in enumerate(pixels) if p > 15)
        raise ErroTiles(
            f"{Path(caminho).name}: pixel ({i % w},{i // w}) usa índice {pixels[i]} (máximo 15)"
        )
    saida = bytearray()
    for ty in range(0, h, 8):
        for tx in range(0, w, 8):
            for y in range(8):
                linha = (ty + y) * w + tx
                for xb in range(0, 8, 2):
                    saida.append((pixels[linha + xb] << 4) | pixels[linha + xb + 1])
    if quantidade is not None:
        saida = saida[:quantidade * BYTES_TILE]
    return bytes(saida)
