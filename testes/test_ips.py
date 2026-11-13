import pytest

from ferramentas.ips import ErroIps, aplicar_ips, gerar_ips


def _registros(patch: bytes):
    assert patch[:5] == b"PATCH"
    i = 5
    out = []
    while patch[i:i + 3] != b"EOF":
        off = int.from_bytes(patch[i:i + 3], "big")
        tam = int.from_bytes(patch[i + 3:i + 5], "big")
        out.append((off, tam))
        i += 5 + tam
    assert i + 3 == len(patch)
    return out


def test_ida_e_volta(rom_sintetica):
    a = bytes(rom_sintetica)
    b = bytearray(a)
    b[0x300] ^= 0xFF
    b[0x1000:0x1010] = bytes(16)
    b[-1] ^= 0x01
    assert aplicar_ips(a, gerar_ips(a, bytes(b))) == bytes(b)


def test_sem_diferencas(rom_sintetica):
    a = bytes(rom_sintetica)
    assert gerar_ips(a, a) == b"PATCHEOF"


def test_expansao(rom_sintetica):
    a = bytes(rom_sintetica)
    b = a + b"\xff" * 0x10000
    assert aplicar_ips(a, gerar_ips(a, b)) == b


def test_expansao_com_zeros(rom_sintetica):
    a = bytes(rom_sintetica)
    b = a + bytes(0x100)
    assert aplicar_ips(a, gerar_ips(a, b)) == b


def test_regiao_maior_que_ffff():
    a = bytes(0x30000)
    b = bytes(0x1000) + b"\x01" * 0x20000 + bytes(0xF000)
    patch = gerar_ips(a, b)
    assert all(t <= 0xFFFF for _, t in _registros(patch))
    assert aplicar_ips(a, patch) == b


def test_offset_eof():
    a = bytes(0x460000)
    b = bytearray(a)
    b[0x454F46] = 1
    patch = gerar_ips(a, bytes(b))
    assert all(off != 0x454F46 for off, _ in _registros(patch))
    assert aplicar_ips(a, patch) == bytes(b)


def test_patch_invalido(rom_sintetica):
    with pytest.raises(ErroIps):
        aplicar_ips(bytes(rom_sintetica), b"XXXX")


def test_patch_truncado(rom_sintetica):
    with pytest.raises(ErroIps):
        aplicar_ips(bytes(rom_sintetica), b"PATCH\x00\x10\x00\x00\x05ab")


def test_reducao(rom_sintetica):
    a = bytes(rom_sintetica)
    with pytest.raises(ErroIps):
        gerar_ips(a, a[:-2])
