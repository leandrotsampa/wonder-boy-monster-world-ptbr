import random

import pytest

from ferramentas.rom import corrigir_cabecalho


@pytest.fixture
def rom_sintetica() -> bytearray:
    rnd = random.Random(1234)
    rom = bytearray(0x8000)
    rom[0x100:0x110] = b"SEGA MEGA DRIVE "
    rom[0x200:] = bytes(rnd.randrange(256) for _ in range(0x8000 - 0x200))
    corrigir_cabecalho(rom)
    return rom


@pytest.fixture(scope="session")
def rom_base() -> bytes:
    """ROM base real (validada por sha1 em config/rom.yaml); skip se ausente."""
    import hashlib
    from pathlib import Path

    from ferramentas.config import carregar_projeto

    projeto = carregar_projeto(Path(__file__).resolve().parent.parent)
    caminho = projeto.caminho_rom
    if not caminho.is_file():
        pytest.skip("ROM base ausente")
    dados = caminho.read_bytes()
    if hashlib.sha1(dados).hexdigest() != str(projeto.rom.get("sha1", "")).lower():
        pytest.skip("ROM base ausente (sha1 diferente do configurado)")
    return dados


@pytest.fixture(scope="session")
def caminho_rom_base(rom_base) -> "Path":
    """Caminho da ROM base validada (pula se ausente, via rom_base)."""
    from pathlib import Path

    from ferramentas.config import carregar_projeto

    return carregar_projeto(Path(__file__).resolve().parent.parent).caminho_rom


@pytest.fixture(scope="session")
def _emulador_sessao(caminho_rom_base):
    """Uma instância só por processo: cores libretro guardam estado global."""
    from ferramentas.emulador.libretro import CORE_PADRAO, Emulador

    if not CORE_PADRAO.is_file():
        pytest.skip("core libretro ausente (ver README, seção Emulador para testes)")
    emu = Emulador(CORE_PADRAO, caminho_rom_base)
    yield emu
    emu.fechar()


@pytest.fixture
def emulador(_emulador_sessao):
    """Emulador recém-ligado (reset + estado inicial restaurado) a cada teste."""
    _emulador_sessao.reiniciar()
    return _emulador_sessao
