"""Format dels números a la interfície, a la catalana (1.868; 0,42 %)."""


def num(value: float, decimals: int = 0) -> str:
    """
    :param value: el número.
    :param decimals: decimals.
    :return: amb punt de milers i coma decimal.
    """
    text = f"{value:,.{decimals}f}"
    return text.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def pct(share: float, decimals: int = 2) -> str:
    """
    :param share: proporció entre 0 i 1.
    :param decimals: decimals.
    :return: el percentatge amb coma decimal (p.e. 0,42 %).
    """
    return f"{num(share * 100, decimals)} %"


def size(n_bytes: float) -> str:
    """
    :param n_bytes: mida en bytes.
    :return: en KB, MB o GB (1 MB = 1024² bytes, com `--max-dataset-mb`), amb un decimal (p.e. 5,8 GB).
    """
    for unit, power in (("GB", 3), ("MB", 2), ("KB", 1)):
        if n_bytes >= 1024**power:
            return f"{num(n_bytes / 1024**power, 1)} {unit}"
    return f"{num(n_bytes)} B"
