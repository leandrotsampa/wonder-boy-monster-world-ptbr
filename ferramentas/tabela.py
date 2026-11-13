"""Tabela de caracteres no estilo Thingy (.tbl)."""

from __future__ import annotations

import re
from pathlib import Path

_LITERAL = re.compile(r"\[\$([0-9A-Fa-f]{2})\]")


class ErroTabela(Exception):
    pass


class Tabela:
    def __init__(self, mapa: dict[bytes, str]):
        self._dec = dict(mapa)
        self._enc: dict[str, bytes] = {}
        for chave, valor in mapa.items():
            self._enc.setdefault(valor, chave)
        self._max_bytes = max((len(k) for k in mapa), default=1)
        self._max_texto = max((len(v) for v in self._enc), default=1)

    @classmethod
    def de_texto(cls, texto: str) -> "Tabela":
        mapa: dict[bytes, str] = {}
        for n, linha in enumerate(texto.splitlines(), 1):
            linha = linha.rstrip("\r")
            if not linha.strip() or linha.lstrip().startswith("#"):
                continue
            if "=" not in linha:
                raise ErroTabela(f"linha {n}: formato inválido (esperado HEX=valor): {linha!r}")
            hexa, valor = linha.split("=", 1)
            try:
                chave = bytes.fromhex(hexa.strip())
            except ValueError:
                raise ErroTabela(f"linha {n}: hexadecimal inválido: {hexa!r}") from None
            if not chave or valor == "":
                raise ErroTabela(f"linha {n}: entrada vazia: {linha!r}")
            if chave in mapa:
                raise ErroTabela(f"linha {n}: hex duplicado {chave.hex().upper()}")
            mapa[chave] = valor
        return cls(mapa)

    @classmethod
    def carregar(cls, caminho: Path) -> "Tabela":
        return cls.de_texto(Path(caminho).read_text(encoding="utf-8"))

    def entradas(self) -> dict[bytes, str]:
        """Todas as entradas (bytes -> valor), na ordem do arquivo."""
        return dict(self._dec)

    def caracteres(self) -> set[str]:
        return {v for v in self._enc if not (v.startswith("[") and v.endswith("]"))}

    def decodificar(self, dados: bytes) -> str:
        saida = []
        i = 0
        while i < len(dados):
            for tam in range(min(self._max_bytes, len(dados) - i), 0, -1):
                valor = self._dec.get(bytes(dados[i:i + tam]))
                if valor is not None:
                    saida.append(valor)
                    i += tam
                    break
            else:
                saida.append(f"[${dados[i]:02X}]")
                i += 1
        return "".join(saida)

    def codificar(self, texto: str, id_entrada: str = "?") -> bytes:
        saida = bytearray()
        i = 0
        while i < len(texto):
            # o literal [$XX] tem prioridade: "[" pode ser um caractere da tabela
            m = _LITERAL.match(texto, i)
            if m:
                saida.append(int(m.group(1), 16))
                i = m.end()
                continue
            for tam in range(min(self._max_texto, len(texto) - i), 0, -1):
                b = self._enc.get(texto[i:i + tam])
                if b is not None:
                    saida += b
                    i += tam
                    break
            else:
                if texto[i] == "[" and "]" in texto[i:]:
                    codigo = texto[i:texto.index("]", i) + 1]
                    raise ErroTabela(
                        f"{id_entrada}: código de controle desconhecido {codigo} (posição {i})"
                    )
                raise ErroTabela(
                    f"{id_entrada}: caractere {texto[i]!r} não existe na tabela (posição {i})"
                )
        return bytes(saida)
