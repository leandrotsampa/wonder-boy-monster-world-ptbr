import random

import pytest
from PIL import Image

from ferramentas.tiles import (ErroTiles, cor_md_para_rgb, paleta_de_bytes,
                               png_para_tiles, rgb_para_cor_md, tiles_para_png)

PALETA = [(i * 16, i * 16, i * 16) for i in range(16)]


def test_cor():
    assert cor_md_para_rgb(0x0EEE) == (252, 252, 252)
    assert cor_md_para_rgb(0x000E) == (252, 0, 0)
    assert cor_md_para_rgb(0x0E00) == (0, 0, 252)
    assert rgb_para_cor_md((250, 0, 0)) == 0x000E
    for w in (0x0000, 0x0246, 0x0ACE, 0x0EEE):
        assert rgb_para_cor_md(cor_md_para_rgb(w)) == w


def test_paleta_de_bytes():
    dados = b"\x0e\xee" + b"\x00\x00" * 15
    p = paleta_de_bytes(dados)
    assert len(p) == 16 and p[0] == (252, 252, 252) and p[1] == (0, 0, 0)


def test_tile_conhecido(tmp_path):
    dados = b"\x12" + bytes(31)
    arq = tmp_path / "t.png"
    tiles_para_png(dados, 1, PALETA, arq)
    img = Image.open(arq)
    assert img.mode == "P" and img.size == (8, 8)
    assert img.getpixel((0, 0)) == 1 and img.getpixel((1, 0)) == 2


def test_ida_e_volta(tmp_path):
    rnd = random.Random(7)
    dados = bytes(rnd.randrange(256) for _ in range(32 * 10))
    arq = tmp_path / "t.png"
    tiles_para_png(dados, 4, PALETA, arq)
    assert Image.open(arq).size == (32, 24)
    assert png_para_tiles(arq, 10) == dados


def test_png_nao_indexado(tmp_path):
    arq = tmp_path / "rgb.png"
    Image.new("RGB", (8, 8)).save(arq)
    with pytest.raises(ErroTiles):
        png_para_tiles(arq)


def test_dimensao_invalida(tmp_path):
    arq = tmp_path / "p.png"
    Image.new("P", (10, 8)).save(arq)
    with pytest.raises(ErroTiles):
        png_para_tiles(arq)


def test_indice_maior_que_15(tmp_path):
    arq = tmp_path / "p.png"
    img = Image.new("P", (8, 8))
    img.putpalette([0] * 768)
    img.putpixel((3, 3), 16)
    img.save(arq)
    with pytest.raises(ErroTiles):
        png_para_tiles(arq)
